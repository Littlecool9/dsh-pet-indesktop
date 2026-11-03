@echo off
chcp 936 >nul
cd /d "%~dp0"
title SurfCore 安装程序
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo   没找到 Node.js。
  echo   请先安装 Node 22.13 或更高版本： https://nodejs.org/
  echo   装完请重新打开这个窗口，再双击本文件。
  echo.
  pause
  exit /b 1
)
node "%~dp0installer.mjs"
echo.
pause
