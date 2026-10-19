# Skynet Command - one-time setup. Everything goes into THIS folder (runtime\ = private Python, models\ = speech AI).
$ErrorActionPreference = 'Stop'
$app  = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $app
$rt   = Join-Path $root 'runtime'
$py   = Join-Path $rt 'python\python.exe'
$pyw  = Join-Path $rt 'python\pythonw.exe'
$url  = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.12.15%2B20261013-x86_64-pc-windows-msvc-install_only.tar.gz'
$sha  = 'BBC902D4D187AC4914915BF538196A064B49109A33A104965B5164CED5B80A1E'
function Step($t) { Write-Host ''; Write-Host "=== $t ===" -ForegroundColor Red }
function MakeLink($path) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = $pyw; $s.Arguments = '"' + (Join-Path $app 'skynet_command.py') + '"'
    $s.WorkingDirectory = $app; $s.IconLocation = (Join-Path $app 'skynet_command.ico') + ',0'; $s.Description = 'Skynet Command'; $s.Save()
}
try {
    Write-Host 'SKYNET COMMAND - setup (one time, needs internet, about 5 minutes)' -ForegroundColor Red
    Write-Host "Everything is installed inside: $root"
    if (-not (Test-Path $py)) {
        Step '1/4  Downloading a private Python 3.12 for this folder (~45 MB)'
        New-Item -ItemType Directory -Force $rt | Out-Null
        $tgz = Join-Path $rt 'python.tar.gz'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $tgz -UseBasicParsing
        if ((Get-FileHash $tgz -Algorithm SHA256).Hash -ne $sha) { Remove-Item $tgz; throw 'The Python download is damaged or not the expected file. Run setup again.' }
        Step '2/4  Unpacking'
        tar -xzf $tgz -C $rt
        if ($LASTEXITCODE -ne 0) { throw 'Unpacking failed (Windows 10 or newer is needed).' }
        Remove-Item $tgz
        Get-ChildItem (Join-Path $rt 'python') -Recurse -Filter *.pdb | Remove-Item -Force
    } else { Step '1-2/4  Python already here - skipped' }
    Step '3/4  Installing the speech engine (~300 MB)'
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --no-cache-dir --only-binary=:all: -r (Join-Path $app 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing the speech engine failed - see the messages above.' }
    Step '4/4  Shortcuts'
    MakeLink (Join-Path $root 'Skynet Command.lnk')
    $a = Read-Host 'Also put a shortcut on your Desktop? (Y/N)'
    if ($a -match '^[yY]') { MakeLink (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Skynet Command.lnk') }
    Write-Host ''; Write-Host 'DONE! Starting Skynet Command...' -ForegroundColor Green
    Write-Host 'First start downloads the speech model (once). NVIDIA card? Run "GPU boost (NVIDIA only).bat" later.'
    Start-Process -FilePath $pyw -ArgumentList ('"' + (Join-Path $app 'skynet_command.py') + '"') -WorkingDirectory $app
    Start-Sleep -Seconds 4
} catch {
    Write-Host ''; Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter to close'; exit 1
}
