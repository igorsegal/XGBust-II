@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set PY=D:\Python314\python.exe
if not exist "%PY%" ( echo NO PYTHON %PY% & pause & exit /b 1 )
set "GPP="
for /f "delims=" %%G in ('dir /b /s "D:\AHexaTrader\_COMPILER\g++.exe" 2^>nul') do if not defined GPP set "GPP=%%G"
if not defined GPP ( echo NO COMPILER IN D:\AHexaTrader\_COMPILER & pause & exit /b 1 )
for %%D in ("%GPP%") do set "PATH=%%~dpD;%PATH%"
set BARS=D:\AHexaTrader\1DataFiles\BAZA\EURUSD\EURUSD_H1.bin
echo [1/5] compile tester...
"%GPP%" -O2 -std=c++17 -static -o tester\tester.exe tester\tester.cpp
if errorlevel 1 ( echo COMPILE FAILED & pause & exit /b 1 )
echo [2/5] validate registry...
"%PY%" validate_registry.py
if errorlevel 1 ( echo REGISTRY INVALID & pause & exit /b 1 )
echo [3/5] check indicators against independent Python...
"%PY%" tests\xcheck_indicators.py tester\tester.exe %BARS%
if errorlevel 1 ( echo INDICATOR CHECK FAILED & pause & exit /b 1 )
"%PY%" tests\xcheck_indicators2.py tester\tester.exe %BARS%
if errorlevel 1 ( echo INDICATOR CHECK 2 FAILED & pause & exit /b 1 )
for %%P in (EURUSD GBPUSD USDJPY) do (
  "%PY%" tests\xcheck_london.py tester\tester.exe configs\london_trap_%%P_M5.json
  if errorlevel 1 ( echo LONDON TRAP CHECK FAILED %%P & pause & exit /b 1 )
)
for %%P in (EURUSD GBPUSD USDJPY) do (
  "%PY%" tests\xcheck_classic.py tester\tester.exe configs\classic_trace_%%P_M5.json
  if errorlevel 1 ( echo CLASSIC TRACE CHECK FAILED %%P & pause & exit /b 1 )
)
for %%P in (EURUSD GBPUSD USDJPY) do (
  "%PY%" tests\xcheck_ny.py tester\tester.exe configs\ny_continuation_%%P_M5.json
  if errorlevel 1 ( echo NY CONTINUATION CHECK FAILED %%P & pause & exit /b 1 )
)
echo [4/5] run all configs, development windows only...
for %%f in (configs\*.json) do (
  echo ===== %%f
  tester\tester.exe "%%f" --selftest
  if errorlevel 1 ( echo TEST FAILED %%f & pause & exit /b 1 )
)
echo [5/5] record results into registry...
"%PY%" record_results.py
if errorlevel 1 ( echo RECORD FAILED & pause & exit /b 1 )
echo.
echo DONE
pause
