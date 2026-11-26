@echo off
chcp 65001 >nul
setlocal
cd /d D:\AHexaTrader\XGBoost-edge-git || exit /b 1
echo.
echo --- new specs to draft rules
set "PYTHONUTF8=1"
set "PY=python"
python --version >nul 2>&1 || set "PY=py"
if not exist data_test mkdir data_test
set "GPP="
for /f "delims=" %%G in ('dir /b /s "D:\AHexaTrader\_COMPILER\g++.exe" 2^>nul') do if not defined GPP set "GPP=%%G"
if not defined GPP ( echo NO COMPILER & exit /b 1 )
for %%D in ("%GPP%") do set "PATH=%%~dpD;%PATH%"
"%GPP%" -O2 -std=c++17 -static -o data_test\draft_tester.exe registry\tester\tester.cpp
if errorlevel 1 ( echo COMPILE FAILED & exit /b 1 )
%PY% -u registry\spec_to_rule.py --tester data_test\draft_tester.exe
exit /b %errorlevel%
