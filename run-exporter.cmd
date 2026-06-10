@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-exporter.ps1" %*
echo.
