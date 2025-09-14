@echo off
REM Audiobook CLI Automation Script
REM This script runs the audiobook pipeline with virtual environment

REM Change to project directory
cd /d "D:\Projects\pheonix\alpha\E3"
echo [%date% %time%] Changed to directory: %CD% >> logs/debug_batch.log

REM Activate virtual environment
echo [%date% %time%] Activating virtual environment...
call .venv\Scripts\activate
echo [%date% %time%] Virtual environment activated >> logs/debug_batch.log
echo [%date% %time%] Python executable: %VIRTUAL_ENV%\Scripts\python.exe >> logs/debug_batch.log

REM Check if activation was successful
if errorlevel 1 (
    echo [%date% %time%] ERROR: Failed to activate virtual environment
    exit /b 1
)

REM Run audiobook CLI and capture output
echo [%date% %time%] Starting audiobook CLI...
python audiobook_agent/audiobook_cli.py >> logs/test_batch_output.log

REM Log completion
echo [%date% %time%] Audiobook CLI run completed with exit code %ERRORLEVEL%

REM Deactivate virtual environment
deactivate