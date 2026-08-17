@echo off
rem QueryForge 启动脚本 — 服务控制台日志统一写入 logs\server.log
rem 用法：双击运行，或在终端执行 start_server.bat
cd /d %~dp0

if not exist logs mkdir logs
echo [%date% %time%] 启动 QueryForge (venv) ...
.venv\Scripts\python.exe main.py >> logs\server.log 2>&1
