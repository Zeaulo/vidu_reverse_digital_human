@echo off
rem Set UTF-8 console encoding and use the script's own directory.
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0test\start_studio.ps1"
if errorlevel 1 pause
