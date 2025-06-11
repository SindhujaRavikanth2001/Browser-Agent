#!/bin/bash

# Exit on error
set -e

# Ensure curl is installed
if ! command -v curl &> /dev/null; then
    echo "curl not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y curl
fi

# Install Node.js v20 and npm if not already present or if the installed version is too old
if ! command -v node &> /dev/null || ! node -v | grep -q 'v20'; then
    echo "Node.js v20 not found or not the correct version. Installing/Upgrading..."
    
    # Clean up any previous Node.js related apt configurations
    sudo apt-get purge -y nodejs npm 2>/dev/null || true # Purge if exists, ignore errors
    sudo rm -f /etc/apt/sources.list.d/nodesource.list
    sudo rm -f /etc/apt/keyrings/nodesource.gpg

    # Use the official NodeSource setup script for Node.js 20.x
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    
    # Install nodejs (which includes npm)
    sudo apt-get install -y nodejs
    
    echo "Node.js version: $(node -v)"
    echo "npm version: $(npm -v)"
fi

# Navigate to the frontend directory
cd frontend/fw-manus-ui

# Start the development server
echo "Starting React development server..."

# Install dependencies if not already done
npm install

# Start the development server
npm run dev
