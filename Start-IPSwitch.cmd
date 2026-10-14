@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-IPSwitch.ps1" -CreateDesktopShortcut
if errorlevel 1 pause
