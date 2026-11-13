@echo off
setlocal
rem Double-click to start Margin and open it in your browser.
rem Close this window (or press Ctrl+C) to stop the app.

cd /d "%~dp0"
set "URL=http://127.0.0.1:5050"
set "PY=.venv\Scripts\python.exe"

rem Already running? Just open it.
curl -s -o NUL "%URL%" >nul 2>nul
if not errorlevel 1 (
    echo Margin is already running at %URL%
    start "" "%URL%"
    exit /b 0
)

rem Reuse the virtual environment if its dependencies are installed; otherwise set it up.
if exist "%PY%" "%PY%" -c "import flask, requests, bleach, dotenv" >nul 2>nul
if exist "%PY%" if not errorlevel 1 goto ready

echo First run: creating a virtual environment and installing dependencies...
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto setupfailed
"%PY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto setupfailed

:ready
if not exist ".env" if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo Created .env. To connect Canvas, open it in Notepad, add your Canvas address and token, then restart.
    echo The demo works without it.
    echo.
)

rem Open the browser once the server answers.
start "" /b powershell -NoProfile -Command "for ($i = 0; $i -lt 40; $i++) { try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%URL%' | Out-Null; Start-Process '%URL%'; break } catch { Start-Sleep -Milliseconds 250 } }"

echo Starting Margin at %URL% -- close this window or press Ctrl+C to stop.
"%PY%" app.py
if errorlevel 1 pause
exit /b 0

:setupfailed
echo.
echo Setup failed. Install Python 3.12 or newer from python.org, then try again.
pause
exit /b 1
