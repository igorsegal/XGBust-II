@echo off
cd /d "%~dp0"
set "GPP="
for /f "delims=" %%G in ('dir /b /s "D:\AHexaTrader\_COMPILER\g++.exe" 2^>nul') do if not defined GPP set "GPP=%%G"
if not defined GPP ( echo NO COMPILER IN D:\AHexaTrader\_COMPILER & pause & exit /b 1 )
for %%D in ("%GPP%") do set "PATH=%%~dpD;%PATH%"
echo compiler: %GPP%
if not exist "D:\EURUSD\EURUSD_M1.bin" ( echo NO QUOTES D:\EURUSD & pause & exit /b 1 )
echo compile...
"%GPP%" -O2 -std=c++17 -static -o tools\build_indicators.exe tools\build_indicators.cpp
if errorlevel 1 ( echo COMPILE FAILED & pause & exit /b 1 )
if not exist "D:\EURUSD\indicators" mkdir "D:\EURUSD\indicators"
echo calculate...
tools\build_indicators.exe D:\EURUSD D:\EURUSD\indicators
pause
