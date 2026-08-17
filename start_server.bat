@echo off
rem QueryForge 启动脚本 — 服务日志由应用统一写入 logs\（app/server/sqlalchemy 等，自动轮转）
rem 用法：双击运行，或在终端执行 start_server.bat
cd /d %~dp0

if not exist logs mkdir logs
echo [%date% %time%] 启动 QueryForge (venv) ...
echo 日志目录: %~dp0logs
.venv\Scripts\python.exe main.py
