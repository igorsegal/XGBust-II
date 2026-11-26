@echo off
chcp 65001 >nul
echo GITHUB_PUSH version 9
cd /d D:\AHexaTrader\XGBoost-edge-git
if errorlevel 1 ( echo NO PROJECT FOLDER & pause & exit /b 1 )
where git >nul 2>nul
if errorlevel 1 ( echo NO GIT IN PATH & pause & exit /b 1 )
git ls-files --error-unmatch dashscope_key.txt >nul 2>nul
if not errorlevel 1 ( echo STOP: dashscope_key.txt is tracked by git, key must not go to GitHub & pause & exit /b 1 )
git reset -q
git ls-files --error-unmatch openrouter_key.txt >nul 2>nul
if not errorlevel 1 ( echo STOP: openrouter_key.txt is tracked by git, key must not go to GitHub & pause & exit /b 1 )
echo --- jury check by golden set
set "PY=python"
python --version >nul 2>&1 || set "PY=py"
set "JURY=src/jury.py"
%PY% -m src.golden --check
if errorlevel 1 set "JURY="
if not defined JURY echo WARNING: new jury.py did not pass the golden set, it is NOT sent, GitHub keeps the old one
echo --- add programs and documents
git add -- .gitignore .github/workflows/scrape-and-judge.yml AGENTS.md GITHUB_PUSH.bat CONVEYOR.bat %JURY% src/golden.py data/golden tests/test_jury.py tests/test_spec_to_rule.py registry tools/build_2020.py tools/build_baza.py tools/build_ev.py tools/build_indicators.cpp .github/workflows/cloud_tests.yml src/scraper.py tests/test_scraper_mock.py
if errorlevel 1 ( echo ADD FAILED, nothing sent & pause & exit /b 1 )
git diff --cached --name-only | findstr /i /r /c:"dashscope" /c:"_key\.txt" /c:"\.bin" /c:"\.exe" /c:"\.parquet" /c:"\.zip" /c:"\.pyc"
if not errorlevel 1 ( git reset -q & echo STOP: bad file in set, nothing sent & pause & exit /b 1 )
echo --- what will be sent
git --no-pager diff --cached --name-status
git diff --cached --quiet
if not errorlevel 1 goto pull
git commit -q -m "Jury with golden gate, OpenRouter option, spec to rule loop"
if errorlevel 1 ( echo COMMIT FAILED, nothing sent & pause & exit /b 1 )
:pull
echo --- pull
git pull --rebase --autostash
if errorlevel 1 ( echo PULL FAILED, nothing pushed & pause & exit /b 1 )
echo --- push
git push
if errorlevel 1 ( echo PUSH FAILED & pause & exit /b 1 )
echo.
echo PUSH OK
if exist CONVEYOR.bat call CONVEYOR.bat
pause
