@echo off
rem WorkHub 便携启动（Windows）：先切到仓库根目录，再用 python 起服务并打开浏览器。
rem 依赖 Python 3.10+；如果 python 不在 PATH，把下面这行改成解释器的绝对路径。
chcp 65001 >nul
cd /d "%~dp0.."
python -m workhub --open %*
if errorlevel 1 pause
