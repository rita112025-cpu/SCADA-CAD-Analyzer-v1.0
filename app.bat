@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title SCADA DWG Analyzer

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python.exe"
)

echo SCADA DWG Analyzer is starting...
echo Python: %PYTHON_EXE%
echo.
"%PYTHON_EXE%" app.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] app exited normally. Exit code: 0
) else (
  echo.
  echo [ERROR] app exited with an error. Exit code: %EXIT_CODE%
)
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
