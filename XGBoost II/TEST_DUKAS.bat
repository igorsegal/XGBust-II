@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
D:\Python314\python.exe -u tools\test_dukas.py
echo.
pause
