@echo off
rem Re-create the desktop shortcut from this folder. Run again after moving/renaming the folder.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$r=(Get-Location).Path; $d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d ('DWG'+[char]0x5206+[char]0x6790+'.lnk')));" ^
  "$s.TargetPath=Join-Path $r 'app.bat'; $s.WorkingDirectory=$r;" ^
  "$s.IconLocation=(Join-Path $r 'dwg_analysis.ico')+',0'; $s.WindowStyle=7; $s.Save();" ^
  "Write-Host ('Shortcut -> ' + $s.TargetPath)"
ie4uinit.exe -show >nul 2>&1
endlocal
