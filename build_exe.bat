@echo off
title LockIn - build standalone exe (optional)
echo.
echo OPTIONAL: builds a single LockIn.exe with PyInstaller.
echo You do not need this to use LockIn - run install_requirements.bat instead.
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    set "PY=python"
)
%PY% -m pip install --disable-pip-version-check pyinstaller
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name LockIn --icon "%~dp0app.ico" --paths "%~dp0" "%~dp0LockIn.pyw"
echo.
if exist dist\LockIn.exe (
    echo Success! Created dist\LockIn.exe
) else (
    echo Build failed - see the messages above.
)
echo.
pause
