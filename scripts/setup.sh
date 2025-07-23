#!/bin/bash

# Exit on error
set -e

echo "Setting up the environment..."

# Install required system packages
echo "Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    software-properties-common \
    git \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libxcursor1 \
    libgtk-3-0 \
    libcairo-gobject2 \
    libgdk-pixbuf-2.0-0

# Install Python 3.11
echo "Installing Python 3.11..."
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# Remove existing venv if it exists
if [ -d "venv" ]; then
    echo "Removing existing virtual environment..."
    rm -rf venv
fi

# Create virtual environment with Python 3.11
echo "Creating virtual environment with Python 3.11..."
python3.11 -m venv venv || {
    echo "Failed to create virtual environment with Python 3.11"
    exit 1
}

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate || {
    echo "Failed to activate virtual environment"
    exit 1
}

# Verify Python version
echo "Python version:"
python --version

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright browsers and dependencies
echo "Installing Playwright browsers and dependencies..."
playwright install
playwright install-deps

# Add the project root to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Set ownership of /mnt/data/browseragent_llm to current user
echo "Creating and setting ownership of /mnt/data/browseragent_llm..."
sudo mkdir -p /mnt/data/browseragent_llm
sudo chown -R $(whoami):$(whoami) /mnt/data/browseragent_llm

# Set HF_HOME environment variable for model downloads
export HF_HOME="/mnt/data/browseragent_llm"

# Download models   
echo "Downloading models..."
python scripts/download_models.py

echo "Setup completed successfully!" 