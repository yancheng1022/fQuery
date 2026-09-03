@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  Offline dependency install
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found. Install 64-bit Python and add it to PATH.
  pause
  exit /b 1
)

echo Current Python:
python --version
echo.
if exist PYTHON_VERSION.txt (
  echo Required Python version:
  type PYTHON_VERSION.txt
  echo.
)

echo Installing from local wheels, please wait...
python -m pip install --no-index --find-links=wheels -r requirements.txt
if errorlevel 1 (
  echo.
  echo [FAILED] Check PYTHON_VERSION.txt and use matching 64-bit Python.
  pause
  exit /b 1
)

echo.
echo [OK] Dependencies installed. Double-click run.bat to start.
pause
