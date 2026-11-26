@echo off
cd /d "%~dp0"
if not exist "tools\build_indicators.exe" ( echo RUN BUILD_INDICATORS.bat FIRST & pause & exit /b 1 )
for %%S in (GBPUSD XAUUSD) do (
  if not exist "D:\BAZA\%%S\indicators" mkdir "D:\BAZA\%%S\indicators"
  tools\build_indicators.exe D:\BAZA\%%S D:\BAZA\%%S\indicators %%S
  if errorlevel 1 ( echo FAILED %%S & pause & exit /b 1 )
)
echo.
echo ALL INDICATORS OK
pause
