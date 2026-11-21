"""Parallel Warehouse Management & Multi-Robot Retrieval - Pygame application."""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pygame

import cluster
from db import WarehouseDB
from engine_client import start_engine
from warehouse import Warehouse

SW, SH = 1320, 800
PANEL_W = 376
PANEL_X = SW - PANEL_W - 14

# Modern dark-slate palette
BG = (15, 20, 30)
CARD = (24, 31, 46)
CARD_ALT = (30, 39, 58)
BORDER = (52, 65, 92)
TXT = (236, 241, 250)
DIM = (144, 158, 184)
ACC = (56, 168, 255)
OK = (52, 211, 153)
BAD = (248, 113, 113)
WARN = (251, 191, 36)
FLOOR = (22, 28, 42)
AISLE = (33, 42, 61)
DOCK_BG = (16, 78, 60)
DOCK_BD = (52, 211, 153)

pygame.init()
pygame.display.set_caption("Parallel Warehouse — Multi-Robot Retrieval (MPI + OpenMP)")
screen = pygame.display.set_mode((SW, SH))
clock = pygame.time.Clock()


def font(size, bold=False):
    return pygame.font.SysFont("segoeui,arial,helvetica", size, bold=bold)


F10 = font(10, True)
F11 = font(11)
F12 = font(12)
F12B = font(12, True)
F14 = font(14)
F14B = font(14, True)
F16 = font(16, True)
F20 = font(20, True)
F28 = font(28, True)


def draw_text(surf, text, f, color, pos, center=False, right=False):
    img = f.render(str(text), True, color)
    r = img.get_rect()
    if center:
        r.center = pos
    elif right:
        r.topright = pos
    else:
        r.topleft = pos
    surf.blit(img, r)
    return r


def draw_card(rect, title=None, bg=CARD, border=BORDER):
    r = pygame.Rect(rect)
    pygame.draw.rect(screen, bg, r, border_radius=10)
    pygame.draw.rect(screen, border, r, 1, border_radius=10)
    if title:
        draw_text(screen, title, F12B, ACC, (r.x + 14, r.y + 10))
        pygame.draw.line(screen, BORDER, (r.x + 14, r.y + 30), (r.right - 14, r.y + 30), 1)
    return r


def shade(col, f):
    return tuple(max(0, min(255, int(v * f))) for v in col)


def draw_robot_sprite(x, y, sz, idle, fdx, fdy, carry_col, label):
    """Draw a detailed AGV warehouse robot (treads, metallic body, antenna/LED, visor, carried crate)."""
    ix, iy = int(x), int(y)
    w = max(14, int(sz * 0.78))
    h = max(12, int(sz * 0.66))
    # Ground shadow
    pygame.draw.ellipse(screen, (8, 10, 16), (ix - w // 2 - 2, iy + h // 4, w + 4, h // 2 + 4))
    # Wheels / treads
    tw, th = max(4, w // 4), max(4, h // 3)
    for wx in (-w // 2 - 1, w // 2 - tw + 1):
        for wy in (-h // 2 + 1, h // 2 - th - 1):
            pygame.draw.rect(screen, (18, 22, 30), (ix + wx, iy + wy, tw, th), border_radius=2)
    # Main metallic chassis
    body = pygame.Rect(ix - w // 2, iy - h // 2, w, h)
    trim = (56, 189, 248) if idle else (251, 146, 60)
    pygame.draw.rect(screen, (42, 54, 78), body, border_radius=5)
    pygame.draw.rect(screen, trim, body, 2, border_radius=5)
    # Top deck plate
    deck = body.inflate(-6, -6)
    pygame.draw.rect(screen, (62, 78, 108), deck, border_radius=3)
    # Directional visor / sensor eyes facing movement direction
    vx = ix + int(fdx * (w * 0.34))
    vy = iy + int(fdy * (h * 0.34))
    if fdx == 0 and fdy == 0:
        vy = iy - int(h * 0.32)
    visor_col = (125, 211, 252) if idle else (253, 224, 71)
    if abs(fdx) >= abs(fdy) and fdx != 0:
        pygame.draw.rect(screen, visor_col, (vx - 2, vy - 4, 4, 8), border_radius=2)
    else:
        pygame.draw.rect(screen, visor_col, (vx - 4, vy - 2, 8, 4), border_radius=2)
    # Antenna + glowing status LED
    pygame.draw.line(screen, (180, 195, 220), (ix + w // 3, iy - h // 2), (ix + w // 3, iy - h // 2 - 5), 1)
    pygame.draw.circle(screen, (52, 211, 153) if not idle else (56, 189, 248), (ix + w // 3, iy - h // 2 - 6), 2)
    # Robot ID or carried 3D crate
    if carry_col is not None:
        cw = max(8, w // 2)
        cr = pygame.Rect(ix - cw // 2, iy - cw // 2 - 3, cw, cw - 1)
        pygame.draw.rect(screen, shade(carry_col, 0.72), (cr.x, cr.y + 3, cr.w, cr.h), border_radius=2)
        pygame.draw.rect(screen, carry_col, cr, border_radius=2)
        pygame.draw.rect(screen, (255, 255, 255), cr, 1, border_radius=2)
        draw_text(screen, label, F10, (15, 20, 30) if sum(carry_col) > 380 else (255, 255, 255), cr.center, center=True)
    else:
        draw_text(screen, label, F10, (235, 242, 255), (ix, iy), center=True)


# ------------------------------------------------------------------------------------------------ widgets
class Button:
    def __init__(self, rect, text, cb, color=ACC):
        self.rect, self.text, self.cb, self.color, self.enabled = pygame.Rect(rect), text, cb, color, True

    def draw(self):
        hover = self.rect.collidepoint(pygame.mouse.get_pos()) and self.enabled
        c = self.color if self.enabled else (62, 68, 84)
        if hover:
            c = tuple(min(255, v + 22) for v in c)
        pygame.draw.rect(screen, c, self.rect, border_radius=7)
        pygame.draw.rect(screen, tuple(min(255, v + 35) for v in c), self.rect, 1, border_radius=7)
        tc = (15, 20, 30) if sum(c) > 460 else (255, 255, 255)
        draw_text(screen, self.text, F12B, tc, self.rect.center, center=True)

    def event(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.enabled and self.rect.collidepoint(e.pos):
            self.cb()
            return True
        return False


class Stepper:
    def __init__(self, pos, label, value, lo, hi, step=1, w=400):
        self.x, self.y, self.label, self.value, self.lo, self.hi, self.step, self.w = pos[0], pos[1], label, value, lo, hi, step, w
        self.minus = Button((self.x + w - 116, self.y, 32, 30), "-", self.dec, (58, 70, 96))
        self.plus = Button((self.x + w - 32, self.y, 32, 30), "+", self.inc, (58, 70, 96))

    def dec(self):
        self.value = max(self.lo, self.value - self.step)

    def inc(self):
        self.value = min(self.hi, self.value + self.step)

    def draw(self):
        draw_text(screen, self.label, F14, TXT, (self.x, self.y + 6))
        self.minus.draw()
        self.plus.draw()
        val_r = pygame.Rect(self.x + self.w - 80, self.y, 44, 30)
        pygame.draw.rect(screen, BG, val_r, border_radius=6)
        pygame.draw.rect(screen, BORDER, val_r, 1, border_radius=6)
        draw_text(screen, self.value, F14B, TXT, val_r.center, center=True)

    def event(self, e):
        return self.minus.event(e) or self.plus.event(e)


class TextBox:
    def __init__(self, rect, text="", numeric=False, placeholder=""):
        self.rect, self.text, self.numeric, self.active, self.placeholder = pygame.Rect(rect), text, numeric, False, placeholder

    def draw(self):
        pygame.draw.rect(screen, BG, self.rect, border_radius=6)
        pygame.draw.rect(screen, ACC if self.active else BORDER, self.rect, 2 if self.active else 1, border_radius=6)
        if self.text:
            draw_text(screen, self.text, F14, TXT, (self.rect.x + 10, self.rect.y + 6))
        else:
            draw_text(screen, self.placeholder, F12, DIM, (self.rect.x + 10, self.rect.y + 8))
        if self.active and int(time.time() * 2) % 2 == 0:
            w = F14.size(self.text)[0]
            pygame.draw.line(screen, ACC, (self.rect.x + 11 + w, self.rect.y + 6), (self.rect.x + 11 + w, self.rect.bottom - 6), 2)

    def event(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.active = self.rect.collidepoint(e.pos)
            return self.active
        if e.type == pygame.KEYDOWN and self.active:
            if e.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif e.unicode and e.unicode.isprintable() and len(self.text) < 24:
                if not self.numeric or e.unicode.isdigit():
                    self.text += e.unicode
            return True
        return False

    def int_value(self, default=0):
        try:
            return int(self.text)
        except ValueError:
            return default


class Dropdown:
    def __init__(self, rect, options_fn):
        self.rect, self.options_fn, self.sel, self.open = pygame.Rect(rect), options_fn, 0, False

    def options(self):
        return self.options_fn()

    @property
    def value(self):
        opts = self.options()
        if not opts:
            return None
        self.sel = min(self.sel, len(opts) - 1)
        return opts[self.sel][1]

    def select_value(self, v):
        for i, (_, val) in enumerate(self.options()):
            if val == v:
                self.sel = i

    def draw(self):
        opts = self.options()
        pygame.draw.rect(screen, BG, self.rect, border_radius=6)
        pygame.draw.rect(screen, ACC if self.open else BORDER, self.rect, 2 if self.open else 1, border_radius=6)
        if opts:
            self.sel = min(self.sel, len(opts) - 1)
            draw_text(screen, opts[self.sel][0], F14, TXT, (self.rect.x + 10, self.rect.y + 6))
        pygame.draw.polygon(screen, DIM, [(self.rect.right - 20, self.rect.y + 12), (self.rect.right - 10, self.rect.y + 12),
                                          (self.rect.right - 15, self.rect.y + 19)])

    def draw_list(self):
        if not self.open:
            return
        opts = self.options()
        vis = min(len(opts), 10)
        r = pygame.Rect(self.rect.x, self.rect.bottom + 3, self.rect.w, vis * 28)
        pygame.draw.rect(screen, CARD_ALT, r, border_radius=6)
        pygame.draw.rect(screen, ACC, r, 1, border_radius=6)
        mx, my = pygame.mouse.get_pos()
        for i in range(vis):
            ir = pygame.Rect(r.x + 2, r.y + i * 28 + 1, r.w - 4, 26)
            if ir.collidepoint(mx, my):
                pygame.draw.rect(screen, (52, 76, 118), ir, border_radius=4)
            draw_text(screen, opts[i][0], F14, TXT, (ir.x + 8, ir.y + 4))

    def event(self, e):
        if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
            return False
        if self.open:
            opts = self.options()
            vis = min(len(opts), 10)
            for i in range(vis):
                if pygame.Rect(self.rect.x, self.rect.bottom + 3 + i * 28, self.rect.w, 28).collidepoint(e.pos):
                    self.sel = i
                    self.open = False
                    return True
            self.open = False
            return self.rect.collidepoint(e.pos)
        if self.rect.collidepoint(e.pos):
            self.open = True
            return True
        return False


# ------------------------------------------------------------------------------------------------ application
class App:
    def __init__(self):
        self.scene = "setup"
        self.cores = cluster.logical_cores()
        self.agent = cluster.Agent()
        self.agent.start()
        self.nodes, self.node_on = [], {}
        self.mode = "single"
        self.show_advanced = False
        self.engine = None
        self.wh = None
        self.db = WarehouseDB()
        self.msg, self.msg_color = "", TXT
        self.build_setup()

    # ---------------------------------------------------------------- setup scene
    def build_setup(self):
        x = 56
        self.st_shelves = Stepper((x, 160), "Number of shelves", 24, 6, 96, 6, 420)
        self.st_robots = Stepper((x, 206), "Number of robots", 6, 1, 50, 1, 420)
        self.st_carry = Stepper((x, 252), "Robot carry capacity (units/trip)", 5, 1, 20, 1, 420)
        self.st_cap = Stepper((x, 298), "Shelf capacity (units)", 50, 10, 200, 10, 420)
        self.preset_btns = [Button((x + 434 + i * 58, 160, 50, 30), str(n), (lambda n=n: setattr(self.st_shelves, "value", n)), (58, 70, 96))
                            for i, n in enumerate((12, 24, 48))]
        self.btn_single = Button((x, 412, 160, 34), "Single PC", lambda: self.set_mode("single"), ACC)
        self.btn_cluster = Button((x + 172, 412, 160, 34), "Cluster (LAN)", lambda: self.set_mode("cluster"), (58, 70, 96))
        self.btn_advanced = Button((x, 466, 210, 32), "Advanced: Hidden", self.toggle_advanced, (58, 70, 96))
        self.st_ranks = Stepper((x, 512), "MPI ranks (processes)", 1, 1, max(1, self.cores), 1, 420)
        self.st_threads = Stepper((x, 558), "OpenMP threads per rank", self.cores, 1, max(1, self.cores), 1, 420)
        self.btn_discover = Button((x, 466, 160, 34), "Discover laptops", self.do_discover, (44, 148, 118))
        self.btn_start = Button((36, 702, 240, 46), "Start Simulation", self.start_sim, OK)
        self.setup_msg = ""

    def toggle_advanced(self):
        self.show_advanced = not self.show_advanced
        self.btn_advanced.label = "Advanced: Shown" if self.show_advanced else "Advanced: Hidden"
        self.btn_advanced.color = ACC if self.show_advanced else (58, 70, 96)

    def set_mode(self, m):
        self.mode = m
        self.btn_single.color = ACC if m == "single" else (58, 70, 96)
        self.btn_cluster.color = ACC if m == "cluster" else (58, 70, 96)
        if m == "cluster" and not self.nodes:
            self.do_discover()

    def do_discover(self):
        self.nodes = cluster.discover()
        for n in self.nodes:
            self.node_on.setdefault(n["ip"], True)
        self.setup_msg = "Found %d laptop(s) on LAN" % len(self.nodes)

    def start_sim(self):
        hosts = None
        if self.mode == "cluster":
            hosts = [(n["ip"], n["cores"]) for n in self.nodes if self.node_on.get(n["ip"])]
            if len(hosts) < 1:
                self.setup_msg = "Select at least one laptop"
                return
            if len(hosts) == 1:
                hosts = None
        if self.engine:
            self.engine.close()
        self.setup_msg = "Starting engine..."
        self.engine = start_engine(ranks=self.st_ranks.value if self.mode == "single" else 1,
                                   threads=self.st_threads.value if self.mode == "single" else 0, hosts=hosts)
        self.wh = Warehouse(self.st_shelves.value, self.st_robots.value, self.st_carry.value, self.st_cap.value)
        self.db.start_run(self.engine.label, self.engine.ranks, self.engine.threads,
                          self.st_shelves.value, self.st_robots.value)
        self.db.sync_inventory(self.wh)
        self.threads_cfg = self.st_threads.value if self.mode == "single" else 0
        self.build_main()
        self.scene = "main"

    # ---------------------------------------------------------------- main scene
    def build_main(self):
        wh = self.wh
        px = PANEL_X + 14
        iw = PANEL_W - 28
        # Card 1: REQUEST A PRODUCT (y=58..188)
        self.dd_product = Dropdown((px, 110, iw, 30), lambda: [("%s  (%d avail)" % (n, wh.total_available(i)), i) for i, (n, _) in enumerate(wh.products)])
        self.tb_qty = TextBox((px + 36, 148, 72, 30), "5", True, "qty")
        self.btn_submit = Button((px + 116, 148, 104, 30), "Submit", self.on_submit, OK)
        self.btn_burst = Button((px + 228, 148, iw - 228, 30), "Random Burst", self.on_burst, (217, 119, 6))

        # Card 2: UPDATE STOCK (y=198..410)
        self.dd_shelf = Dropdown((px, 250, iw, 30), lambda: [("%s  %s  (%d/%d)" % (s.label, wh.products[s.product][0] if s.product is not None else "-", s.stock, s.capacity), s.id) for s in wh.shelves])
        self.btn_p10 = Button((px, 288, 52, 28), "+10", lambda: self.adjust(10), (46, 138, 98))
        self.btn_m10 = Button((px + 58, 288, 52, 28), "-10", lambda: self.adjust(-10), (185, 68, 68))
        self.tb_stock = TextBox((px + 120, 288, 96, 28), "", True, "units")
        self.btn_set = Button((px + 224, 288, iw - 224, 28), "Set Stock", self.on_set, ACC)
        self.dd_change = Dropdown((px, 326, 214, 28), lambda: [(n, i) for i, (n, _) in enumerate(wh.products)])
        self.btn_change = Button((px + 224, 326, iw - 224, 28), "Assign Shelf", self.on_change, (124, 92, 196))
        self.tb_newprod = TextBox((px, 364, 214, 28), "", False, "new product name")
        self.btn_addprod = Button((px + 224, 364, iw - 224, 28), "Add Product", self.on_addprod, (44, 148, 138))

        # Bottom controls
        by = SH - 50
        self.btn_pause = Button((24, by, 76, 30), "Pause", self.toggle_pause, (64, 78, 108))
        self.speed_btns = [Button((106 + i * 44, by, 38, 30), "x%d" % s, (lambda s=s: self.set_speed(s)), (58, 70, 96)) for i, s in enumerate((1, 2, 4, 8))]
        self.btn_view = Button((288, by, 78, 30), "View: 3D", self.toggle_view, (124, 92, 196))
        self.btn_paths = Button((372, by, 84, 30), "Paths: On", self.toggle_paths, (58, 70, 96))
        self.btn_back = Button((462, by, 68, 30), "Setup", self.back, (130, 66, 76))

        self.widgets = [self.btn_submit, self.btn_burst, self.btn_p10, self.btn_m10, self.btn_set, self.btn_change,
                        self.btn_addprod, self.btn_pause, self.btn_view, self.btn_paths, self.btn_back] + self.speed_btns
        self.textboxes = [self.tb_qty, self.tb_stock, self.tb_newprod]
        self.dropdowns = [self.dd_product, self.dd_shelf, self.dd_change]
        self.paused, self.speed, self.show_paths, self.view_3d = False, 2, True, True
        self.tick_acc, self.cool = 0.0, 0
        self.msg, self.msg_color = "Ready. Submit a request or click a shelf.", DIM
        self.hover_shelf = None
        L = wh.layout
        avail_w = PANEL_X - 44
        avail_h = SH - 170
        self.cell = max(16, min(int(avail_w / L["W"]), int(avail_h / L["H"])))
        self.ox = 20 + (avail_w - L["W"] * self.cell) // 2
        self.oy = 82
        # Isometric 3D projection parameters
        span = L["W"] + L["H"]
        self.iso_tw = max(10.0, min((avail_w - 40) / max(1, span), (avail_h - 60) / max(1, span * 0.56)))
        self.iso_th = self.iso_tw * 0.52
        self.iso_zh = self.iso_tw * 1.05
        self.iso_cx = 20 + avail_w / 2.0 - (L["W"] - L["H"]) * self.iso_tw * 0.1
        self.iso_cy = 96.0 + self.iso_zh * 0.4
        self.tick_dt = 0.2
        self.last_tick_time = time.time()

    def say(self, text, color=TXT):
        self.msg, self.msg_color = text, color

    def on_submit(self):
        pid = self.dd_product.value
        qty = self.tb_qty.int_value(0)
        if pid is None:
            return
        req = self.wh.submit_request(pid, qty)
        self.db.log_request(req, self.wh.products[pid][0])
        self.db.sync_inventory(self.wh)
        if req.status == "REJECTED":
            self.say("Request #%d REJECTED: %s" % (req.id, req.note), BAD)
        else:
            self.say("Request #%d accepted (%s)" % (req.id, req.note), OK)

    def on_burst(self):
        rng, wh = random.Random(), self.wh
        acc = rej = 0
        for _ in range(15):
            pid = rng.randrange(len(wh.products))
            req = wh.submit_request(pid, rng.randint(1, 12))
            self.db.log_request(req, wh.products[pid][0])
            acc += req.status != "REJECTED"
            rej += req.status == "REJECTED"
        self.db.sync_inventory(wh)
        self.say("Burst: %d accepted, %d rejected (no stock)" % (acc, rej), WARN if rej else OK)

    def adjust(self, delta):
        sid = self.dd_shelf.value
        ok, m = self.wh.set_stock(sid, self.wh.shelves[sid].stock + delta)
        if ok:
            self.db.sync_inventory(self.wh)
        self.say(m, OK if ok else BAD)

    def on_set(self):
        if not self.tb_stock.text:
            return
        sid = self.dd_shelf.value
        ok, m = self.wh.set_stock(sid, self.tb_stock.int_value())
        if ok:
            self.db.sync_inventory(self.wh)
        self.say(m, OK if ok else BAD)

    def on_change(self):
        ok, m = self.wh.set_shelf_product(self.dd_shelf.value, self.dd_change.value)
        if ok:
            self.db.sync_inventory(self.wh)
        self.say(m, OK if ok else BAD)

    def on_addprod(self):
        i = self.wh.add_product(self.tb_newprod.text)
        if i is None:
            self.say("Enter a product name", BAD)
        else:
            self.db.sync_inventory(self.wh)
            self.say("Added '%s' — assign to an empty shelf" % self.wh.products[i][0], OK)
            self.tb_newprod.text = ""

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.text = "Resume" if self.paused else "Pause"

    def set_speed(self, s):
        self.speed = s

    def toggle_paths(self):
        self.show_paths = not self.show_paths
        self.btn_paths.text = "Paths: On" if self.show_paths else "Paths: Off"

    def toggle_view(self):
        self.view_3d = not self.view_3d
        self.btn_view.text = "View: 3D" if self.view_3d else "View: 2D"

    def back(self):
        if self.engine:
            self.engine.close()
            self.engine = None
        self.scene = "setup"

    # ---------------------------------------------------------------- events
    def handle(self, e):
        if e.type == pygame.QUIT:
            return False
        if self.scene == "setup":
            ws = [self.st_shelves, self.st_robots, self.st_carry, self.st_cap, self.btn_single, self.btn_cluster,
                  self.btn_start] + self.preset_btns
            if self.mode == "single":
                ws += [self.btn_advanced]
                if self.show_advanced:
                    ws += [self.st_ranks, self.st_threads]
            else:
                ws += [self.btn_discover]
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    for i, n in enumerate(self.nodes):
                        if pygame.Rect(56, 514 + i * 30, 480, 26).collidepoint(e.pos):
                            self.node_on[n["ip"]] = not self.node_on.get(n["ip"], True)
            for w in ws:
                if w.event(e):
                    break
            return True
        for d in self.dropdowns:
            if d.open and d.event(e):
                return True
        for d in self.dropdowns:
            if d.event(e):
                return True
        for t in self.textboxes:
            if t.event(e):
                return True
        if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE and not any(t.active for t in self.textboxes):
            self.toggle_pause()
        if e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN and self.tb_qty.active:
            self.on_submit()
        for w in self.widgets:
            if w.event(e):
                return True
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            s = self.shelf_at(e.pos)
            if s is not None:
                self.dd_shelf.select_value(s.id)
                self.say("Selected %s (%s)" % (s.label, self.wh.products[s.product][0]), ACC)
        return True

    def shelf_at(self, pos):
        if self.view_3d:
            dx = (pos[0] - self.iso_cx) / self.iso_tw
            dy = (pos[1] + 0.4 * self.iso_zh - self.iso_cy) / self.iso_th
            gx = (dx + dy) * 0.5 - 0.5
            gy = (dy - dx) * 0.5 - 0.5
            best, bd = None, 0.75
            for s in self.wh.shelves:
                d = abs(s.x - gx) + abs(s.y - gy)
                if d < bd:
                    best, bd = s, d
            return best
        cx, cy = (pos[0] - self.ox) // self.cell, (pos[1] - self.oy) // self.cell
        for s in self.wh.shelves:
            if s.x == cx and s.y == cy:
                return s
        return None

    # ---------------------------------------------------------------- update
    def update(self, dt):
        if self.scene != "main" or self.paused:
            return
        self.tick_acc += dt * self.speed
        steps = 0
        while self.tick_acc >= self.tick_dt and steps < 6:
            self.tick_acc -= self.tick_dt
            steps += 1
            if self.cool > 0:
                self.cool -= 1
            elif self.wh.pending and self.wh.available_robots():
                res = self.wh.plan(self.engine, {"pick": 2, "drop": 2, "threads": self.threads_cfg})
                if res is not None:
                    self.db.log_timing(self.wh.tick, res["timing"])
                    if not res["assign"]:
                        self.cool = 6
            self.wh.step()
            if self.cool == 0 and self.wh.pending and self.wh.available_robots():
                res = self.wh.plan(self.engine, {"pick": 2, "drop": 2, "threads": self.threads_cfg})
                if res is not None:
                    self.db.log_timing(self.wh.tick, res["timing"])
                    if not res["assign"]:
                        self.cool = 6
            self.last_tick_time = time.time()

    # ---------------------------------------------------------------- drawing: setup
    def draw_setup(self):
        screen.fill(BG)
        draw_text(screen, "Parallel Warehouse Management", F28, TXT, (36, 28))
        draw_text(screen, "Multi-Robot Box Retrieval Simulation  •  MPI + OpenMP Planning Engine", F14, DIM, (36, 66))

        draw_card((36, 108, 636, 246), "WAREHOUSE CONFIGURATION")
        for w in [self.st_shelves, self.st_robots, self.st_carry, self.st_cap] + self.preset_btns:
            w.draw()

        draw_card((36, 368, 636, 314), "EXECUTION MODE & CPU POOLING")
        self.btn_single.draw()
        self.btn_cluster.draw()
        draw_text(screen, "Local CPU cores: %d" % self.cores, F14, DIM, (406, 420))
        if self.mode == "single":
            self.btn_advanced.draw()
            if self.show_advanced:
                self.st_ranks.draw()
                self.st_threads.draw()
                draw_text(screen, "No network needed  •  Total parallel workers = %d ranks × %d threads = %d" %
                          (self.st_ranks.value, self.st_threads.value, self.st_ranks.value * self.st_threads.value),
                          F14, OK, (56, 614))
            else:
                draw_text(screen, "Automatic: %d MPI rank × %d OpenMP threads  (no network needed)" %
                          (self.st_ranks.value, self.st_threads.value),
                          F14, OK, (56, 514))
        else:
            self.btn_discover.draw()
            draw_text(screen, "Run this app on all Windows 11 laptops on the same Wi-Fi/hotspot.", F12, DIM, (230, 474))
            total = 0
            for i, n in enumerate(self.nodes[:4]):
                on = self.node_on.get(n["ip"], True)
                r = pygame.Rect(56, 514 + i * 30, 480, 26)
                pygame.draw.rect(screen, (26, 86, 68) if on else CARD_ALT, r, border_radius=5)
                pygame.draw.rect(screen, OK if on else BORDER, r, 1, border_radius=5)
                draw_text(screen, "%s  %s   (%s)   %d cores" % ("[✓]" if on else "[ ]", n["host"], n["ip"], n["cores"]),
                          F12B, TXT, (r.x + 10, r.y + 5))
                total += n["cores"] if on else 0
            draw_text(screen, "Pooled CPU cores: %d" % total, F16, WARN, (56, 642))

        self.btn_start.draw()
        if self.setup_msg:
            draw_text(screen, self.setup_msg, F14, WARN, (296, 715))

        draw_card((696, 108, 588, 574), "HOW IT WORKS & VISUAL GUIDE")
        lines = [
            "1. Each shelf holds one product — its name & stock bar appear on the map.",
            "2. Submit a request using the Product dropdown + Quantity.",
            "3. Insufficient stock rejects the request immediately (no robot moves).",
            "4. Requests split into trips; robots are assigned via MPI/OpenMP auction,",
            "   routed with A*, and de-conflicted with space-time reservation.",
            "5. Active robots show a Request Badge above them (e.g. #7 Rice -> DZ2).",
            "6. Drop Zones (DZ1–DZ4) at the top receive boxes and flash on delivery.",
            "7. Update stock or add new products at any time from the right panel.",
        ]
        for i, l in enumerate(lines):
            draw_text(screen, l, F14, TXT, (718, 158 + i * 32))

        # Mini visual legend inside right card
        draw_card((718, 434, 544, 224), "LEGEND", bg=BG)
        dz = pygame.Rect(742, 482, 58, 36)
        pygame.draw.rect(screen, DOCK_BG, dz, border_radius=5)
        pygame.draw.rect(screen, DOCK_BD, dz, 2, border_radius=5)
        draw_text(screen, "DZ1", F12B, (180, 255, 220), dz.center, center=True)
        draw_text(screen, "Drop Zone (Collection bay — flashes on delivery)", F12, TXT, (814, 492))

        sh = pygame.Rect(742, 534, 58, 40)
        pygame.draw.rect(screen, (231, 111, 81), sh, border_radius=5)
        draw_text(screen, "Rice", F11, (20, 20, 20), (sh.centerx, sh.y + 11), center=True)
        draw_text(screen, "32/50", F10, (20, 20, 20), (sh.centerx, sh.y + 25), center=True)
        draw_text(screen, "Shelf (1 product per shelf; click to edit stock)", F12, TXT, (814, 546))

        rx, ry = 771, 616
        badge = pygame.Rect(rx - 40, ry - 36, 80, 17)
        pygame.draw.rect(screen, (231, 111, 81), badge, border_radius=8)
        draw_text(screen, "#7 Rice->DZ1", F10, (15, 20, 30), badge.center, center=True)
        draw_robot_sprite(rx, ry, 30, False, 0, -1, (231, 111, 81), "R1")
        draw_text(screen, "Active Robot with Request ID & target Drop Zone badge", F12, TXT, (814, 608))

    # ---------------------------------------------------------------- drawing: main
    def cell_rect(self, x, y):
        c = self.cell
        return pygame.Rect(self.ox + x * c, self.oy + y * c, c, c)

    def center(self, x, y):
        return (self.ox + (x + 0.5) * self.cell, self.oy + (y + 0.5) * self.cell)

    def draw_main(self):
        wh, c = self.wh, self.cell
        screen.fill(BG)
        L = wh.layout

        # Top header bar
        pygame.draw.rect(screen, CARD, (0, 0, SW, 48))
        pygame.draw.line(screen, BORDER, (0, 48), (SW, 48), 1)
        draw_text(screen, "PARALLEL WAREHOUSE", F16, TXT, (20, 14))
        eng_pill = pygame.Rect(228, 11, 360, 26)
        pygame.draw.rect(screen, CARD_ALT, eng_pill, border_radius=13)
        pygame.draw.rect(screen, BORDER, eng_pill, 1, border_radius=13)
        draw_text(screen, self.engine.label, F12, ACC, eng_pill.center, center=True)
        draw_text(screen, "Tick %d" % wh.tick, F12B, DIM, (PANEL_X - 24, 16), right=True)

        self.hover_shelf = self.shelf_at(pygame.mouse.get_pos())
        if self.view_3d:
            self.draw_world_3d()
        else:
            self.draw_world_2d()

        # Hover tooltip
        s = self.hover_shelf
        if s is not None:
            t = "%s • %s   Stock: %d/%d   Reserved: %d" % (s.label, wh.products[s.product][0], s.stock, s.capacity, s.reserved)
            w = F12B.size(t)[0] + 18
            mx, my = pygame.mouse.get_pos()
            r = pygame.Rect(min(mx + 14, PANEL_X - w - 10), my + 14, w, 26)
            pygame.draw.rect(screen, (10, 14, 24), r, border_radius=6)
            pygame.draw.rect(screen, ACC, r, 1, border_radius=6)
            draw_text(screen, t, F12B, TXT, (r.x + 9, r.y + 5))

        self.draw_panel()
        self.draw_status()
        for d in self.dropdowns:
            d.draw_list()

    def draw_robot_badge(self, r, x, y, y_offset):
        if r.trip is None:
            return
        t = r.trip
        wh = self.wh
        n_docks = len(wh.layout["docks"])
        pname = wh.products[t.shelf.product][0][:6]
        dz_num = (t.id % n_docks) + 1
        if r.k < r.pickT:
            tag = "#%d %s->%s" % (t.req.id, pname, t.shelf.label)
        elif r.k < r.dropT:
            tag = "#%d %s->DZ%d" % (t.req.id, pname, dz_num)
        else:
            tag = "#%d done" % t.req.id
        bw = F10.size(tag)[0] + 10
        br = pygame.Rect(int(x - bw // 2), int(y - y_offset - 16), bw, 16)
        pcol = wh.products[t.shelf.product][1]
        pygame.draw.rect(screen, pcol, br, border_radius=8)
        pygame.draw.rect(screen, (15, 20, 30), br, 1, border_radius=8)
        tc_b = (15, 20, 30) if sum(pcol) > 380 else (255, 255, 255)
        draw_text(screen, tag, F10, tc_b, br.center, center=True)

    def iso_pt(self, gx, gy, gz=0.0):
        return (self.iso_cx + (gx - gy) * self.iso_tw,
                self.iso_cy + (gx + gy) * self.iso_th - gz * self.iso_zh)

    def draw_iso_box(self, gx, gy, w, d, h, top_col, border_col=None):
        p00 = self.iso_pt(gx, gy, h)
        p10 = self.iso_pt(gx + w, gy, h)
        p11 = self.iso_pt(gx + w, gy + d, h)
        p01 = self.iso_pt(gx, gy + d, h)
        b10 = self.iso_pt(gx + w, gy, 0)
        b11 = self.iso_pt(gx + w, gy + d, 0)
        b01 = self.iso_pt(gx, gy + d, 0)
        left_face = [p01, p11, b11, b01]
        right_face = [p10, p11, b11, b10]
        top_face = [p00, p10, p11, p01]
        pygame.draw.polygon(screen, shade(top_col, 0.72), left_face)
        pygame.draw.polygon(screen, shade(top_col, 0.54), right_face)
        pygame.draw.polygon(screen, top_col, top_face)
        if border_col:
            pygame.draw.polygon(screen, border_col, left_face, 1)
            pygame.draw.polygon(screen, border_col, right_face, 1)
            pygame.draw.polygon(screen, border_col, top_face, 1)
        return top_face

    def draw_world_3d(self):
        wh = self.wh
        L = wh.layout
        # Floor tiles
        for y in range(L["H"]):
            for x in range(L["W"]):
                pts = [self.iso_pt(x, y), self.iso_pt(x + 1, y), self.iso_pt(x + 1, y + 1), self.iso_pt(x, y + 1)]
                pygame.draw.polygon(screen, AISLE, pts)
                pygame.draw.polygon(screen, FLOOR, pts, 1)

        # Robot home pads
        for (x, y) in L["homes"]:
            pts = [self.iso_pt(x + 0.15, y + 0.15), self.iso_pt(x + 0.85, y + 0.15),
                   self.iso_pt(x + 0.85, y + 0.85), self.iso_pt(x + 0.15, y + 0.85)]
            pygame.draw.polygon(screen, (48, 66, 102), pts, 1)

        # Drop Zone 3D platforms + banner
        banner_pt = self.iso_pt(L["W"] * 0.5, -0.35, 0.35)
        br_top = pygame.Rect(int(banner_pt[0] - 110), int(banner_pt[1] - 10), 220, 20)
        pygame.draw.rect(screen, (16, 56, 46), br_top, border_radius=5)
        pygame.draw.rect(screen, DOCK_BD, br_top, 1, border_radius=5)
        draw_text(screen, "DROP ZONE  (COLLECTION BAYS)", F10, (167, 243, 208), br_top.center, center=True)

        for idx, (x, y) in enumerate(L["docks"]):
            flashing = wh.dock_flash[idx] > 0
            col = (52, 211, 153) if flashing else DOCK_BG
            bd = (255, 255, 255) if flashing else DOCK_BD
            self.draw_iso_box(x + 0.08, y + 0.08, 0.84, 0.84, 0.16, col, bd)
            tc = self.iso_pt(x + 0.5, y + 0.5, 0.16)
            draw_text(screen, "DZ%d" % (idx + 1), F10, (15, 20, 30) if flashing else (180, 255, 220), tc, center=True)

        # Planned paths along the 3D floor
        alpha = min(1.0, (time.time() - self.last_tick_time) / (self.tick_dt / max(1, self.speed))) if not self.paused else 1.0
        if self.show_paths:
            for r in wh.robots:
                if r.trip and r.k < len(r.path):
                    pts = [self.iso_pt(r.x + 0.5, r.y + 0.5, 0.05)] + [self.iso_pt(p[0] + 0.5, p[1] + 0.5, 0.05) for p in r.path[r.k:]]
                    col = wh.products[r.trip.shelf.product][1]
                    for i in range(0, len(pts) - 1, 2):
                        pygame.draw.line(screen, col, pts[i], pts[i + 1], 2)

        # Depth-sorted shelves + robots
        items = []
        for s in wh.shelves:
            items.append((s.x + s.y, 0, s))
        for r in wh.robots:
            fx = r.px + (r.x - r.px) * alpha
            fy = r.py + (r.y - r.py) * alpha
            items.append((fx + fy, 1, (r, fx, fy)))
        items.sort(key=lambda it: (it[0], it[1]))

        sel = self.dd_shelf.value
        rsz = max(16, int(self.iso_tw * 1.1))
        for _, kind, obj in items:
            if kind == 0:
                s = obj
                col = wh.products[s.product][1] if s.product is not None else (90, 90, 90)
                if s.stock == 0:
                    col = shade(col, 0.35)
                if s.flash:
                    col = (255, 255, 255)
                # Rack base + 3D stock cube proportional to fill level
                self.draw_iso_box(s.x + 0.1, s.y + 0.1, 0.8, 0.8, 0.14, (45, 55, 76), BORDER)
                h = 0.18 + 0.72 * (s.stock / max(1, s.capacity))
                bd = (255, 255, 255) if s.id == sel else shade(col, 0.4)
                self.draw_iso_box(s.x + 0.14, s.y + 0.14, 0.72, 0.72, h, col, bd)
                top_c = self.iso_pt(s.x + 0.5, s.y + 0.5, h)
                name = wh.products[s.product][0][:7] if s.product is not None else "-"
                tc = (15, 20, 30) if sum(col) > 380 else (255, 255, 255)
                draw_text(screen, name, F10, tc, (top_c[0], top_c[1] - 4), center=True)
                draw_text(screen, "%d" % s.stock, F10, tc, (top_c[0], top_c[1] + 6), center=True)
            else:
                r, fx, fy = obj
                px, py = self.iso_pt(fx + 0.5, fy + 0.5, 0.12)
                carry_col = wh.products[r.carrying][1] if r.carrying is not None else None
                draw_robot_sprite(px, py, rsz, r.idle, r.x - r.px, r.y - r.py, carry_col, "R%d" % (r.id + 1))
                self.draw_robot_badge(r, px, py, int(rsz * 0.45) + 8)

    def draw_world_2d(self):
        wh, c = self.wh, self.cell
        L = wh.layout
        # Warehouse outer frame
        grid_r = pygame.Rect(self.ox - 4, self.oy - 4, L["W"] * c + 8, L["H"] * c + 8)
        pygame.draw.rect(screen, FLOOR, grid_r, border_radius=8)
        pygame.draw.rect(screen, BORDER, grid_r, 1, border_radius=8)

        # Drop Zone header strip above row 0
        dz_banner = pygame.Rect(self.ox, self.oy - 22, L["W"] * c, 18)
        pygame.draw.rect(screen, (16, 56, 46), dz_banner, border_radius=4)
        pygame.draw.rect(screen, DOCK_BD, dz_banner, 1, border_radius=4)
        draw_text(screen, "DROP ZONE  (COLLECTION BAYS)", F10, (167, 243, 208), dz_banner.center, center=True)

        for y in range(L["H"]):
            for x in range(L["W"]):
                if L["grid"][y][x] != "#":
                    pygame.draw.rect(screen, AISLE, self.cell_rect(x, y).inflate(-2, -2), border_radius=3)

        # Drop Zone bays (DZ1..DZn)
        for idx, (x, y) in enumerate(L["docks"]):
            dr = self.cell_rect(x, y).inflate(-2, -2)
            flashing = wh.dock_flash[idx] > 0
            bg = (52, 211, 153) if flashing else DOCK_BG
            pygame.draw.rect(screen, bg, dr, border_radius=5)
            pygame.draw.rect(screen, (255, 255, 255) if flashing else DOCK_BD, dr, 2, border_radius=5)
            draw_text(screen, "DZ%d" % (idx + 1), F10 if c < 34 else F12B,
                      (15, 20, 30) if flashing else (180, 255, 220), dr.center, center=True)

        # Robot home pads
        for (x, y) in L["homes"]:
            hr = self.cell_rect(x, y).inflate(-6, -6)
            pygame.draw.rect(screen, (42, 54, 82), hr, 1, border_radius=4)

        # Shelves
        fs = F12B if c >= 38 else F10
        fs_sub = F11 if c >= 38 else F10
        sel = self.dd_shelf.value
        for s in wh.shelves:
            r = self.cell_rect(s.x, s.y).inflate(-3, -3)
            col = wh.products[s.product][1] if s.product is not None else (90, 90, 90)
            if s.stock == 0:
                col = tuple(int(v * 0.35) for v in col)
            if s.flash:
                col = (255, 255, 255)
            pygame.draw.rect(screen, col, r, border_radius=5)
            if s.id == sel:
                pygame.draw.rect(screen, (255, 255, 255), r.inflate(4, 4), 2, border_radius=6)
            name = wh.products[s.product][0] if s.product is not None else "-"
            while fs.size(name)[0] > r.w - 4 and len(name) > 2:
                name = name[:-1]
            dark = sum(col) > 380
            tc = (15, 20, 30) if dark else (255, 255, 255)
            draw_text(screen, name, fs, tc, (r.centerx, r.y + r.h * 0.28), center=True)
            draw_text(screen, "%d/%d" % (s.stock, s.capacity), fs_sub, tc, (r.centerx, r.y + r.h * 0.58), center=True)
            frac = s.stock / max(1, s.capacity)
            pygame.draw.rect(screen, (0, 0, 0), (r.x + 4, r.bottom - 7, r.w - 8, 4), border_radius=2)
            pygame.draw.rect(screen, tc, (r.x + 4, r.bottom - 7, max(2, int((r.w - 8) * frac)) if s.stock > 0 else 0, 4), border_radius=2)

        # Planned paths
        alpha = min(1.0, (time.time() - self.last_tick_time) / (self.tick_dt / max(1, self.speed))) if not self.paused else 1.0
        if self.show_paths:
            for r in wh.robots:
                if r.trip and r.k < len(r.path):
                    pts = [self.center(r.x, r.y)] + [self.center(*p) for p in r.path[r.k:]]
                    col = wh.products[r.trip.shelf.product][1]
                    for i in range(0, len(pts) - 1, 2):
                        pygame.draw.line(screen, col, pts[i], pts[i + 1], 2)

        # Robots + Request Badge above each active robot
        for r in wh.robots:
            px, py = self.center(r.px, r.py)
            qx, qy = self.center(r.x, r.y)
            x, y = px + (qx - px) * alpha, py + (qy - py) * alpha
            carry_col = wh.products[r.carrying][1] if r.carrying is not None else None
            draw_robot_sprite(x, y, c, r.idle, r.x - r.px, r.y - r.py, carry_col, "R%d" % (r.id + 1))
            self.draw_robot_badge(r, x, y, int(c * 0.42) + 8)

    def draw_panel(self):
        wh = self.wh
        px = PANEL_X + 14
        # Card 1: Request a product
        draw_card((PANEL_X, 58, PANEL_W, 130), "REQUEST A PRODUCT")
        draw_text(screen, "Product", F12, DIM, (px, 92))
        self.dd_product.draw()
        draw_text(screen, "Qty", F12, DIM, (px, 155))
        self.tb_qty.draw()
        self.btn_submit.draw()
        self.btn_burst.draw()

        # Card 2: Update stock
        draw_card((PANEL_X, 198, PANEL_W, 206), "UPDATE STOCK")
        draw_text(screen, "Shelf (or click a shelf on the map)", F12, DIM, (px, 232))
        self.dd_shelf.draw()
        self.btn_p10.draw()
        self.btn_m10.draw()
        self.tb_stock.draw()
        self.btn_set.draw()
        self.dd_change.draw()
        self.btn_change.draw()
        self.tb_newprod.draw()
        self.btn_addprod.draw()

        # Card 3: Requests list
        draw_card((PANEL_X, 414, PANEL_W, 314), "REQUESTS & DROP STATUS")
        y = 450
        for req in reversed(wh.requests[-9:]):
            col = {"COMPLETED": OK, "REJECTED": BAD, "IN_PROGRESS": WARN, "ALLOCATED": ACC}.get(req.status, TXT)
            line = "#%d  %-8s  x%-3d  %s" % (req.id, wh.products[req.product][0][:8], req.qty, req.status.replace("_", " "))
            draw_text(screen, line, F12B, col, (px, y))
            if req.status in ("IN_PROGRESS", "COMPLETED"):
                draw_text(screen, "%d/%d" % (req.delivered, req.qty), F12, DIM, (PANEL_X + PANEL_W - 14, y), right=True)
            y += 26
        draw_text(screen, "Pending trips in queue: %d" % len(wh.pending), F12, DIM, (px, 704))

        # Status toast bar
        toast_r = pygame.Rect(PANEL_X, 738, PANEL_W, 48)
        pygame.draw.rect(screen, CARD, toast_r, border_radius=8)
        pygame.draw.rect(screen, self.msg_color if self.msg_color != DIM else BORDER, toast_r, 1, border_radius=8)
        draw_text(screen, self.msg[:50], F12B, self.msg_color, (toast_r.x + 12, toast_r.y + 16))

    def draw_status(self):
        wh = self.wh
        bar = pygame.Rect(14, SH - 58, PANEL_X - 28, 46)
        draw_card(bar)
        for w in [self.btn_pause, self.btn_paths, self.btn_back] + self.speed_btns:
            w.draw()
        for i, b in enumerate(self.speed_btns):
            if (1, 2, 4, 8)[i] == self.speed:
                pygame.draw.rect(screen, WARN, b.rect, 2, border_radius=7)
        busy = wh.busy_count()
        rx = 534
        draw_text(screen, "Robots: %d  (Busy %d / Idle %d)" % (len(wh.robots), busy, len(wh.robots) - busy), F12B, TXT, (rx, SH - 51))
        t = wh.last_timing
        if t:
            draw_text(screen, "Plan: K1 %.2fms  K3 %.2fms  K4 %.2fms  Total %.2fms  [%dr×%dt]" %
                      (t["k1"], t["k3"], t["k4"], t["total"], t["ranks"], t["threads"]), F11, DIM, (rx, SH - 31))
        else:
            draw_text(screen, "Waiting for first batch...", F11, DIM, (rx, SH - 31))

    # ---------------------------------------------------------------- main loop
    def run(self):
        running = True
        last = time.time()
        while running:
            now = time.time()
            dt, last = now - last, now
            for e in pygame.event.get():
                if not self.handle(e):
                    running = False
            self.update(dt)
            if self.scene == "setup":
                self.draw_setup()
            else:
                self.draw_main()
            pygame.display.flip()
            clock.tick(60)
        if self.engine:
            self.engine.close()
        self.db.close()
        self.agent.running = False
        pygame.quit()


if __name__ == "__main__":
    App().run()
