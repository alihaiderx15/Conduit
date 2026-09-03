@echo off
setlocal
cd /d "%~dp0"

echo ==============================================================
echo CONDUIT SAFE SETUP LAUNCHER
echo ==============================================================
echo.

REM Never launch setup.py with .venv\Scripts\python.exe here.
REM A corrupted venv can fail before setup.py gets a chance to repair itself.

where py >nul 2>nul
if %errorlevel%==0 (
    py setup.py
    goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python setup.py
    goto :done
)

echo [FAILED] No system Python launcher was found.
echo Install Python 3.13 or Python 3.14 first, then run this file again.
exit /b 1

:done
if not %errorlevel%==0 (
    echo.
    echo Conduit setup failed. See the error above.
    exit /b %errorlevel%
)

echo.
echo Conduit setup finished successfully.
echo Start Conduit with:
echo     py main.py
exit /b 0
