@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\project.ps1" -Action start
if errorlevel 1 pause
