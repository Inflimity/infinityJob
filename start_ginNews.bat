@echo off
cd /d "%~dp0"

REM Activate the virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Run the main script
python main.py

REM Pause so the window doesn't immediately close if there's an error
pause
