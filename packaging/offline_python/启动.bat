@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DISABLE_MODEL_SOURCE_CHECK=True
set PADDLE_PDX_CACHE_HOME=%~dp0.paddlex
python main.py
if errorlevel 1 pause
