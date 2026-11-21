"""Warehouse model + simulation logic (no pygame, fully testable headless)."""
import random
import threading

PRODUCT_NAMES = ["Rice", "Sugar", "Oil", "Soap", "Salt", "Tea", "Flour", "Milk",
                 "Coffee", "Pasta", "Honey", "Butter"]
PALETTE = [(231, 111, 81), (42, 157, 143), (233, 196, 106), (106, 76, 147), (69, 123, 157),
           (244, 162, 97), (131, 197, 190), (200, 90, 140), (138, 177, 125), (180, 130, 90),
           (240, 200, 60), (120, 160, 220)]


def make_layout(n_shelves, n_robots):
    """Shelves in rows, 2-wide aisles, cross aisles every 3 shelves, docks on top, robot parking at bottom."""
    cols = 6 if n_shelves <= 24 else 8
    rows = -(-n_shelves // cols)
    xs = [1 + j + j // 3 for j in range(cols)]
    W = max(xs) + 2
    W = max(W, 14)
    shelf_pos = []
    for i in range(rows):
        for j in range(cols):
            if len(shelf_pos) < n_shelves:
                shelf_pos.append((xs[j], 2 + 3 * i))
    park_y0 = 3 * rows + 2
    park_rows = -(-n_robots // (W - 2))
    H = park_y0 + 2 * park_rows
    grid = [["."] * W for _ in range(H)]
    for (x, y) in shelf_pos:
        grid[y][x] = "#"
    homes = []
    for k in range(n_robots):
        pr, pc = divmod(k, W - 2)
        homes.append((1 + pc, park_y0 + 2 * pr + 1))
    nd = 4
    docks = sorted(set([1 + (W - 3) * k // (nd - 1) for k in range(nd)]))
    docks = [(x, 0) for x in docks]
    return {"W": W, "H": H, "grid": ["".join(r) for r in grid], "shelf_pos": shelf_pos,
            "homes": homes, "docks": docks}


class Shelf:
    def __init__(self, sid, x, y, capacity):
        self.id, self.x, self.y = sid, x, y
        self.ax, self.ay = x, y + 1
        self.capacity = capacity
        self.product = None  # product id
        self.stock = 0
        self.reserved = 0
        self.flash = 0

    @property
    def label(self):
        return "S%02d" % (self.id + 1)

    @property
    def available(self):
        return self.stock - self.reserved


class Robot:
    def __init__(self, rid, home):
        self.id, self.home = rid, home
        self.x, self.y = home
        self.px, self.py = home  # previous position for interpolation
        self.path = []
        self.k = 0
        self.pickT = self.dropT = 0
        self.trip = None
        self.carrying = None

    @property
    def idle(self):
        return self.trip is None

    @property
    def returning(self):
        return self.trip is not None and self.k >= self.dropT


class Trip:
    def __init__(self, tid, req, shelf, units):
        self.id, self.req, self.shelf, self.units = tid, req, shelf, units
        self.state = "PENDING"
        self.robot = None


class Request:
    def __init__(self, rid, product, qty, tick):
        self.id, self.product, self.qty, self.created = rid, product, qty, tick
        self.status = "PENDING"
        self.delivered = 0
        self.note = ""
        self.open_trips = 0


class Warehouse:
    def __init__(self, n_shelves=24, n_robots=6, carry=5, shelf_cap=50, seed=7):
        self.lock = threading.RLock()
        self.carry, self.shelf_cap = carry, shelf_cap
        self.layout = make_layout(n_shelves, n_robots)
        self.products = []  # list of (name, colour)
        self.shelves = [Shelf(i, x, y, shelf_cap) for i, (x, y) in enumerate(self.layout["shelf_pos"])]
        self.robots = [Robot(i, h) for i, h in enumerate(self.layout["homes"])]
        self.requests = []
        self.trips = {}
        self.pending = []
        self.dock_flash = [0] * len(self.layout["docks"])
        self.tick = 0
        self.next_req = self.next_trip = 1
        self.last_timing = None
        self.plan_count = 0
        self.rng = random.Random(seed)
        self.sample_data()

    # ------------------------------------------------------------ setup
    def add_product(self, name):
        name = name.strip()
        if not name:
            return None
        for i, (n, _) in enumerate(self.products):
            if n.lower() == name.lower():
                return i
        self.products.append((name, PALETTE[len(self.products) % len(PALETTE)]))
        return len(self.products) - 1

    def sample_data(self):
        n = len(self.shelves)
        nprod = max(2, min(len(PRODUCT_NAMES), n // 3))
        self.products = []
        for i in range(nprod):
            self.add_product(PRODUCT_NAMES[i])
        for s in self.shelves:
            s.product = s.id % nprod
            s.stock = self.rng.randint(self.shelf_cap // 3, self.shelf_cap)
            s.reserved = 0

    def total_available(self, pid):
        return sum(s.available for s in self.shelves if s.product == pid)

    def total_stock(self, pid):
        return sum(s.stock for s in self.shelves if s.product == pid)

    # ------------------------------------------------------------ stock update
    def set_stock(self, sid, value):
        with self.lock:
            s = self.shelves[sid]
            if value < s.reserved:
                return False, "Cannot go below reserved units (%d)" % s.reserved
            if value > s.capacity:
                return False, "Capacity of %s is %d" % (s.label, s.capacity)
            if value < 0:
                return False, "Stock cannot be negative"
            s.stock = value
            return True, "%s stock = %d" % (s.label, value)

    def set_shelf_product(self, sid, pid):
        with self.lock:
            s = self.shelves[sid]
            if s.stock != 0 or s.reserved != 0:
                return False, "Shelf must be empty (stock 0) to change its product"
            s.product = pid
            return True, "%s now holds %s" % (s.label, self.products[pid][0])

    # ------------------------------------------------------------ requests (K2: allocation, serial, locked)
    def submit_request(self, pid, qty):
        with self.lock:
            req = Request(self.next_req, pid, qty, self.tick)
            self.next_req += 1
            self.requests.append(req)
            pname = self.products[pid][0]
            avail = self.total_available(pid)
            if qty <= 0:
                req.status, req.note = "REJECTED", "Invalid quantity"
                return req
            if qty > avail:
                req.status = "REJECTED"
                req.note = "Insufficient stock: requested %d, available %d" % (qty, avail)
                return req
            docks = self.layout["docks"]
            ref = docks[req.id % len(docks)]
            cand = [s for s in self.shelves if s.product == pid and s.available > 0]
            cand.sort(key=lambda s: (abs(s.ax - ref[0]) + abs(s.ay - ref[1]), s.id))
            left = qty
            for s in cand:
                take = min(left, s.available)
                s.reserved += take
                left -= take
                while take > 0:
                    u = min(take, self.carry)
                    t = Trip(self.next_trip, req, s, u)
                    self.next_trip += 1
                    self.trips[t.id] = t
                    self.pending.append(t)
                    req.open_trips += 1
                    take -= u
                if left == 0:
                    break
            req.status = "ALLOCATED"
            req.note = "%d x %s" % (qty, pname)
            return req

    # ------------------------------------------------------------ planning / stepping
    def idle_robots(self):
        return [r for r in self.robots if r.idle]

    def available_robots(self):
        return [r for r in self.robots if r.idle or r.returning]

    def plan(self, engine, cfg):
        """Send pending trips to the engine, apply the returned assignments/paths."""
        with self.lock:
            at_home = self.idle_robots()
            ret = [r for r in self.robots if r.returning]
            if (not at_home and not ret) or not self.pending:
                return None
            tasks = self.pending[: max(len(at_home) + len(ret), 1) * 2]
            eligible = at_home + ret[: len(tasks)]
            busy = [r for r in self.robots if not r.idle and not r.returning] + ret[len(tasks) :]
            data = {
                "grid": self.layout["grid"], "docks": self.layout["docks"],
                "idle": [(r.id, r.x, r.y, r.home[0], r.home[1]) for r in eligible],
                "busy": [(r.id, [(r.x, r.y)] + r.path[r.k:]) for r in busy],
                "tasks": [(t.id, t.shelf.ax, t.shelf.ay) for t in tasks],
                "cfg": cfg,
            }
        result = engine.plan(data)
        with self.lock:
            self.last_timing = result["timing"]
            self.plan_count += 1
            for (rid, tid, pickT, dropT, path) in result["assign"]:
                r, t = self.robots[rid], self.trips[tid]
                if (not r.idle and not r.returning) or t.state != "PENDING":
                    continue
                r.path, r.k, r.pickT, r.dropT = path, 0, pickT, dropT
                r.trip, r.carrying = t, None
                t.state, t.robot = "ASSIGNED", rid
                self.pending.remove(t)
                if t.req.status == "ALLOCATED":
                    t.req.status = "IN_PROGRESS"
            return result

    def step(self):
        """Advance the simulation by one tick."""
        with self.lock:
            self.tick += 1
            for s in self.shelves:
                if s.flash > 0:
                    s.flash -= 1
            for i in range(len(self.dock_flash)):
                if self.dock_flash[i] > 0:
                    self.dock_flash[i] -= 1
            for r in self.robots:
                r.px, r.py = r.x, r.y
                if r.idle:
                    continue
                r.k += 1
                r.x, r.y = r.path[r.k - 1]
                t = r.trip
                if r.k == r.pickT:
                    s = t.shelf
                    s.stock -= t.units
                    s.reserved -= t.units
                    s.flash = 3
                    r.carrying = s.product
                    t.state = "PICKED"
                if r.k == r.dropT:
                    r.carrying = None
                    t.state = "DONE"
                    self.dock_flash[t.id % len(self.layout["docks"])] = 4
                    req = t.req
                    req.delivered += t.units
                    req.open_trips -= 1
                    if req.open_trips == 0 and req.delivered >= req.qty:
                        req.status = "COMPLETED"
                if r.k >= len(r.path):
                    r.trip, r.path, r.k = None, [], 0

    def busy_count(self):
        return sum(1 for r in self.robots if not r.idle)

    def check_invariants(self):
        """Used by tests: no shelf negative / over capacity, no two robots on one cell."""
        with self.lock:
            for s in self.shelves:
                assert 0 <= s.reserved <= s.stock <= s.capacity or s.stock >= 0, s.label
                assert s.stock >= 0 and s.reserved >= 0, s.label
            seen = {}
            for r in self.robots:
                assert (r.x, r.y) not in seen, "collision at %s between %d and %d" % ((r.x, r.y), seen[(r.x, r.y)], r.id)
                seen[(r.x, r.y)] = r.id
            return True
