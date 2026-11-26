@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set PY=D:\Python314\python.exe
if not exist "%PY%" ( echo NO FILE %PY% & pause & exit /b 1 )
"%PY%" -u tools\scan_folder.py "D:\AHexaTrader\1DataFiles"
echo.
echo FINISHED
pause
