# Build zero-install green package: embeddable Python 3.12 + RapidOCR.
# Customer: unzip and double-click run.bat (no system Python needed).
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\packaging\build_green.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PkgName = "PdfTableExtractor_green"
$Stage = Join-Path $Root ("dist\" + $PkgName)
$ReleaseDir = Join-Path $Root "release"
$CacheDir = Join-Path $Root "packaging\cache"
$PyVer = "3.12.7"
$PyEmbedUrl = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$EmbedZip = Join-Path $CacheDir ("python-$PyVer-embed-amd64.zip")
$GetPip = Join-Path $CacheDir "get-pip.py"

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Write-Host "==> Ensure RapidOCR models exist..." -ForegroundColor Cyan
$ModelSrc = & python -c "import rapidocr, pathlib; print(pathlib.Path(rapidocr.__file__).parent / 'models')"
$onnxCount = @(Get-ChildItem $ModelSrc -Filter *.onnx -ErrorAction SilentlyContinue).Count
if ($onnxCount -lt 1) {
    & python -c "from rapidocr import RapidOCR, LangRec; RapidOCR(params={'Rec.lang_type': LangRec.CH})"
    $onnxCount = @(Get-ChildItem $ModelSrc -Filter *.onnx -ErrorAction SilentlyContinue).Count
}
if ($onnxCount -lt 1) { throw "RapidOCR models missing" }

if (Test-Path $Stage) {
    Write-Host ("==> Cleaning {0}" -f $Stage) -ForegroundColor Yellow
    Remove-Item -Recurse -Force $Stage
}
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

Write-Host "==> Download embeddable Python if needed..." -ForegroundColor Cyan
if (-not (Test-Path $EmbedZip)) {
    Write-Host ("  downloading {0}" -f $PyEmbedUrl)
    Invoke-WebRequest -Uri $PyEmbedUrl -OutFile $EmbedZip
}
if (-not (Test-Path $GetPip)) {
    Write-Host ("  downloading {0}" -f $GetPipUrl)
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPip
}

$PyDir = Join-Path $Stage "runtime"
New-Item -ItemType Directory -Force -Path $PyDir | Out-Null
Expand-Archive -Path $EmbedZip -DestinationPath $PyDir -Force

# Enable site-packages in embeddable Python
$Pth = Get-ChildItem $PyDir -Filter "python*._pth" | Select-Object -First 1
if (-not $Pth) { throw "python*._pth not found in embed package" }
$pthText = @(
    "python312.zip"
    "."
    ".."
    "Lib"
    "Lib\site-packages"
    "import site"
) -join "`r`n"
[System.IO.File]::WriteAllText($Pth.FullName, $pthText)

Write-Host "==> Bootstrap pip into embeddable Python..." -ForegroundColor Cyan
$PyExe = Join-Path $PyDir "python.exe"
& $PyExe $GetPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }

Write-Host "==> Download wheels with host Python..." -ForegroundColor Cyan
$WheelDir = Join-Path $Stage "_wheels_tmp"
New-Item -ItemType Directory -Force -Path $WheelDir | Out-Null
# Force cp312 wheels to match embeddable runtime
& python -m pip download -r (Join-Path $Root "requirements.txt") -d $WheelDir `
    --python-version 312 --only-binary=:all: --platform win_amd64 --implementation cp --abi cp312
if ($LASTEXITCODE -ne 0) {
    Write-Host "strict cp312 download failed, fallback to host pip download" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $WheelDir
    New-Item -ItemType Directory -Force -Path $WheelDir | Out-Null
    & python -m pip download -r (Join-Path $Root "requirements.txt") -d $WheelDir
    if ($LASTEXITCODE -ne 0) { throw "pip download failed" }
}

Write-Host "==> Install wheels into embeddable Python..." -ForegroundColor Cyan
& $PyExe -m pip install --no-index --find-links=$WheelDir -r (Join-Path $Root "requirements.txt") --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip install into embed failed" }
Remove-Item -Recurse -Force $WheelDir

Write-Host "==> Bundle tkinter (missing from embeddable Python)..." -ForegroundColor Cyan
$TkSrcCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"),
    "C:\Python312",
    "C:\Program Files\Python312"
) | Where-Object { $_ -and (Test-Path $_) }
$TkSrc = $TkSrcCandidates | Where-Object {
    (Test-Path (Join-Path $_ "Lib\tkinter")) -and (Test-Path (Join-Path $_ "DLLs\_tkinter.pyd")) -and (Test-Path (Join-Path $_ "tcl\tcl8.6"))
} | Select-Object -First 1
if (-not $TkSrc) {
    throw "Need a full python.org Python 3.12 install on the build machine to bundle tkinter."
}
Write-Host ("  from: {0}" -f $TkSrc)

# Ensure Lib is importable
$pthText = @(
    "python312.zip"
    "."
    ".."
    "Lib"
    "Lib\site-packages"
    "import site"
) -join "`r`n"
[System.IO.File]::WriteAllText($Pth.FullName, $pthText)

$tkLibDst = Join-Path $PyDir "Lib\tkinter"
New-Item -ItemType Directory -Force -Path (Join-Path $PyDir "Lib") | Out-Null
if (Test-Path $tkLibDst) { Remove-Item -Recurse -Force $tkLibDst }
Copy-Item -Recurse (Join-Path $TkSrc "Lib\tkinter") $tkLibDst

# Native deps must sit beside python.exe
foreach ($f in @("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll")) {
    Copy-Item -Force (Join-Path $TkSrc "DLLs\$f") $PyDir
}

$tclDst = Join-Path $PyDir "tcl"
New-Item -ItemType Directory -Force -Path $tclDst | Out-Null
foreach ($name in @("tcl8.6", "tk8.6", "tcl8")) {
    $src = Join-Path $TkSrc "tcl\$name"
    $dst = Join-Path $tclDst $name
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Recurse $src $dst
    Write-Host ("  + {0}" -f $name)
}

$env:TCL_LIBRARY = Join-Path $PyDir "tcl\tcl8.6"
$env:TK_LIBRARY = Join-Path $PyDir "tcl\tk8.6"
& $PyExe -c "import tkinter as tk; r=tk.Tk(); r.withdraw(); print('tkinter ok', tk.TkVersion); r.destroy()"
if ($LASTEXITCODE -ne 0) { throw "tkinter still not importable in green runtime" }

Write-Host "==> Copy application..." -ForegroundColor Cyan
Copy-Item (Join-Path $Root "main.py") $Stage
Copy-Item (Join-Path $Root "requirements.txt") $Stage
Copy-Item -Recurse (Join-Path $Root "pdf_table_extractor") (Join-Path $Stage "pdf_table_extractor")
Get-ChildItem (Join-Path $Stage "pdf_table_extractor") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$ModelsDst = Join-Path $Stage "models"
New-Item -ItemType Directory -Force -Path $ModelsDst | Out-Null
Copy-Item (Join-Path $ModelSrc "*.onnx") $ModelsDst -Force

$RunBat = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0
set RAPIDOCR_MODEL_DIR=%~dp0models
set DISABLE_MODEL_SOURCE_CHECK=True
set OC_DISABLE_DOT_ACCESS_WARNING=1
set TCL_LIBRARY=%~dp0runtime\tcl\tcl8.6
set TK_LIBRARY=%~dp0runtime\tcl\tk8.6
"%~dp0runtime\python.exe" main.py %*
if errorlevel 1 pause
"@
[System.IO.File]::WriteAllText((Join-Path $Stage "run.bat"), $RunBat)

$Usage = @"
扫描件 PDF 表格提取工具（绿色免安装版）

使用方法：
1. 解压到任意目录（路径不要过深）
2. 双击 run.bat
3. 选择 PDF，点击「开始提取」

说明：
- 无需安装 Python，无需联网
- 已内置 Python 3.12 运行时与 OCR 模型
- 结果保存为：PDF同目录\文件名_tables.db
- 建议 Windows 10/11 64 位，内存 4GB 及以上
"@
[System.IO.File]::WriteAllText((Join-Path $Stage "usage.txt"), $Usage, [System.Text.UTF8Encoding]::new($false))

Write-Host "==> Zip..." -ForegroundColor Cyan
$ZipPath = Join-Path $ReleaseDir ($PkgName + ".zip")
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Push-Location (Join-Path $Root "dist")
try { tar -a -cf $ZipPath $PkgName } finally { Pop-Location }

$folderMb = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
$zipMb = (Get-Item $ZipPath).Length / 1MB
Write-Host ""
Write-Host ("Done: {0}" -f $Stage) -ForegroundColor Green
Write-Host ("Folder MB: {0:N0}  Zip MB: {1:N0}" -f $folderMb, $zipMb) -ForegroundColor Green
Write-Host ("Zip path: {0}" -f $ZipPath) -ForegroundColor Green
Write-Host "Customer: unzip -> run.bat" -ForegroundColor Green
