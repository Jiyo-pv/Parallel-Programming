"""Headless benchmark runner: measures K1, K3, K4 & total planning times, speedup, and efficiency."""
import csv
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from engine_client import ENGINE_DIR, ProcessEngine, PyEngine, find_mpiexec
from warehouse import make_layout


def make_batch(n_shelves, n_robots, n_tasks, threads=0, sched=1):
    layout = make_layout(n_shelves, n_robots)
    idle = [(i, h[0], h[1], h[0], h[1]) for i, h in enumerate(layout["homes"])]
    tasks = []
    for t in range(n_tasks):
        sx, sy = layout["shelf_pos"][t % n_shelves]
        tasks.append((t + 1, sx, sy + 1))
    return {
        "grid": layout["grid"],
        "docks": layout["docks"],
        "idle": idle,
        "busy": [],
        "tasks": tasks,
        "cfg": {"pick": 2, "drop": 2, "threads": threads, "sched": sched},
    }


def bench_one(engine, batch, runs=3):
    k1s, k3s, k4s, tots = [], [], [], []
    last = None
    for _ in range(runs):
        res = engine.plan(batch)
        t = res["timing"]
        k1s.append(t["k1"])
        k3s.append(t["k3"])
        k4s.append(t["k4"])
        tots.append(t["total"])
        last = t
    return {
        "k1_ms": statistics.median(k1s),
        "k3_ms": statistics.median(k3s),
        "k4_ms": statistics.median(k4s),
        "total_ms": statistics.median(tots),
        "ranks": last["ranks"],
        "threads": last["threads"],
    }


def main():
    scenarios = [
        ("small", 24, 8, 24),
        ("medium", 96, 40, 80),
        ("large", 192, 80, 160),
    ]

    configs = []
    ser = os.path.join(ENGINE_DIR, "engine_serial.exe")
    omp = os.path.join(ENGINE_DIR, "engine_omp.exe")
    mpi = os.path.join(ENGINE_DIR, "engine_mpi.exe")
    mpiexec = find_mpiexec()

    if os.path.exists(ser):
        configs.append(("serial", lambda th: ProcessEngine([ser], "serial"), 1, 1))
    else:
        configs.append(("python_serial", lambda th: PyEngine(), 1, 1))

    cores = os.cpu_count() or 4
    thread_list = sorted({t for t in (1, 2, 4, cores) if t <= cores})
    if os.path.exists(omp):
        for th in thread_list:
            configs.append((f"omp_{th}t", lambda t=th: ProcessEngine([omp], f"omp_{t}t"), 1, th))

    if os.path.exists(mpi) and mpiexec:
        for rk in (1, 2, 4):
            if rk <= cores:
                th = max(1, cores // rk)
                configs.append((f"mpi_{rk}r_{th}t", lambda r=rk, t=th: ProcessEngine(
                    [mpiexec, "-n", str(r), "-env", "OMP_NUM_THREADS", str(t), mpi], f"mpi_{r}r_{t}t"
                ), rk, th))

    out_csv = os.path.join(ROOT, "bench", "results.csv")
    rows = []
    for sname, ns, nr, nt in scenarios:
        base_ms = None
        print(f"\n=== Scenario: {sname} (shelves={ns}, robots={nr}, tasks={nt}) ===")
        for cname, factory, rk, th in configs:
            eng = factory(th)
            batch = make_batch(ns, nr, nt, threads=th)
            m = bench_one(eng, batch, runs=3)
            eng.close()
            if base_ms is None:
                base_ms = m["total_ms"]
            speedup = base_ms / max(1e-6, m["total_ms"])
            workers = max(1, rk * th)
            eff = speedup / workers
            print(f"  {cname:14s}  K1={m['k1_ms']:6.2f}ms  K3={m['k3_ms']:6.2f}ms  K4={m['k4_ms']:6.2f}ms  "
                  f"Total={m['total_ms']:7.2f}ms  Speedup={speedup:5.2f}x  Eff={eff*100:5.1f}%")
            rows.append({
                "scenario": sname, "shelves": ns, "robots": nr, "tasks": nt,
                "config": cname, "ranks": rk, "threads": th,
                "k1_ms": f"{m['k1_ms']:.3f}", "k3_ms": f"{m['k3_ms']:.3f}",
                "k4_ms": f"{m['k4_ms']:.3f}", "total_ms": f"{m['total_ms']:.3f}",
                "speedup": f"{speedup:.3f}", "efficiency": f"{eff:.3f}",
            })

    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved benchmark results to {out_csv}")


if __name__ == "__main__":
    main()
