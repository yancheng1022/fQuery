@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DISABLE_MODEL_SOURCE_CHECK=True
set RAPIDOCR_MODEL_DIR=%~dp0models
python main.py
if errorlevel 1 pause
