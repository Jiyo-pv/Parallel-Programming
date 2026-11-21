"""SQLite persistence for warehouse state, requests, trips, and parallel engine timing metrics."""
import os
import sqlite3
import time


def default_db_path():
    local_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "WarehouseSim") if os.environ.get("APPDATA") else None,
        local_dir,
    ]
    for folder in candidates:
        if not folder:
            continue
        try:
            os.makedirs(folder, exist_ok=True)
            test_path = os.path.join(folder, ".write_test")
            with open(test_path, "w") as f:
                f.write("ok")
            os.remove(test_path)
            return os.path.join(folder, "warehouse.db")
        except OSError:
            continue
    return ":memory:"


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    r INTEGER, g INTEGER, b INTEGER
);
CREATE TABLE IF NOT EXISTS shelves (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    x INTEGER, y INTEGER,
    access_x INTEGER, access_y INTEGER,
    capacity INTEGER,
    product_id INTEGER,
    stock INTEGER,
    reserved INTEGER
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_req_id INTEGER,
    run_id INTEGER,
    product_name TEXT,
    quantity INTEGER,
    status TEXT,
    delivered INTEGER,
    note TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine_label TEXT,
    ranks INTEGER,
    threads INTEGER,
    n_shelves INTEGER,
    n_robots INTEGER,
    started_at REAL
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    tick INTEGER,
    k1_ms REAL,
    k3_ms REAL,
    k4_ms REAL,
    total_ms REAL,
    ranks INTEGER,
    threads INTEGER,
    rounds INTEGER
);
"""


class WarehouseDB:
    def __init__(self, path=None):
        self.path = path or default_db_path()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.run_id = None

    def start_run(self, engine_label, ranks, threads, n_shelves, n_robots):
        cur = self.conn.execute(
            "INSERT INTO runs(engine_label, ranks, threads, n_shelves, n_robots, started_at) VALUES (?,?,?,?,?,?)",
            (engine_label, ranks, threads, n_shelves, n_robots, time.time()),
        )
        self.conn.commit()
        self.run_id = cur.lastrowid
        return self.run_id

    def sync_inventory(self, wh):
        with self.conn:
            self.conn.execute("DELETE FROM products")
            self.conn.executemany(
                "INSERT INTO products(id, name, r, g, b) VALUES (?,?,?,?,?)",
                [(i, name, col[0], col[1], col[2]) for i, (name, col) in enumerate(wh.products)],
            )
            self.conn.execute("DELETE FROM shelves")
            self.conn.executemany(
                "INSERT INTO shelves(id, label, x, y, access_x, access_y, capacity, product_id, stock, reserved) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(s.id, s.label, s.x, s.y, s.ax, s.ay, s.capacity, s.product, s.stock, s.reserved) for s in wh.shelves],
            )

    def log_request(self, req, product_name):
        with self.conn:
            self.conn.execute(
                "INSERT INTO requests(sim_req_id, run_id, product_name, quantity, status, delivered, note, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (req.id, self.run_id, product_name, req.qty, req.status, req.delivered, req.note, time.time()),
            )

    def update_request(self, req):
        if self.run_id is None:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE requests SET status=?, delivered=? WHERE run_id=? AND sim_req_id=?",
                (req.status, req.delivered, self.run_id, req.id),
            )

    def log_timing(self, tick, timing):
        if not timing or self.run_id is None:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO metrics(run_id, tick, k1_ms, k3_ms, k4_ms, total_ms, ranks, threads, rounds) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (self.run_id, tick, timing["k1"], timing["k3"], timing["k4"], timing["total"],
                 timing["ranks"], timing["threads"], timing["rounds"]),
            )

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
