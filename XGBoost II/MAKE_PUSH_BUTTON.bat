@echo off
if not exist D:\AHexaTrader\XGBoost-edge-git\GITHUB_PUSH.bat ( echo NO GITHUB_PUSH.bat & pause & exit /b 1 )
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $d 'GitHub PUSH.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($p); $s.TargetPath=$env:ComSpec; $s.Arguments='/c D:\AHexaTrader\XGBoost-edge-git\GITHUB_PUSH.bat'; $s.WorkingDirectory='D:\AHexaTrader\XGBoost-edge-git'; $s.IconLocation='D:\AHexaTrader\XGBoost-edge-git\PUSH_BUTTON.ico,0'; $s.Save(); if(-not (Test-Path -LiteralPath $p)){exit 1}"
if errorlevel 1 ( echo BUTTON NOT CREATED & pause & exit /b 1 )
echo.
echo BUTTON CREATED ON DESKTOP
pause
