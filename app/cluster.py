"""LAN discovery of laptops running this app (UDP broadcast) + core counting for the pooled-CPU cluster mode."""
import json
import os
import socket
import subprocess
import sys
import threading
import time

PORT = 5600
MAGIC = b"WAREHOUSE_DISCOVER"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(HERE)
ENGINE_EXE = os.path.join(ROOT, "engine", "engine_mpi.exe")
MPI_DIR = os.path.join(ROOT, "mpi")


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def physical_cores():
    try:
        import psutil
        return psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except Exception:
        return os.cpu_count() or 1


def logical_cores():
    return os.cpu_count() or 1


def node_info():
    return {"host": socket.gethostname(), "ip": local_ip(), "cores": logical_cores(),
            "physical": physical_cores(), "exe": ENGINE_EXE}


class Agent(threading.Thread):
    """Answers discovery requests so other laptops can see this machine and its CPU cores."""

    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
        self.ok = True

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", PORT))
            s.settimeout(0.5)
        except Exception:
            self.ok = False
            return
        while self.running:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception:
                break
            if data == MAGIC:
                try:
                    s.sendto(json.dumps(node_info()).encode(), addr)
                except Exception:
                    pass
        s.close()


def discover(timeout=1.5):
    """Broadcast and collect replies.  Returns a list of node_info dicts (including this PC)."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.3)
    try:
        s.sendto(MAGIC, ("255.255.255.255", PORT))
    except Exception:
        pass
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, _ = s.recvfrom(2048)
            info = json.loads(data.decode())
            found[info["ip"]] = info
        except socket.timeout:
            continue
        except Exception:
            continue
    s.close()
    me = node_info()
    found.setdefault(me["ip"], me)
    return sorted(found.values(), key=lambda n: n["ip"])


def start_smpd(mpi_dir=None):
    """Best effort: start the bundled MS-MPI daemon so other laptops can launch ranks here."""
    candidates = [mpi_dir] if mpi_dir else []
    candidates += [MPI_DIR, r"C:\Program Files\Microsoft MPI\Bin"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for d in candidates:
        exe = os.path.join(d, "smpd.exe")
        if os.path.exists(exe):
            try:
                return subprocess.Popen([exe, "-d", "0"], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, creationflags=flags)
            except Exception:
                return None
    return None
