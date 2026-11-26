@echo off
cd /d "%~dp0"
git ls-files --error-unmatch dashscope_key.txt >nul 2>nul
if not errorlevel 1 (
echo STOP: dashscope_key.txt is tracked by git, key must not go to GitHub
goto failed
)
copy /Y workflows_new\build_quotes.yml .github\workflows\build_quotes.yml
if errorlevel 1 goto failed
set FILES=.github/workflows/build_quotes.yml workflows_new/build_quotes.yml src/build_quotes.py PUSH_QUOTES.bat
git add %FILES%
if errorlevel 1 goto failed
git diff --cached --quiet -- %FILES%
if not errorlevel 1 goto push
git commit -m "Build EURUSD quotes database in GitHub Actions" -- %FILES%
if errorlevel 1 goto failed
:push
git pull --rebase --autostash
if errorlevel 1 goto failed
git push
if errorlevel 1 goto failed
echo.
echo PUSH OK
pause
exit /b 0
:failed
echo.
echo PUSH FAILED
pause
exit /b 1
