@echo off
REM Starts the Claude Code bridge on this machine.
REM Keep this window open while you use the web chat from another device.
cd /d "%~dp0.."
python "bridge\server.py"
pause
