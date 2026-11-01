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

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_startup.ps1"
if errorlevel 1 goto startupfailed

echo.
echo Soundroom is installed and will start when you sign in to Windows.
echo Use start.bat to run it now in a visible console.
pause
exit /b 0

:startupfailed
echo Soundroom dependencies were installed, but Windows could not register startup.
echo Run install.bat again from your Windows account or create the task in Task Scheduler.
pause
exit /b 1

:failed
echo Setup could not finish. Check your Python installation and internet connection, then retry.
pause
exit /b 1
