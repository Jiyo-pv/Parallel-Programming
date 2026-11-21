"""Engine bridge: talks to the C++ MPI/OpenMP engine over stdin/stdout, or falls back to a pure-Python engine."""
import heapq
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(HERE)
ENGINE_DIR = os.path.join(ROOT, "engine")
BIG = 1000000


def find_mpiexec():
    for p in (
        os.path.join(ROOT, "mpi", "mpiexec.exe"),
        os.path.join(ROOT, "mpi", "mpiexec"),
        r"C:\Program Files\Microsoft MPI\Bin\mpiexec.exe",
    ):
        if os.path.exists(p):
            return p
    return shutil.which("mpiexec")


def encode_batch(d):
    cfg = d["cfg"]
    out = ["GRID %d %d" % (len(d["grid"][0]), len(d["grid"]))]
    out += d["grid"]
    out.append("DOCKS %d" % len(d["docks"]))
    out += ["%d %d" % p for p in d["docks"]]
    out.append("IDLE %d" % len(d["idle"]))
    out += ["%d %d %d %d %d" % r for r in d["idle"]]
    out.append("BUSY %d" % len(d["busy"]))
    for rid, pts in d["busy"]:
        out.append("%d %d %s" % (rid, len(pts) - 1, " ".join("%d %d" % p for p in pts)))
    out.append("TASKS %d" % len(d["tasks"]))
    out += ["%d %d %d" % t for t in d["tasks"]]
    out.append("CFG %d %d %d %d" % (cfg.get("pick", 2), cfg.get("drop", 2), cfg.get("threads", 0), cfg.get("sched", 1)))
    out.append("GO")
    return "\n".join(out) + "\n"


class ProcessEngine:
    """Runs engine exe (optionally under mpiexec) as a persistent child process."""

    def __init__(self, cmd, label):
        self.label = label
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1)
        line = self.proc.stdout.readline().strip()
        if not line.startswith("READY"):
            err = ""
            try:
                self.proc.kill()
                err = self.proc.stderr.read()
            except Exception:
                pass
            raise RuntimeError("engine failed to start: %r %s" % (line, err[:300]))
        parts = line.split()
        self.ranks, self.threads = int(parts[1]), int(parts[2])
        self.label = "%s  (%d rank%s x %d thread%s)" % (label, self.ranks, "" if self.ranks == 1 else "s",
                                                        self.threads, "" if self.threads == 1 else "s")

    def plan(self, d):
        self.proc.stdin.write(encode_batch(d))
        self.proc.stdin.flush()
        timing, assign = None, []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("engine died: " + self.proc.stderr.read()[:300])
            line = line.strip()
            if line == "END":
                break
            if line.startswith("TIMING"):
                v = line.split()[1:]
                timing = {"k1": float(v[0]), "k3": float(v[1]), "k4": float(v[2]), "total": float(v[3]),
                          "ranks": int(v[4]), "threads": int(v[5]), "rounds": int(v[6])}
            elif line.startswith("ASSIGN"):
                continue
            elif line:
                v = list(map(int, line.split()))
                rid, tid, pickT, dropT, n = v[:5]
                pts = [(v[5 + 2 * i], v[6 + 2 * i]) for i in range(n)]
                assign.append((rid, tid, pickT, dropT, pts))
        return {"timing": timing, "assign": assign}

    def close(self):
        try:
            self.proc.stdin.write("QUIT\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


# ----------------------------------------------------------------------------- pure python fallback
class PyEngine:
    """Serial reference implementation (same protocol result). Used when no compiled engine is available."""
    label = "Python fallback engine (serial)"

    def __init__(self):
        self.ranks, self.threads = 1, 1

    def close(self):
        pass

    def plan(self, d):
        t0 = time.perf_counter()
        grid = d["grid"]
        W, H = len(grid[0]), len(grid)
        blocked = [[c == "#" for c in row] for row in grid]
        docks, idle, tasks = d["docks"], d["idle"], d["tasks"]
        pick, drop = max(1, d["cfg"].get("pick", 2)), max(1, d["cfg"].get("drop", 2))

        def bfs(src):
            dist = {src: 0}
            q = [src]
            for c in q:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c[0] + dx, c[1] + dy)
                    if 0 <= n[0] < W and 0 <= n[1] < H and not blocked[n[1]][n[0]] and n not in dist:
                        dist[n] = dist[c] + 1
                        q.append(n)
            return dist

        cost = []
        for (tid, ax, ay) in tasks:
            dist = bfs((ax, ay))
            dk = docks[tid % len(docks)]
            dc = dist.get(dk, BIG)
            cost.append([(dist.get((r[1], r[2]), BIG) + dc) if dc < BIG else BIG for r in idle])
        k1 = (time.perf_counter() - t0) * 1000
        # greedy global-min assignment
        cand = sorted((cost[t][r], r, t) for t in range(len(tasks)) for r in range(len(idle)) if cost[t][r] < BIG)
        ur, ut, pairs = set(), set(), []
        for c, r, t in cand:
            if r not in ur and t not in ut:
                ur.add(r); ut.add(t); pairs.append((r, t))
        pairs.sort()
        k3 = (time.perf_counter() - t0) * 1000 - k1
        # reservations
        vtx, edge, perm, last = set(), set(), {}, {}

        def add(s, path):
            vtx.add((s[0], s[1], 0)); last[s] = max(last.get(s, 0), 0)
            prev = s
            for i, p in enumerate(path):
                t = i + 1
                vtx.add((p[0], p[1], t)); last[p] = max(last.get(p, 0), t)
                edge.add((prev, p, t)); prev = p
            perm[prev] = min(perm.get(prev, 10 ** 9), len(path))

        def blk(x, y, t):
            return (x, y, t) in vtx or ((x, y) in perm and t >= perm[(x, y)])

        assigned = {idle[r][0] for r, _ in pairs}
        for r in idle:
            if r[0] not in assigned and r[1] == r[3] and r[2] == r[4]:
                perm[(r[1], r[2])] = 0
        for rid, pts in d["busy"]:
            add(pts[0], pts[1:])

        def leg(s, t0_, g, wait, final):
            maxT = t0_ + 3 * (W + H) + 120
            h = lambda x, y: abs(x - g[0]) + abs(y - g[1])
            pq = [(t0_ + h(*s), t0_, s[0], s[1])]
            parent, closed = {(s[0], s[1], t0_): None}, set()
            while pq:
                f, t, x, y = heapq.heappop(pq)
                if (x, y, t) in closed:
                    continue
                closed.add((x, y, t))
                if (x, y) == tuple(g):
                    ok = all(not blk(x, y, t + w) for w in range(1, wait + 1))
                    if ok and final:
                        ok = (x, y) not in perm and last.get((x, y), -1) < t
                    if ok:
                        out, k = [], (x, y, t)
                        while parent[k] is not None:
                            out.append((k[0], k[1])); k = parent[k]
                        return out[::-1], t
                if t >= maxT:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < W and 0 <= ny < H) or blocked[ny][nx] or blk(nx, ny, t + 1):
                        continue
                    if (dx or dy) and (((nx, ny), (x, y), t + 1) in edge):
                        continue
                    nk = (nx, ny, t + 1)
                    if nk in closed:
                        continue
                    parent.setdefault(nk, (x, y, t))
                    heapq.heappush(pq, (t + 1 + h(nx, ny), t + 1, nx, ny))
            return None, 0

        assign = []
        for r, t in pairs:
            rid, rx, ry, hx, hy = idle[r]
            tid, ax, ay = tasks[t]
            dk = tuple(docks[tid % len(docks)])
            s = (rx, ry); path = []; tc = 0
            seg, te = leg(s, tc, (ax, ay), pick, False)
            if seg is None:
                continue
            path += seg + [(ax, ay)] * pick; tc = te + pick; pickT = len(path)
            seg, te = leg((ax, ay), tc, dk, drop, False)
            if seg is None:
                continue
            path += seg + [dk] * drop; tc = te + drop; dropT = len(path)
            seg, te = leg(dk, tc, (hx, hy), 0, True)
            if seg is None:
                continue
            path += seg
            add(s, path)
            assign.append((rid, tid, pickT, dropT, path))
        total = (time.perf_counter() - t0) * 1000
        return {"timing": {"k1": k1, "k3": k3, "k4": total - k1 - k3, "total": total, "ranks": 1,
                           "threads": 1, "rounds": 0}, "assign": assign}


def start_engine(ranks=1, threads=0, hosts=None, prefer="auto"):
    """Pick the best available engine.  hosts = [(ip, cores), ...] enables cluster mode."""
    mpi_exe = os.path.join(ENGINE_DIR, "engine_mpi.exe")
    ser_exe = os.path.join(ENGINE_DIR, "engine_serial.exe")
    omp_exe = os.path.join(ENGINE_DIR, "engine_omp.exe")
    mpiexec = find_mpiexec()
    errors = []
    if prefer != "python":
        if hosts and mpiexec and os.path.exists(mpi_exe):
            cmd = [mpiexec]
            for i, (ip, cores) in enumerate(hosts):
                if i:
                    cmd.append(":")
                cmd += ["-n", "1", "-host", ip, "-env", "OMP_NUM_THREADS", str(cores), mpi_exe]
            try:
                return ProcessEngine(cmd, "C++ MPI+OpenMP cluster")
            except Exception as e:
                errors.append(str(e))
        if mpiexec and os.path.exists(mpi_exe):
            try:
                env_cmd = [mpiexec, "-n", str(max(1, ranks))]
                if threads > 0:
                    env_cmd += ["-env", "OMP_NUM_THREADS", str(threads)]
                return ProcessEngine(env_cmd + [mpi_exe], "C++ MPI+OpenMP")
            except Exception as e:
                errors.append(str(e))
        for exe, lab in ((omp_exe, "C++ OpenMP"), (ser_exe, "C++ serial")):
            if os.path.exists(exe):
                try:
                    return ProcessEngine([exe], lab)
                except Exception as e:
                    errors.append(str(e))
    eng = PyEngine()
    eng.errors = errors
    return eng
