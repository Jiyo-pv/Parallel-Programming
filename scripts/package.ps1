# Package WarehouseSim into a portable Windows 11 folder and .zip (no extra installation for end users)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $Root "dist\WarehouseSim-win64"

& "$PSScriptRoot\build.ps1"

python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..."
    python -m pip install pyinstaller
}

Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --onedir --windowed --name WarehouseSim `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build_pyinstaller") `
    --specpath (Join-Path $Root "build_pyinstaller") `
    --paths (Join-Path $Root "app") `
    (Join-Path $Root "app\main.py")

# PyInstaller puts output in dist\WarehouseSim; rename to WarehouseSim-win64
Rename-Item (Join-Path $Root "dist\WarehouseSim") "WarehouseSim-win64"

# Copy compiled C++ engines
$PkgEngine = Join-Path $DistDir "engine"
New-Item -ItemType Directory -Force $PkgEngine | Out-Null
Copy-Item (Join-Path $Root "engine\*.exe") $PkgEngine -ErrorAction SilentlyContinue

# Copy MS-MPI runtime binaries if installed on the build machine
$MpiBin = "C:\Program Files\Microsoft MPI\Bin"
$MpiSys = Join-Path $env:WINDIR "System32\msmpi.dll"
if (Test-Path $MpiBin) {
    $PkgMpi = Join-Path $DistDir "mpi"
    New-Item -ItemType Directory -Force $PkgMpi | Out-Null
    Copy-Item "$MpiBin\mpiexec.exe" $PkgMpi -ErrorAction SilentlyContinue
    Copy-Item "$MpiBin\smpd.exe" $PkgMpi -ErrorAction SilentlyContinue
    if (Test-Path $MpiSys) {
        Copy-Item $MpiSys $PkgMpi
        Copy-Item $MpiSys $PkgEngine
    }
}

# Include end-user README.txt in the portable folder
@"
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
"@ | Set-Content -Path (Join-Path $DistDir "README.txt") -Encoding UTF8

$ZipPath = Join-Path $Root "dist\WarehouseSim-win64.zip"
Remove-Item $ZipPath -ErrorAction SilentlyContinue
Compress-Archive -Path $DistDir -DestinationPath $ZipPath
Write-Host "Portable package created at: $ZipPath"
