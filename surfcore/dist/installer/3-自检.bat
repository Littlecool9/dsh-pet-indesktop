@echo off
chcp 936 >nul
cd /d "%~dp0"
title SurfCore вт╪Л
node "%~dp0doctor.mjs"
echo.
pause
