@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto :novenv
start "" .venv\Scripts\pythonw.exe app.py
exit /b 0

:novenv
rem Launched from a shortcut the console is hidden, so report the problem in a dialog ("|" = line break).
set "MSG=Python environment (.venv) not found in:|%CD%||Setup:|python -m venv .venv|.venv\Scripts\pip install -r requirements.txt"
powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [void][Windows.MessageBox]::Show($env:MSG.Replace('|',[string][char]10), 'SCADA DWG Analyzer', 'OK', 'Error')"
exit /b 2
