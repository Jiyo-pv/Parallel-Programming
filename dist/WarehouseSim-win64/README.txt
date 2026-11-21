WarehouseSim - Portable Windows Edition
=======================================

How to Run
----------
1. Extract the ENTIRE WarehouseSim-win64.zip folder first
   (Right-click the .zip -> "Extract All...").
   Do NOT double-click WarehouseSim.exe from inside the zip preview.
2. Open the extracted "WarehouseSim-win64" folder.
3. Double-click "WarehouseSim.exe".

Troubleshooting
---------------
- "Windows protected your PC" (SmartScreen):
  Click "More info" -> "Run anyway".
- Windows Firewall prompt:
  If you plan to use Cluster (LAN) mode with other laptops on the same
  Wi-Fi or hotspot, click "Allow" so devices can discover each other.
- Keep all files together:
  Do not move WarehouseSim.exe out of this folder; it needs the "engine",
  "mpi", and "_internal" folders next to it.

Where Data is Saved
-------------------
Simulation logs, inventory snapshots, and timings are saved locally to:
%APPDATA%\WarehouseSim\warehouse.db
