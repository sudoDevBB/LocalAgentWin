@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it from python.org, then run install.bat again.
  echo During setup, enable the Python launcher option.
  pause
  exit /b 1
)

py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install a supported Python version and retry.
  pause
  exit /b 1
)

py -3 -m venv .venv
if errorlevel 1 goto failed
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto failed
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Soundroom dependencies are ready. Use start.bat to run the local server.
pause
exit /b 0

:failed
echo Setup could not finish. Check your Python installation and internet connection, then retry.
pause
exit /b 1
