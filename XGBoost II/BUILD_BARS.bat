@echo off
chcp 65001 >nul
set PYTHONUTF8=1
echo BUILD_BARS version 2
cd /d D:\AHexaTrader\XGBoost-edge-git
set PY=D:\Python314\python.exe
if not exist "%PY%" ( echo NO FILE %PY% & pause & exit /b 1 )
echo --- install pyarrow and numpy
"%PY%" -m pip install --quiet pyarrow numpy
if errorlevel 1 ( echo PIP FAILED & pause & exit /b 1 )
echo --- selftest of the aggregation
"%PY%" tools\build_bars.py --selftest
if errorlevel 1 ( echo SELFTEST FAILED & pause & exit /b 1 )
echo --- build bars from all parquet files
"%PY%" -u tools\build_bars.py D:\Tickstory\DATA\HF_EURUSD EURUSD D:\AHexaTrader\1DataFiles\bin\EURUSD > bars_log.txt 2>&1
type bars_log.txt
echo.
echo FINISHED
pause
