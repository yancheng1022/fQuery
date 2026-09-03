# Build offline portable package for intranet customers.
# Usage: powershell -ExecutionPolicy Bypass -File .\packaging\build_portable.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$DistName = "PdfTableExtractor"
$OutDir = Join-Path $Root "dist\$DistName"
$ModelsSrc = Join-Path $env:USERPROFILE ".paddlex\official_models"
$NeedModels = @("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec")

Write-Host "==> Checking OCR models..." -ForegroundColor Cyan
foreach ($m in $NeedModels) {
    $p = Join-Path $ModelsSrc $m
    if (-not (Test-Path $p)) {
        throw "Missing model folder: $p. Run extraction once locally to download models, then rebuild."
    }
}

Write-Host "==> PyInstaller build (this can take a long time)..." -ForegroundColor Cyan
$py = (Get-Command python).Source
& $py -m PyInstaller --noconfirm --clean (Join-Path $Root "PdfTableExtractor.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed, exit=$LASTEXITCODE" }

if (-not (Test-Path $OutDir)) {
    throw "Output folder not found: $OutDir"
}

Write-Host "==> Copy offline OCR models..." -ForegroundColor Cyan
$modelsDst = Join-Path $OutDir ".paddlex\official_models"
New-Item -ItemType Directory -Force -Path $modelsDst | Out-Null
foreach ($m in $NeedModels) {
    $src = Join-Path $ModelsSrc $m
    $dst = Join-Path $modelsDst $m
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Recurse -Force $src $dst
    Write-Host "  + $m"
}

Write-Host "==> Write launcher and readme..." -ForegroundColor Cyan
Copy-Item -Force (Join-Path $PSScriptRoot "使用说明.txt") (Join-Path $OutDir "使用说明.txt")

$bat = "@echo off`r`ncd /d `"%~dp0`"`r`nstart `"`" `"%~dp0PdfTableExtractor.exe`"`r`n"
[System.IO.File]::WriteAllText((Join-Path $OutDir "启动.bat"), $bat, [System.Text.Encoding]::ASCII)

Write-Host "==> Create zip for delivery..." -ForegroundColor Cyan
$ReleaseDir = Join-Path $Root "release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$ZipPath = Join-Path $ReleaseDir "PdfTableExtractor_内网离线版.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Push-Location (Join-Path $Root "dist")
try {
    tar -a -cf $ZipPath $DistName
} finally {
    Pop-Location
}

Write-Host "==> Size summary..." -ForegroundColor Cyan
$size = (Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
$zipMb = if (Test-Path $ZipPath) { (Get-Item $ZipPath).Length / 1MB } else { 0 }
Write-Host ("Done folder: {0}" -f $OutDir) -ForegroundColor Green
Write-Host ("Approx folder size: {0:N2} GB" -f $size) -ForegroundColor Green
Write-Host ("Zip: {0} ({1:N0} MB)" -f $ZipPath, $zipMb) -ForegroundColor Green
Write-Host "Send the zip to the customer; they unzip and double-click PdfTableExtractor.exe." -ForegroundColor Green
