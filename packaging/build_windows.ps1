# Python 포함 Windows 휴대용 패키지(L-SATS-windows.zip)를 만든다.
# GitHub Actions(windows-latest)에서 setup-python으로 설치한 Python과 같은 버전의
# 공식 embeddable Python을 받아 패키지를 넣는다.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$pkg = Join-Path $dist 'L-SATS'
Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $pkg | Out-Null

$ver = (python -c "import platform; print(platform.python_version())").Trim()
$tag = (python -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')").Trim()
Write-Host "Python $ver"

# 1) embeddable Python
$zip = Join-Path $dist 'python-embed.zip'
Invoke-WebRequest "https://www.python.org/ftp/python/$ver/python-$ver-embed-amd64.zip" -OutFile $zip
$py = Join-Path $pkg 'python'
Expand-Archive $zip $py
Remove-Item $zip
# 패키지 경로와 앱 폴더(..)를 검색 경로에 넣고 site를 켠다
Set-Content -Encoding ascii (Join-Path $py "python$tag._pth") @"
python$tag.zip
.
Lib\site-packages
..
import site
"@

# 2) 패키지 설치 (같은 Python 버전·플랫폼)
python -m pip install --no-cache-dir --target (Join-Path $py 'Lib\site-packages') -r (Join-Path $root 'requirements.txt')

# 3) VC++ 런타임 DLL 동봉 (재배포 패키지가 없는 PC 대비)
foreach ($dll in 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') {
    $src = Join-Path $env:WINDIR "System32\$dll"
    if ((Test-Path $src) -and -not (Test-Path (Join-Path $py $dll))) { Copy-Item $src $py }
}

# 4) 앱 파일
Copy-Item (Join-Path $root 'app.py') $pkg
Copy-Item -Recurse (Join-Path $root 'slab') $pkg
Copy-Item -Recurse (Join-Path $root 'demo_data') $pkg
New-Item -ItemType Directory -Force (Join-Path $pkg '.streamlit') | Out-Null
Copy-Item (Join-Path $root '.streamlit\config.toml') (Join-Path $pkg '.streamlit')
Copy-Item (Join-Path $PSScriptRoot 'START.bat') $pkg
Copy-Item (Join-Path $PSScriptRoot 'UPDATE.bat') $pkg
Copy-Item (Join-Path $PSScriptRoot 'HOW-TO-USE.txt') $pkg
Copy-Item (Join-Path $root 'requirements.txt') $pkg
New-Item -ItemType Directory -Force (Join-Path $pkg 'tools') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'update.ps1') (Join-Path $pkg 'tools')
Copy-Item (Join-Path $PSScriptRoot 'check_requirements.py') (Join-Path $pkg 'tools')
# 버전: 태그 빌드면 태그(v0.1.5), 아니면 커밋 해시. UPDATE.bat 이 이 값으로 최신인지 판단한다.
$version = if ($env:GITHUB_REF_NAME -match '^v') { $env:GITHUB_REF_NAME } else { 'dev-' + (git -C $root rev-parse --short HEAD) }
Set-Content -Encoding ascii -NoNewline (Join-Path $pkg 'VERSION') $version
Get-ChildItem $pkg -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Write-Host "version: [$version]"
Get-ChildItem -Force $pkg | ForEach-Object { Write-Host "pkg: $($_.Name)" }

# 5) 압축: 전체(Python 포함)와 업데이트용(프로그램 파일만, UPDATE.bat 이 받는다)
# (Compress-Archive 는 일부 파일을 빠뜨려서 Python zipfile 로 만든다)
function Zip([string]$parent, [string]$name) {
    $base = Join-Path $dist ($name -replace '\.zip$', '')
    python -c "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'L-SATS')" $base $parent
    if ($LASTEXITCODE -ne 0) { throw "zip failed: $name" }
}
$out = Join-Path $dist 'L-SATS-windows.zip'
Zip $dist 'L-SATS-windows.zip'
'full   {0:N0} MB' -f ((Get-Item $out).Length / 1MB) | Write-Host

$upd = Join-Path $dist 'update\L-SATS'
New-Item -ItemType Directory -Force $upd | Out-Null
Get-ChildItem $pkg -Force | Where-Object { $_.Name -ne 'python' } | Copy-Item -Recurse -Destination $upd
$out = Join-Path $dist 'L-SATS-update.zip'
Zip (Join-Path $dist 'update') 'L-SATS-update.zip'
'update {0:N2} MB' -f ((Get-Item $out).Length / 1MB) | Write-Host
python -c "import zipfile, sys; print(*zipfile.ZipFile(sys.argv[1]).namelist(), sep='\n')" $out
