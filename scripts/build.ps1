# Build the C++ parallel engine (serial, OpenMP, and MPI+OpenMP if MS-MPI + MSVC/CMake are installed)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EngineDir = Join-Path $Root "engine"
$BuildDir = Join-Path $EngineDir "build"

if (Get-Command cmake -ErrorAction SilentlyContinue) {
    Write-Host "CMake found. Configuring..."
    New-Item -ItemType Directory -Force $BuildDir | Out-Null
    cmake -S $EngineDir -B $BuildDir -DCMAKE_BUILD_TYPE=Release
    cmake --build $BuildDir --config Release
} else {
    python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('ziglang') else 1)"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "CMake not found; building engine_serial.exe with ziglang..."
        python -m ziglang c++ -O2 -std=c++17 "$EngineDir\engine.cpp" -o "$EngineDir\engine_serial.exe"
    } elseif (-not (Test-Path "$EngineDir\engine_serial.exe")) {
        Write-Warning "Neither CMake nor ziglang found. The Python fallback engine will be used."
    }
}

Get-ChildItem "$EngineDir\*.exe" -ErrorAction SilentlyContinue | Select-Object Name, Length
