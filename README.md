# Parallel Warehouse Management & Multi-Robot Box Retrieval (MPI + OpenMP)

A Windows 11 simulation and parallel planning engine for warehouse inventory management and multi-robot box retrieval.

## Features
- **Configurable Setup**: Choose number of shelves (presets 12 / 24 / 48 or custom), number of robots (1–50), robot carry capacity, and shelf capacity.
- **One Product per Shelf**: Each shelf displays its assigned product name, colour, `stock/capacity`, and fill bar.
- **Request & Stock Controls**:
  - Select product from a dropdown showing live available units + enter quantity (or trigger a **Random burst** of concurrent requests).
  - **Insufficient stock** rejects the request cleanly—nothing is reserved and no robot moves.
  - **Update Stock** panel (`+10`, `-10`, `Set`, `Change product` on empty shelves, `Add product`) + click any shelf on the map to select it.
- **Parallel Planning Engine (`engine/engine.cpp`)**:
  - **K1 (Distance fields)**: BFS from shelf access cells (OpenMP + MPI cyclic split).
  - **K3 (Robot–task assignment)**: Bertsekas auction algorithm (OpenMP + MPI Allgather).
  - **K4 (Path planning & conflict resolution)**: Parallel static A* followed by space-time A* reservation replanning.
- **Execution Modes**:
  - **Single-PC**: Runs locally with no network required.
  - **Cluster (LAN)**: UDP discovery of Windows 11 laptops on the same Wi-Fi/hotspot, pooling their CPU cores.
- **SQLite Persistence**: Logs runs, inventory snapshots, requests, and kernel timings to `%APPDATA%\WarehouseSim\warehouse.db`.

## Quick Start (from source)
```powershell
python app\main.py
```
`app\engine_client.py` automatically selects `engine_mpi.exe` (via `mpiexec`), `engine_omp.exe`, `engine_serial.exe`, or the built-in Python fallback engine.

## Run Tests & Benchmarks
```powershell
python tests\test_sim.py
python bench\run_bench.py
```
Benchmark results are saved to `bench\results.csv`.

## Build C++ Engines (OpenMP + MS-MPI)
1. Install **Visual Studio 2022 Build Tools** (C++ desktop workload), **CMake**, and **Microsoft MPI (SDK + Runtime)**.
2. Run:
   ```powershell
   .\scripts\build.ps1
   ```
   This compiles `engine_serial.exe`, `engine_omp.exe`, and `engine_mpi.exe` into `engine\`.

## Package as a Portable Windows App
```powershell
.\scripts\package.ps1
```
Creates `dist\WarehouseSim-win64.zip` containing `WarehouseSim.exe`, the compiled C++ engines, and bundled MS-MPI runtime binaries (when installed on the build machine).
