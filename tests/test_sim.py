"""Headless end-to-end test: random request bursts on each available engine, collision + stock invariants."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from warehouse import Warehouse
from engine_client import start_engine, PyEngine, ProcessEngine, ENGINE_DIR


def run(engine, shelves=24, robots=6, nreq=25, max_ticks=3000, seed=1):
    wh = Warehouse(shelves, robots, seed=seed)
    start_stock = {p: wh.total_stock(p) for p in range(len(wh.products))}
    rng = wh.rng
    rejected = 0
    for _ in range(nreq):
        pid = rng.randrange(len(wh.products))
        req = wh.submit_request(pid, rng.randint(1, 15))
        rejected += req.status == "REJECTED"
    for _ in range(max_ticks):
        wh.plan(engine, {"pick": 2, "drop": 2, "threads": 0})
        wh.step()
        wh.check_invariants()
        if not wh.pending and wh.busy_count() == 0:
            break
    done = [r for r in wh.requests if r.status == "COMPLETED"]
    delivered = {p: 0 for p in start_stock}
    for r in wh.requests:
        delivered[r.product] += r.delivered
    for p in start_stock:
        assert wh.total_stock(p) == start_stock[p] - delivered[p], "stock mismatch for product %d" % p
        assert wh.total_available(p) == wh.total_stock(p), "leftover reservations"
    assert all(r.status in ("COMPLETED", "REJECTED") for r in wh.requests), [(r.id, r.status) for r in wh.requests if r.status not in ("COMPLETED", "REJECTED")]
    return wh.tick, len(done), rejected


if __name__ == "__main__":
    engines = [("python", PyEngine())]
    for name in ("engine_serial.exe", "engine_omp.exe", "engine_mpi.exe"):
        p = os.path.join(ENGINE_DIR, name)
        if os.path.exists(p) and name != "engine_mpi.exe":
            engines.append((name, ProcessEngine([p], name)))
    for name, eng in engines:
        for (s, r, n) in ((24, 6, 25), (48, 20, 60)):
            t0 = time.time()
            ticks, done, rej = run(eng, s, r, n)
            print("%-18s shelves=%2d robots=%2d  ticks=%4d completed=%2d rejected=%2d  (%.1fs)  OK" % (name, s, r, ticks, done, rej, time.time() - t0))
        eng.close()
