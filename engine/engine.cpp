// Parallel Warehouse Engine  (MPI + OpenMP)
//
// Persistent planning process.  Reads batches from stdin (rank 0), writes plans to stdout (rank 0).
//   K1  distance fields   : BFS from every task's shelf-access cell      (OpenMP over tasks, MPI cyclic split)
//   K3  robot-task assign : integer Bertsekas auction (exact optimum)    (OpenMP over bidders, MPI split + Allgather)
//   K4  path planning     : static A* in parallel (OpenMP + MPI), then conflict detection and
//                           space-time A* replanning of the conflicting robots (rank 0)
//
// Build flags: -DUSE_MPI (needs MPI),  -fopenmp or /openmp (needs OpenMP).  Both optional: without
// them the very same code runs serially, which is the baseline for the speedup measurements.
#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <queue>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#ifdef USE_MPI
#include <mpi.h>
#endif
#ifdef _OPENMP
#include <omp.h>
#endif

using namespace std;

static int g_rank = 0, g_size = 1;
static const int BIG = 1000000;  // "unreachable" cost

static double now_ms() {
    return chrono::duration<double, milli>(chrono::steady_clock::now().time_since_epoch()).count();
}

struct Pt { int x, y; };

// ---------------------------------------------------------------- world state of one batch
static int W = 0, H = 0;
static vector<char> blockedCell;  // 1 = wall / shelf
static inline int cid(int x, int y) { return y * W + x; }
static inline bool inb(int x, int y) { return x >= 0 && y >= 0 && x < W && y < H; }
static const int DX[4] = {1, -1, 0, 0}, DY[4] = {0, 0, 1, -1};

struct RobotIn { int id, x, y, hx, hy; };
struct BusyIn { int id; vector<Pt> p; };  // p[0] = current cell, p[k] = cell at tick k
struct TaskIn { int id, ax, ay; };
struct Input {
    vector<Pt> docks;
    vector<RobotIn> idle;
    vector<BusyIn> busy;
    vector<TaskIn> tasks;
    int pickW = 2, dropW = 2, threads = 0, sched = 1;
};

// ---------------------------------------------------------------- MPI helpers
static vector<vector<char>> allgatherBytes(const vector<char>& local) {
    vector<vector<char>> out(g_size);
#ifdef USE_MPI
    if (g_size > 1) {
        int n = (int)local.size();
        vector<int> counts(g_size), displs(g_size, 0);
        MPI_Allgather(&n, 1, MPI_INT, counts.data(), 1, MPI_INT, MPI_COMM_WORLD);
        int tot = 0;
        for (int i = 0; i < g_size; i++) { displs[i] = tot; tot += counts[i]; }
        vector<char> all(tot > 0 ? tot : 1);
        MPI_Allgatherv(local.data(), n, MPI_CHAR, all.data(), counts.data(), displs.data(), MPI_CHAR,
                       MPI_COMM_WORLD);
        for (int i = 0; i < g_size; i++) out[i].assign(all.begin() + displs[i], all.begin() + displs[i] + counts[i]);
        return out;
    }
#endif
    out[0] = local;
    return out;
}
template <class T> static void put(vector<char>& b, const T& v) {
    const char* p = reinterpret_cast<const char*>(&v);
    b.insert(b.end(), p, p + sizeof(T));
}
struct Reader {
    const vector<char>& b; size_t pos = 0;
    explicit Reader(const vector<char>& bb) : b(bb) {}
    template <class T> T get() { T v; memcpy(&v, b.data() + pos, sizeof(T)); pos += sizeof(T); return v; }
    bool done() const { return pos >= b.size(); }
};

// ---------------------------------------------------------------- static A* (grid walls only)
static bool astarStatic(Pt s, Pt g, vector<Pt>& out) {
    out.clear();
    if (s.x == g.x && s.y == g.y) return true;
    int N = W * H;
    vector<int> gs(N, INT_MAX), par(N, -1);
    vector<char> closed(N, 0);
    typedef pair<int, int> QI;  // (f*N' + ..., cell) ordered by f then cell index (deterministic)
    priority_queue<QI, vector<QI>, greater<QI> > pq;
    auto hfun = [&](int x, int y) { return abs(x - g.x) + abs(y - g.y); };
    int sc = cid(s.x, s.y), gc = cid(g.x, g.y);
    gs[sc] = 0;
    pq.push(QI(hfun(s.x, s.y), sc));
    while (!pq.empty()) {
        int c = pq.top().second; pq.pop();
        if (closed[c]) continue;
        closed[c] = 1;
        if (c == gc) break;
        int cx = c % W, cy = c / W;
        for (int d = 0; d < 4; d++) {
            int nx = cx + DX[d], ny = cy + DY[d];
            if (!inb(nx, ny) || blockedCell[cid(nx, ny)]) continue;
            int nc = cid(nx, ny);
            if (closed[nc]) continue;
            int ng = gs[c] + 1;
            if (ng < gs[nc]) { gs[nc] = ng; par[nc] = c; pq.push(QI(ng + hfun(nx, ny), nc)); }
        }
    }
    if (gs[gc] == INT_MAX) return false;
    for (int c = gc; c != sc; c = par[c]) out.push_back(Pt{c % W, c / W});
    reverse(out.begin(), out.end());
    return true;
}

// ---------------------------------------------------------------- reservation table
struct Resv {
    unordered_set<long long> vtx, edge;
    unordered_map<int, int> perm;       // cell -> time from which it is blocked forever
    unordered_map<int, int> lastVisit;  // cell -> latest time any reserved path stands on it
    static long long vk(int x, int y, int t) { return ((long long)t * 4096 + y) * 4096 + x; }
    static long long ek(int x1, int y1, int x2, int y2, int t) {
        return ((((long long)t * 4096 + y1) * 4096 + x1) * 4096 + y2) * 4096 + x2;
    }
    bool blocked(int x, int y, int t) const {
        if (vtx.count(vk(x, y, t))) return true;
        auto it = perm.find(cid(x, y));
        return it != perm.end() && t >= it->second;
    }
    bool swapBlocked(int x1, int y1, int x2, int y2, int t) const {  // moving 1->2 arriving at t
        return edge.count(ek(x2, y2, x1, y1, t)) > 0;
    }
    bool endFree(int x, int y, int t) const {  // can stand at (x,y) from time t forever?
        if (perm.count(cid(x, y))) return false;
        auto it = lastVisit.find(cid(x, y));
        return it == lastVisit.end() || it->second < t;
    }
    void addPath(Pt s, const vector<Pt>& p) {  // p[k] = cell at time k+1 ; stays at last cell forever
        auto mark = [&](int x, int y, int t) {
            vtx.insert(vk(x, y, t));
            int& lv = lastVisit[cid(x, y)];
            if (lv < t) lv = t;
        };
        mark(s.x, s.y, 0);
        Pt prev = s;
        for (size_t k = 0; k < p.size(); k++) {
            int t = (int)k + 1;
            mark(p[k].x, p[k].y, t);
            edge.insert(ek(prev.x, prev.y, p[k].x, p[k].y, t));
            prev = p[k];
        }
        int c = cid(prev.x, prev.y), tt = (int)p.size();
        auto it = perm.find(c);
        if (it == perm.end() || it->second > tt) perm[c] = tt;
    }
    bool pathFree(Pt s, const vector<Pt>& p) const {
        if (blocked(s.x, s.y, 0)) return false;
        Pt prev = s;
        for (size_t k = 0; k < p.size(); k++) {
            int t = (int)k + 1;
            if (blocked(p[k].x, p[k].y, t)) return false;
            if (swapBlocked(prev.x, prev.y, p[k].x, p[k].y, t)) return false;
            prev = p[k];
        }
        return endFree(prev.x, prev.y, (int)p.size());
    }
};

// space-time A*: from (s, t0) to cell g, arrival must allow `waitTicks` free ticks after it.
static bool stLeg(const Resv& rv, Pt s, int t0, Pt g, int waitTicks, bool finalLeg, vector<Pt>& out, int& tEnd) {
    out.clear();
    int maxT = t0 + 3 * (W + H) + 120;
    typedef tuple<int, int, long long> QN;  // f, t, key
    priority_queue<QN, vector<QN>, greater<QN> > pq;
    unordered_map<long long, long long> parent;
    unordered_set<long long> closed;
    auto key = [&](int x, int y, int t) { return ((long long)t * H + y) * W + x; };
    auto hfun = [&](int x, int y) { return abs(x - g.x) + abs(y - g.y); };
    long long k0 = key(s.x, s.y, t0);
    parent[k0] = -1;
    pq.push(QN(t0 + hfun(s.x, s.y), t0, k0));
    while (!pq.empty()) {
        long long k = get<2>(pq.top()); pq.pop();
        if (closed.count(k)) continue;
        closed.insert(k);
        int x = (int)(k % W), y = (int)((k / W) % H), t = (int)(k / ((long long)W * H));
        if (x == g.x && y == g.y) {
            bool ok = true;
            for (int w = 1; w <= waitTicks && ok; w++) ok = !rv.blocked(x, y, t + w);
            if (ok && finalLeg) ok = rv.endFree(x, y, t);
            if (ok) {
                vector<Pt> rev;
                for (long long c = k; c != k0; c = parent[c]) {
                    int cx = (int)(c % W), cy = (int)((c / W) % H);
                    rev.push_back(Pt{cx, cy});
                }
                reverse(rev.begin(), rev.end());
                out = rev; tEnd = t;
                return true;
            }
        }
        if (t >= maxT) continue;
        for (int d = 0; d < 5; d++) {
            int nx = x + (d < 4 ? DX[d] : 0), ny = y + (d < 4 ? DY[d] : 0);
            if (!inb(nx, ny) || blockedCell[cid(nx, ny)]) continue;
            if (rv.blocked(nx, ny, t + 1)) continue;
            if (d < 4 && rv.swapBlocked(x, y, nx, ny, t + 1)) continue;
            long long nk = key(nx, ny, t + 1);
            if (closed.count(nk)) continue;
            if (!parent.count(nk)) parent[nk] = k;
            pq.push(QN(t + 1 + hfun(nx, ny), t + 1, nk));
        }
    }
    return false;
}

struct PlanPath { bool ok = false; vector<Pt> path; int pickT = 0, dropT = 0; };

// ---------------------------------------------------------------- parse input
static bool parseInput(const string& text, Input& in, bool& quit) {
    quit = false;
    istringstream ss(text);
    string tok;
    in = Input();
    int gw = 0, gh = 0;
    while (ss >> tok) {
        if (tok == "QUIT") { quit = true; return true; }
        if (tok == "GRID") {
            ss >> gw >> gh;
            W = gw; H = gh;
            blockedCell.assign(W * H, 0);
            for (int y = 0; y < H; y++) {
                string row; ss >> row;
                for (int x = 0; x < W && x < (int)row.size(); x++) blockedCell[cid(x, y)] = (row[x] == '#');
            }
        } else if (tok == "DOCKS") {
            int n; ss >> n;
            for (int i = 0; i < n; i++) { Pt p; ss >> p.x >> p.y; in.docks.push_back(p); }
        } else if (tok == "IDLE") {
            int n; ss >> n;
            for (int i = 0; i < n; i++) { RobotIn r; ss >> r.id >> r.x >> r.y >> r.hx >> r.hy; in.idle.push_back(r); }
        } else if (tok == "BUSY") {
            int n; ss >> n;
            for (int i = 0; i < n; i++) {
                BusyIn b; int len; ss >> b.id >> len;
                for (int k = 0; k <= len; k++) { Pt p; ss >> p.x >> p.y; b.p.push_back(p); }
                in.busy.push_back(b);
            }
        } else if (tok == "TASKS") {
            int n; ss >> n;
            for (int i = 0; i < n; i++) { TaskIn t; ss >> t.id >> t.ax >> t.ay; in.tasks.push_back(t); }
        } else if (tok == "CFG") {
            ss >> in.pickW >> in.dropW >> in.threads >> in.sched;
        } else if (tok == "GO") {
            break;
        }
    }
    if (in.pickW < 1) in.pickW = 1;
    if (in.dropW < 1) in.dropW = 1;
    sort(in.idle.begin(), in.idle.end(), [](const RobotIn& a, const RobotIn& b) { return a.id < b.id; });
    sort(in.tasks.begin(), in.tasks.end(), [](const TaskIn& a, const TaskIn& b) { return a.id < b.id; });
    return true;
}

// ---------------------------------------------------------------- one planning batch
static void planBatch(const Input& in) {
    double tStart = now_ms();
    int R = (int)in.idle.size(), T = (int)in.tasks.size(), nd = (int)in.docks.size();
    int threads = 1;
#ifdef _OPENMP
    if (in.threads > 0) omp_set_num_threads(in.threads);
    omp_set_schedule(in.sched == 0 ? omp_sched_static : (in.sched == 2 ? omp_sched_guided : omp_sched_dynamic), 0);
    threads = omp_get_max_threads();
#endif
    vector<pair<int, int> > pairs;  // (robot index, task index)
    double k1 = 0, k3 = 0, k4 = 0;
    int rounds = 0;

    if (R > 0 && T > 0 && nd > 0) {
        // ---------------- K1: distance fields -> cost matrix cost[t*R + r]
        double a = now_ms();
        vector<int> myTasks;
        for (int i = g_rank; i < T; i += g_size) myTasks.push_back(i);
        vector<int> localCost(myTasks.size() * (size_t)R, BIG);
        int nm = (int)myTasks.size();
#pragma omp parallel for schedule(runtime)
        for (int k = 0; k < nm; k++) {
            const TaskIn& t = in.tasks[myTasks[k]];
            vector<int> dist(W * H, -1), q;
            q.reserve(W * H);
            int sc = cid(t.ax, t.ay);
            dist[sc] = 0; q.push_back(sc);
            for (size_t h = 0; h < q.size(); h++) {
                int c = q[h], cx = c % W, cy = c / W;
                for (int d = 0; d < 4; d++) {
                    int nx = cx + DX[d], ny = cy + DY[d];
                    if (!inb(nx, ny) || blockedCell[cid(nx, ny)]) continue;
                    int nc = cid(nx, ny);
                    if (dist[nc] >= 0) continue;
                    dist[nc] = dist[c] + 1; q.push_back(nc);
                }
            }
            Pt dk = in.docks[t.id % nd];
            int dc = dist[cid(dk.x, dk.y)];
            for (int r = 0; r < R; r++) {
                int d = dist[cid(in.idle[r].x, in.idle[r].y)];
                localCost[(size_t)k * R + r] = (d < 0 || dc < 0) ? BIG : d + dc;
            }
        }
        vector<char> blob;
        for (int c : localCost) put(blob, c);
        vector<vector<char> > all = allgatherBytes(blob);
        vector<int> cost((size_t)T * R, BIG);
        for (int rk = 0; rk < g_size; rk++) {
            Reader rd(all[rk]);
            for (int i = rk, k = 0; i < T; i += g_size, k++)
                for (int r = 0; r < R; r++) cost[(size_t)i * R + r] = rd.get<int>();
        }
        k1 = now_ms() - a;

        // ---------------- K3: auction (bidders = smaller side)
        a = now_ms();
        bool robotsBid = R <= T;
        int nb = robotsBid ? R : T, no = robotsBid ? T : R;
        auto costBO = [&](int b, int o) -> int { return robotsBid ? cost[(size_t)o * R + b] : cost[(size_t)b * R + o]; };
        vector<long long> price(no, 0);
        vector<int> owner(no, -1), asg(nb, -1);
        struct Bid { int b, o; long long bid; };
        long long scale = nb + 1;
        while (rounds < 200000) {
            vector<int> U;
            for (int b = 0; b < nb; b++) if (asg[b] < 0) U.push_back(b);
            if (U.empty()) break;
            rounds++;
            vector<int> mine;
            for (size_t k = g_rank; k < U.size(); k += g_size) mine.push_back(U[k]);
            vector<Bid> mb(mine.size());
            int mn = (int)mine.size();
#pragma omp parallel for schedule(runtime)
            for (int k = 0; k < mn; k++) {
                int b = mine[k];
                long long v1 = LLONG_MIN, v2 = LLONG_MIN; int o1 = -1;
                for (int o = 0; o < no; o++) {
                    long long v = (long long)(BIG - costBO(b, o)) * scale - price[o];
                    if (v > v1) { v2 = v1; v1 = v; o1 = o; }
                    else if (v > v2) v2 = v;
                }
                if (v2 == LLONG_MIN) v2 = v1;
                mb[k].b = b; mb[k].o = o1; mb[k].bid = price[o1] + (v1 - v2) + 1;
            }
            vector<char> bb;
            for (const Bid& x : mb) { put(bb, x.b); put(bb, x.o); put(bb, x.bid); }
            vector<vector<char> > ab = allgatherBytes(bb);
            vector<int> bestB(no, -1); vector<long long> bestBid(no, LLONG_MIN);
            for (int rk = 0; rk < g_size; rk++) {
                Reader rd(ab[rk]);
                while (!rd.done()) {
                    int b = rd.get<int>(); int o = rd.get<int>(); long long bid = rd.get<long long>();
                    if (bid > bestBid[o] || (bid == bestBid[o] && b < bestB[o])) { bestBid[o] = bid; bestB[o] = b; }
                }
            }
            for (int o = 0; o < no; o++) if (bestB[o] >= 0) {
                if (owner[o] >= 0) asg[owner[o]] = -1;
                owner[o] = bestB[o]; asg[bestB[o]] = o; price[o] = bestBid[o];
            }
        }
        for (int b = 0; b < nb; b++) {
            int o = asg[b];
            if (o < 0) continue;
            int r = robotsBid ? b : o, t = robotsBid ? o : b;
            if (cost[(size_t)t * R + r] >= BIG) continue;
            pairs.push_back(make_pair(r, t));
        }
        sort(pairs.begin(), pairs.end());
        k3 = now_ms() - a;
    }

    // ---------------- K4: parallel unconstrained paths, then resolve conflicts on rank 0
    vector<PlanPath> plans(pairs.size());
    int np = (int)pairs.size();
    if (np > 0) {
        double a = now_ms();
        vector<int> mine;
        for (int i = g_rank; i < np; i += g_size) mine.push_back(i);
        vector<PlanPath> local(mine.size());
        int mn = (int)mine.size();
#pragma omp parallel for schedule(runtime)
        for (int k = 0; k < mn; k++) {
            const RobotIn& r = in.idle[pairs[mine[k]].first];
            const TaskIn& t = in.tasks[pairs[mine[k]].second];
            Pt cur{r.x, r.y}, acc{t.ax, t.ay}, dk = in.docks[t.id % nd], home{r.hx, r.hy};
            PlanPath pp; vector<Pt> seg; bool ok = true;
            ok = astarStatic(cur, acc, seg);
            if (ok) { pp.path.insert(pp.path.end(), seg.begin(), seg.end());
                      for (int w = 0; w < in.pickW; w++) pp.path.push_back(acc);
                      pp.pickT = (int)pp.path.size();
                      ok = astarStatic(acc, dk, seg); }
            if (ok) { pp.path.insert(pp.path.end(), seg.begin(), seg.end());
                      for (int w = 0; w < in.dropW; w++) pp.path.push_back(dk);
                      pp.dropT = (int)pp.path.size();
                      ok = astarStatic(dk, home, seg); }
            if (ok) pp.path.insert(pp.path.end(), seg.begin(), seg.end());
            pp.ok = ok;
            local[k] = pp;
        }
        vector<char> blob;
        for (int k = 0; k < mn; k++) {
            const PlanPath& p = local[k];
            put(blob, mine[k]); put(blob, (int)p.ok); put(blob, p.pickT); put(blob, p.dropT); put(blob, (int)p.path.size());
            for (const Pt& q : p.path) { put(blob, q.x); put(blob, q.y); }
        }
        vector<vector<char> > all = allgatherBytes(blob);
        for (int rk = 0; rk < g_size; rk++) {
            Reader rd(all[rk]);
            while (!rd.done()) {
                int i = rd.get<int>(); PlanPath p;
                p.ok = rd.get<int>() != 0; p.pickT = rd.get<int>(); p.dropT = rd.get<int>();
                int n = rd.get<int>();
                for (int j = 0; j < n; j++) { Pt q; q.x = rd.get<int>(); q.y = rd.get<int>(); p.path.push_back(q); }
                plans[i] = p;
            }
        }
        if (g_rank == 0) {
            Resv rv;
            vector<char> isAssigned(R, 0);
            for (int i = 0; i < np; i++) isAssigned[pairs[i].first] = 1;
            for (int r = 0; r < R; r++)
                if (!isAssigned[r] && in.idle[r].x == in.idle[r].hx && in.idle[r].y == in.idle[r].hy)
                    rv.perm[cid(in.idle[r].x, in.idle[r].y)] = 0;
            for (const BusyIn& b : in.busy) {
                vector<Pt> rest(b.p.begin() + 1, b.p.end());
                rv.addPath(b.p[0], rest);
            }
            vector<int> redo;
            for (int i = 0; i < np; i++) {
                const RobotIn& r = in.idle[pairs[i].first];
                Pt s{r.x, r.y};
                if (plans[i].ok && rv.pathFree(s, plans[i].path)) rv.addPath(s, plans[i].path);
                else redo.push_back(i);
            }
            for (int i : redo) {
                const RobotIn& r = in.idle[pairs[i].first];
                const TaskIn& t = in.tasks[pairs[i].second];
                Pt s{r.x, r.y}, acc{t.ax, t.ay}, dk = in.docks[t.id % nd], home{r.hx, r.hy};
                PlanPath pp; vector<Pt> seg; int te = 0, tc = 0; bool ok;
                ok = stLeg(rv, s, tc, acc, in.pickW, false, seg, te);
                if (ok) { pp.path.insert(pp.path.end(), seg.begin(), seg.end()); tc = te;
                          for (int w = 0; w < in.pickW; w++) pp.path.push_back(acc);
                          tc += in.pickW; pp.pickT = (int)pp.path.size();
                          ok = stLeg(rv, acc, tc, dk, in.dropW, false, seg, te); }
                if (ok) { pp.path.insert(pp.path.end(), seg.begin(), seg.end()); tc = te;
                          for (int w = 0; w < in.dropW; w++) pp.path.push_back(dk);
                          tc += in.dropW; pp.dropT = (int)pp.path.size();
                          ok = stLeg(rv, dk, tc, home, 0, true, seg, te); }
                if (ok) pp.path.insert(pp.path.end(), seg.begin(), seg.end());
                pp.ok = ok;
                plans[i] = pp;
                if (ok) rv.addPath(s, pp.path);
            }
        }
        k4 = now_ms() - a;
    }

    if (g_rank == 0) {
        int cnt = 0;
        for (int i = 0; i < np; i++) if (plans[i].ok) cnt++;
        printf("TIMING %.3f %.3f %.3f %.3f %d %d %d\n", k1, k3, k4, now_ms() - tStart, g_size, threads, rounds);
        printf("ASSIGN %d\n", cnt);
        for (int i = 0; i < np; i++) {
            if (!plans[i].ok) continue;
            const RobotIn& r = in.idle[pairs[i].first];
            const TaskIn& t = in.tasks[pairs[i].second];
            printf("%d %d %d %d %d", r.id, t.id, plans[i].pickT, plans[i].dropT, (int)plans[i].path.size());
            for (const Pt& q : plans[i].path) printf(" %d %d", q.x, q.y);
            printf("\n");
        }
        printf("END\n");
        fflush(stdout);
    }
}

int main(int argc, char** argv) {
#ifdef USE_MPI
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &g_rank);
    MPI_Comm_size(MPI_COMM_WORLD, &g_size);
#endif
    if (g_rank == 0) {
        int th = 1;
#ifdef _OPENMP
        th = omp_get_max_threads();
#endif
        printf("READY %d %d\n", g_size, th);
        fflush(stdout);
    }
    while (true) {
        vector<char> buf;
        if (g_rank == 0) {
            string text, line;
            bool got = false;
            while (getline(cin, line)) {
                text += line; text += '\n';
                if (line == "GO" || line == "QUIT") { got = true; break; }
            }
            if (!got) text = "QUIT\n";
            buf.assign(text.begin(), text.end());
        }
#ifdef USE_MPI
        int n = (int)buf.size();
        MPI_Bcast(&n, 1, MPI_INT, 0, MPI_COMM_WORLD);
        if (g_rank != 0) buf.resize(n);
        MPI_Bcast(buf.data(), n, MPI_CHAR, 0, MPI_COMM_WORLD);
#endif
        string text(buf.begin(), buf.end());
        Input in; bool quit = false;
        parseInput(text, in, quit);
        if (quit) break;
        planBatch(in);
    }
#ifdef USE_MPI
    MPI_Finalize();
#endif
    return 0;
}
