#!/bin/bash
# Quick start script for Battery Simulation GUI

echo "🔋 Starting Battery Behavior Simulator..."
echo ""

# Check if we're in the right directory
if [ ! -f "gui/app.py" ]; then
    echo "Error: Please run this script from the project root directory"
    exit 1
fi

# Check if streamlit is installed
if ! python -c "import streamlit" 2>/dev/null; then
    echo "Installing Streamlit and dependencies..."
    pip install -r gui/requirements.txt
fi

echo "Opening GUI at http://localhost:8501"
echo "Press Ctrl+C to stop the server"
echo ""

python -m streamlit run gui/app.py
