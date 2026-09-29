@echo off
setlocal
cd /d "%~dp0"
title Install Ameba Voice LED Control Packages

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
  goto :install
)

where py.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py.exe -3"
  goto :install
)

where python.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python.exe"
  goto :install
)

echo.
echo [ERROR] Python 3 was not found.
echo Close this window, reinstall Python with PATH enabled, and try again.
echo.
pause
exit /b 1

:install
echo Updating pip...
%PYTHON_EXE% -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo.
echo Installing required packages...
%PYTHON_EXE% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :failed

echo.
echo Verifying packages...
%PYTHON_EXE% -c "import serial, speech_recognition, pyttsx3, pyaudio; print('All required packages are ready.')"
if errorlevel 1 goto :failed

echo.
echo Installation completed successfully.
echo You can now run start.bat.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] Package installation failed. Keep this window open and copy the error message.
echo.
pause
exit /b 2
