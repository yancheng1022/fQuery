@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  离线安装依赖
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 64 位 Python，并加入 PATH。
  pause
  exit /b 1
)

echo 当前 Python:
python --version
echo.
if exist PYTHON_VERSION.txt (
  echo 本包要求的 Python 版本:
  type PYTHON_VERSION.txt
  echo.
)

echo 正在从本地 wheels 安装，请稍候...
python -m pip install --no-index --find-links=wheels -r requirements.txt
if errorlevel 1 (
  echo.
  echo [失败] 依赖安装失败。请核对 Python 版本是否与 PYTHON_VERSION.txt 一致。
  pause
  exit /b 1
)

echo.
echo [完成] 依赖已安装。可双击「启动.bat」运行。
pause
