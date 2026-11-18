# L-SATS updater (called by UPDATE.bat). ASCII only: Windows PowerShell 5.1 reads scripts as ANSI.
# Downloads L-SATS-update.zip (program files only) from the latest GitHub release and replaces
# app.py, slab, demo_data, tools, START.bat ... The python folder is kept as is.
# If the new version needs different packages, it opens the full ZIP download instead.
# A running program is closed first and START.bat is started again at the end (also when already up to date).
param(
    [string]$Source = 'https://github.com/kuri-dev9/L-SATS/releases/latest/download/L-SATS-update.zip',
    [switch]$NoStart  # do not start START.bat at the end (CI check)
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$FullZip = 'https://github.com/kuri-dev9/L-SATS/releases/latest/download/L-SATS-windows.zip'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Fail([string]$msg) {
    Write-Host ''
    Write-Host "[ERROR] $msg" -ForegroundColor Red
    if ($script:stopped) { StartProgram }  # nothing was replaced: start the current version again
    exit 1
}

Write-Host '============================================================'
Write-Host ' L-SATS update'
Write-Host '============================================================'

# The program must be closed: START.bat and python files would be replaced while in use.
$running = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith((Join-Path $root 'python'), 'OrdinalIgnoreCase') }
function StartProgram {
    if ($NoStart) { return }
    Write-Host 'Starting the program (START.bat)...'
    Start-Process cmd.exe -ArgumentList '/c', 'START.bat' -WorkingDirectory $root
}
if ($running) {
    Write-Host 'Closing the running program...'
    # Also close the black START.bat window (the cmd.exe that started python), not only python itself
    $parents = foreach ($p in $running) {
        (Get-CimInstance Win32_Process -Filter "ProcessId = $($p.Id)" -ErrorAction SilentlyContinue).ParentProcessId
    }
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($pp in $parents) {
        if ($pp) { Get-Process -Id $pp -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'cmd' } |
            Stop-Process -Force -ErrorAction SilentlyContinue }
    }
    $script:stopped = $true
    Start-Sleep -Seconds 2
}

$cur = 'unknown'
if (Test-Path VERSION) { $cur = (Get-Content VERSION -Raw).Trim() }
Write-Host "Current version: $cur"

$tmp = Join-Path $env:TEMP ('lsats-update-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $tmp | Out-Null
try {
    $zip = Join-Path $tmp 'update.zip'
    Write-Host 'Downloading the latest program files...'
    try {
        if ($Source -match '^https?://') {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri $Source -OutFile $zip
        } else {
            Copy-Item $Source $zip
        }
    } catch {
        Fail "Download failed. Check the internet connection. ($($_.Exception.Message))"
    }
    Expand-Archive $zip (Join-Path $tmp 'x')
    $new = Join-Path $tmp 'x\L-SATS'
    if (-not (Test-Path (Join-Path $new 'app.py'))) { Fail 'The downloaded file is not a valid update.' }

    $latest = (Get-Content (Join-Path $new 'VERSION') -Raw).Trim()
    Write-Host "Latest version:  $latest"
    if ($cur -eq $latest) {
        Write-Host ''
        Write-Host 'Already up to date. Nothing to do.' -ForegroundColor Green
        StartProgram
        exit 0
    }

    # Are the installed packages enough for the new version?
    Write-Host 'Checking packages...'
    & (Join-Path $root 'python\python.exe') (Join-Path $new 'tools\check_requirements.py') (Join-Path $new 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'This version needs new packages, so a small update is not enough.' -ForegroundColor Yellow
        Write-Host 'Download the full ZIP once more (the browser opens now):'
        Write-Host "  $FullZip"
        Start-Process $FullZip
        StartProgram
        exit 2
    }

    # Back up the current program files (small), then replace them.
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $root "backup\$cur-$stamp"
    New-Item -ItemType Directory -Force $backup | Out-Null
    $items = Get-ChildItem $new -Force | Where-Object { $_.Name -ne 'UPDATE.bat' }
    foreach ($it in $items) {
        $dst = Join-Path $root $it.Name
        if (Test-Path $dst) { Copy-Item -Recurse -Force $dst $backup }
    }
    foreach ($it in $items) {
        $dst = Join-Path $root $it.Name
        # Folders are replaced whole so that deleted files do not stay behind.
        # tools holds this running script; overwrite it instead of deleting it.
        if ($it.PSIsContainer -and $it.Name -ne 'tools' -and (Test-Path $dst)) {
            Remove-Item -Recurse -Force $dst
        }
        Copy-Item -Recurse -Force $it.FullName $root
    }
    Write-Host ''
    Write-Host "Updated: $cur -> $latest" -ForegroundColor Green
    Write-Host "Old files were saved in backup\$cur-$stamp"
    StartProgram
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
