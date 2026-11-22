@echo off
REM Windows launcher. Usage:  run.bat setup   |   run.bat demo   |   run.bat evaluate
cd /d "%~dp0"

if exist ".venv\installed.ok" goto run

echo.
echo [setup] First run: creating a Python environment in .venv ...
if exist ".venv\Scripts\python.exe" goto install

REM Prefer a Python version that PyTorch supports (3.13 down to 3.10)
for %%V in (3.13 3.12 3.11 3.10) do (
    if not exist ".venv\Scripts\python.exe" (
        py -%%V -c "import sys" >nul 2>&1 && (
            echo [setup] Using Python %%V
            py -%%V -m venv .venv
        )
    )
)
if not exist ".venv\Scripts\python.exe" (
    python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERROR: Python 3.10, 3.11, 3.12 or 3.13 was not found.
    echo        Install Python 3.13 from https://www.python.org/downloads/windows/
    echo        and tick "Add python.exe to PATH" on the first installer screen.
    echo        Then close this window, open a new Command Prompt and run:  run.bat setup
    pause
    exit /b 1
)

:install
echo [setup] Installing packages (first time only, about 3-10 minutes) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: package installation failed. Check the internet connection and run the command again.
    echo        If it keeps failing, delete the .venv folder and try again.
    pause
    exit /b 1
)
echo ok> ".venv\installed.ok"
echo [setup] Packages installed.

:run
if "%~1"=="" (
    ".venv\Scripts\python.exe" run.py demo
) else (
    ".venv\Scripts\python.exe" run.py %*
)
