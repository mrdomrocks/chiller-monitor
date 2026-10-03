@echo off
title Chiller Monitor
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONNOUSERSITE=1
set CHILLER_INSTALLED=1
set CHILLER_OPEN_BROWSER=1
"%~dp0python\python.exe" -m app
echo.
echo Chiller Monitor stopped.
pause
