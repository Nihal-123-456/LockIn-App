@echo off
title LockIn - install requirements
echo.
echo Installing LockIn requirements (pystray + Pillow)...
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    py -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
) else (
    python -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
)
echo.
echo Done. You can now double-click LockIn.pyw to start LockIn.
echo.
pause
