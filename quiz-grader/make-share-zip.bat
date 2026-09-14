@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0make_share_zip.py"
) else (
    python "%~dp0make_share_zip.py"
)
if errorlevel 1 (
    echo.
    echo ZIP creation failed. Install Python 3 if it is not available.
    pause
    exit /b 1
)
echo.
echo The sharing ZIP is in the dist folder next to this batch file.
pause
