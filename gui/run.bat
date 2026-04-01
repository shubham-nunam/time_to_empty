@echo off
REM Quick start script for Battery Simulation GUI

echo.
echo 4 Starting Battery Behavior Simulator...
echo.

REM Check if we're in the right directory
if not exist "gui\app.py" (
    echo Error: Please run this script from the project root directory
    exit /b 1
)

REM Check if streamlit is installed
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installing Streamlit and dependencies...
    pip install -r gui\requirements.txt
)

echo Opening GUI at http://localhost:8501
echo Press Ctrl+C to stop the server
echo.

python -m streamlit run gui\app.py
