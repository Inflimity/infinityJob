@echo off
echo ========================================
echo   Starting Chrome for ginNews X Scraper
echo ========================================
echo.
echo DO NOT CLOSE THIS WINDOW while ginNews is running!
echo.

:: Kill any existing Chrome first
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 2 >nul

:: Start Chrome with remote debugging enabled
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

echo Chrome started with remote debugging on port 9222.
echo.
echo NEXT STEPS:
echo   1. Log into X (twitter) in the Chrome window that just opened
echo   2. Open a NEW Command Prompt
echo   3. Run: cd C:\Users\Administrator\Desktop\GGGINNEWS\ginNews
echo   4. Run: .venv\Scripts\activate
echo   5. Run: python main.py
echo.
pause
