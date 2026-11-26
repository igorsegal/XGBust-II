@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set PY=D:\Python314\python.exe
if not exist "%PY%" ( echo NO FILE %PY% & pause & exit /b 1 )
"%PY%" -c "import numpy, pyarrow" >nul 2>nul
if errorlevel 1 "%PY%" -m pip install --quiet numpy pyarrow
set "GPP="
for /f "delims=" %%G in ('dir /b /s "D:\AHexaTrader\_COMPILER\g++.exe" 2^>nul') do if not defined GPP set "GPP=%%G"
if not defined GPP ( echo NO COMPILER IN D:\AHexaTrader\_COMPILER & pause & exit /b 1 )
"%PY%" -u tools\build_2020.py
if errorlevel 1 ( echo. & echo STOPPED & pause & exit /b 1 )
for %%D in ("%GPP%") do set "PATH=%%~dpD;%PATH%"
echo compile...
"%GPP%" -O2 -std=c++17 -static -o tools\build_indicators.exe tools\build_indicators.cpp
if errorlevel 1 ( echo COMPILE FAILED & pause & exit /b 1 )
for %%S in (EURUSD GBPUSD USDJPY AUDUSD XAUUSD) do (
  if not exist "D:\AHexaTrader\1DataFiles\BAZA\%%S\indicators" mkdir "D:\AHexaTrader\1DataFiles\BAZA\%%S\indicators"
  tools\build_indicators.exe D:\AHexaTrader\1DataFiles\BAZA\%%S D:\AHexaTrader\1DataFiles\BAZA\%%S\indicators %%S
  if errorlevel 1 ( echo FAILED %%S & pause & exit /b 1 )
)
echo.
echo ALL 2020 OK
pause
