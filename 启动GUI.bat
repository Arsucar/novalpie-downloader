@echo off
cd /d "%~dp0"

:: 设置 PYTHONPATH 指向 src 目录，使 novalpie 模块可被找到
set PYTHONPATH=%cd%\src;%PYTHONPATH%

python -m novalpie.gui
if errorlevel 1 (
    echo.
    echo 启动失败，请检查 Python 和依赖
    pause
)
