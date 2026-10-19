# NVIDIA graphics cards only: CUDA libraries (~1 GB) into this folder's private Python -> big accurate model on the GPU
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent $MyInvocation.MyCommand.Path; $py = Join-Path (Split-Path -Parent $app) 'runtime\python\python.exe'
try {
    if (-not (Test-Path $py)) { throw 'Run "1 - SETUP (run once).bat" first.' }
    Write-Host 'GPU BOOST - NVIDIA cards only, downloads about 1 GB' -ForegroundColor Red
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --no-cache-dir --only-binary=:all: nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.27.0.42 nvidia-cuda-nvrtc-cu12==12.9.86
    if ($LASTEXITCODE -ne 0) { throw 'Install failed - see above.' }
    & $py -c "import ctranslate2; print('NVIDIA graphics cards found:', ctranslate2.get_cuda_device_count())"
    Write-Host 'DONE! Restart Skynet Command - the header will show the GPU chip.' -ForegroundColor Green
} catch { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red }
Read-Host 'Press Enter to close'
