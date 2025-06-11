#!/bin/bash

# Exit on error
set -e

echo "Starting OpenManus UI Server..."

# Activate the virtual environment created by setup.sh
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment 'venv' not found. Please run ./scripts/setup.sh first."
    exit 1
fi

source venv/bin/activate || {
    echo "Failed to activate virtual environment. Please check your setup."
    exit 1
}

# Start the UI server using the activated virtual environment's python
python -c "from app.ui.server import OpenManusUI; server = OpenManusUI(); server.run()"

# Keep the terminal open to see logs
read -p "Press Enter to exit..."

# Deactivate virtual environment on exit
deactivate
