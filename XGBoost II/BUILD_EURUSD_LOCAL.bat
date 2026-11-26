@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set PY=D:\Python314\python.exe
if not exist "%PY%" ( echo NO FILE %PY% & pause & exit /b 1 )
"%PY%" -c "import numpy, pyarrow" >nul 2>nul
if errorlevel 1 "%PY%" -m pip install --quiet numpy pyarrow
"%PY%" -u tools\local_eurusd.py
echo.
echo FINISHED
pause
