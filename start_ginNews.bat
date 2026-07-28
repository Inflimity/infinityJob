@echo off
cd /d "%~dp0"

REM Check if the Windows virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found for Windows. Creating one now...
    python -m venv .venv
    
    echo Activating environment and installing requirements...
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
    
    echo Installing Playwright browsers...
    playwright install chromium
) else (
    call .venv\Scripts\activate.bat
)

REM Run the main script
python main.py

REM Pause so the window doesn't immediately close if there's an error
pause
