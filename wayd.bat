@echo off
title WAYD - 在干嘛
cd /d "%~dp0"

REM 用 pythonw.exe 静默启动（无终端窗口）
start "" /B pythonw.exe src\main.py
exit
