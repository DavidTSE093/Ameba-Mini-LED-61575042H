@echo off
setlocal
cd /d "%~dp0"
title Ameba Voice LED Control

rem Prefer the project virtual environment.
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
  goto :run
)

where py.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py.exe -3"
  goto :run
)

where python.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python.exe"
  goto :run
)

echo.
echo [ERROR] Python 3 was not found.
echo.
echo Install Python 3 from:
echo https://www.python.org/downloads/windows/
echo Select "Add python.exe to PATH" during installation.
echo Then close this window and run start.bat again.
echo.
pause
exit /b 1

:run
echo Checking the Python environment...
%PYTHON_EXE% -c "import serial, speech_recognition, pyttsx3, pyaudio" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Python is installed, but required packages are missing.
  echo Double-click install_packages.bat in this folder.
  echo Or open PowerShell in this folder and run:
  echo.
  echo   python -m pip install -r requirements.txt
  echo.
  echo Or, when using the Python launcher, run:
  echo   py -3 -m pip install -r requirements.txt
  echo.
  pause
  exit /b 2
)

echo Starting Ameba Voice LED Control...
%PYTHON_EXE% "%~dp0voice_control.py"
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" (
  echo.
  echo [ERROR] The application stopped with exit code %APP_EXIT%.
  pause
)
exit /b %APP_EXIT%
