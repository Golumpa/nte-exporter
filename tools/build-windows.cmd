@echo off
setlocal

cd /d "%~dp0\.."

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    python -m venv .venv
    if errorlevel 1 exit /b %errorlevel%
)

"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b %errorlevel%

"%PYTHON%" -m pip install -e ".[build]"
if errorlevel 1 exit /b %errorlevel%

"%PYTHON%" -m PyInstaller --clean --noconfirm "packaging\NTE History Exporter.spec"
if errorlevel 1 (
    echo PyInstaller failed.
    exit /b %errorlevel%
)

set "EXE=%CD%\dist\nte-history-exporter.exe"
if not exist "%EXE%" (
    echo Expected build output was not created: %EXE%
    exit /b 1
)

echo Built %EXE%
"%EXE%" --help
if errorlevel 1 (
    echo Built executable smoke test failed.
    exit /b %errorlevel%
)
