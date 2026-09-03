# Build lightweight offline package (RapidOCR + ONNXRuntime).
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\packaging\build_offline_python.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PkgName = "PdfTableExtractor_python_offline"
$Stage = Join-Path $Root ("dist\" + $PkgName)
$ReleaseDir = Join-Path $Root "release"
$Tpl = Join-Path $PSScriptRoot "offline_python"

Write-Host "==> Python info..." -ForegroundColor Cyan
$pyVer = & python -c "import sys; print('%d.%d.%d' % (sys.version_info.major, sys.version_info.minor, sys.version_info.micro))"
$pyTag = & python -c "import sys; print('cp%d%d' % (sys.version_info.major, sys.version_info.minor))"
$plat = & python -c "import platform; print(platform.system() + ' ' + platform.machine())"
Write-Host ("  version={0}  tag={1}  platform={2}" -f $pyVer, $pyTag, $plat)

# Locate RapidOCR models already cached in site-packages
$ModelSrc = & python -c "import rapidocr, pathlib; print(pathlib.Path(rapidocr.__file__).parent / 'models')"
if (-not (Test-Path $ModelSrc)) {
    throw ("RapidOCR models not found: {0}. Init RapidOCR once online first." -f $ModelSrc)
}
$onnxCount = @(Get-ChildItem $ModelSrc -Filter *.onnx -ErrorAction SilentlyContinue).Count
if ($onnxCount -lt 1) {
    throw ("No .onnx files in {0}. Initialize RapidOCR once online first." -f $ModelSrc)
}

if (Test-Path $Stage) {
    Write-Host ("==> Cleaning old stage: {0}" -f $Stage) -ForegroundColor Yellow
    Remove-Item -Recurse -Force $Stage
}
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "wheels") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "models") | Out-Null

Write-Host "==> Copy source..." -ForegroundColor Cyan
Copy-Item (Join-Path $Root "main.py") $Stage
Copy-Item (Join-Path $Root "requirements.txt") $Stage
Copy-Item -Recurse (Join-Path $Root "pdf_table_extractor") (Join-Path $Stage "pdf_table_extractor")
Get-ChildItem (Join-Path $Stage "pdf_table_extractor") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "==> Copy install scripts..." -ForegroundColor Cyan
Copy-Item (Join-Path $Tpl "usage.txt") (Join-Path $Stage "usage.txt")
Copy-Item (Join-Path $Tpl "install.bat") (Join-Path $Stage "install.bat")
Copy-Item (Join-Path $Tpl "run.bat") (Join-Path $Stage "run.bat")

$verLines = @(
    ("Python {0} ({1}, 64bit Windows)" -f $pyVer, $pyTag)
    ("Build platform: {0}" -f $plat)
    ("OCR: RapidOCR + ONNXRuntime (no Paddle)")
    ("Customer should use the same major.minor 64-bit Python, e.g. {0}" -f $pyVer)
)
[System.IO.File]::WriteAllLines((Join-Path $Stage "PYTHON_VERSION.txt"), $verLines)

Write-Host "==> Download wheels..." -ForegroundColor Cyan
$wheels = Join-Path $Stage "wheels"
& python -m pip download -r (Join-Path $Root "requirements.txt") -d $wheels
if ($LASTEXITCODE -ne 0) { throw ("pip download failed, exit={0}" -f $LASTEXITCODE) }

Write-Host "==> Copy OCR onnx models..." -ForegroundColor Cyan
Copy-Item (Join-Path $ModelSrc "*.onnx") (Join-Path $Stage "models") -Force
Get-ChildItem (Join-Path $Stage "models") -Filter *.onnx | ForEach-Object { Write-Host ("  + {0}" -f $_.Name) }

Write-Host "==> Create zip..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$ZipPath = Join-Path $ReleaseDir ($PkgName + ".zip")
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Push-Location (Join-Path $Root "dist")
try {
    tar -a -cf $ZipPath $PkgName
} finally {
    Pop-Location
}

$folderMb = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
$zipMb = (Get-Item $ZipPath).Length / 1MB
$wheelMb = (Get-ChildItem $wheels -File | Measure-Object Length -Sum).Sum / 1MB
$modelMb = (Get-ChildItem (Join-Path $Stage "models") -Recurse -File | Measure-Object Length -Sum).Sum / 1MB

Write-Host ""
Write-Host ("Done folder: {0}" -f $Stage) -ForegroundColor Green
Write-Host ("  wheels MB: {0:N0}" -f $wheelMb)
Write-Host ("  models MB: {0:N0}" -f $modelMb)
Write-Host ("  total folder MB: {0:N0}" -f $folderMb)
Write-Host ("Zip: {0}  ({1:N0} MB)" -f $ZipPath, $zipMb) -ForegroundColor Green
Write-Host "Customer: unzip -> install.bat -> run.bat" -ForegroundColor Green
