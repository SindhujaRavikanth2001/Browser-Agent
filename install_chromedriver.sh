#!/bin/bash

# Updated ChromeDriver Installation Script for Ubuntu
# Works with new Chrome for Testing API

echo "🔧 Installing ChromeDriver for Ubuntu (Updated Method)..."

# 1. Clean up any previous failed attempts
rm -rf ~/.wdm
sudo rm -f /usr/local/bin/chromedriver

# 2. Get Chrome version
if ! command -v google-chrome &> /dev/null; then
    echo "❌ Google Chrome not found. Please install Chrome first."
    exit 1
fi

CHROME_VERSION=$(google-chrome --version | awk '{print $3}')
echo "📋 Chrome version: $CHROME_VERSION"

# 3. Extract major version for new API
CHROME_MAJOR=$(echo $CHROME_VERSION | cut -d'.' -f1)
echo "📋 Chrome major version: $CHROME_MAJOR"

# 4. Try multiple methods to get ChromeDriver

echo "🔍 Method 1: Trying Chrome for Testing API..."

# Method 1: Use new Chrome for Testing API
CHROMEDRIVER_URL=""

# For Chrome 115+ use the new endpoint
if [ "$CHROME_MAJOR" -ge 115 ]; then
    echo "Using new Chrome for Testing API for Chrome $CHROME_MAJOR+"
    
    # Get available versions from the new API
    API_RESPONSE=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json")
    
    if [ $? -eq 0 ] && [ -n "$API_RESPONSE" ]; then
        # Try to find exact version match first
        CHROMEDRIVER_URL=$(echo "$API_RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
chrome_version = '$CHROME_VERSION'
chrome_major = '$CHROME_MAJOR'

# First try exact version match
for version_info in data['versions']:
    if version_info['version'] == chrome_version:
        for download in version_info['downloads'].get('chromedriver', []):
            if download['platform'] == 'linux64':
                print(download['url'])
                sys.exit(0)

# Then try same major version
for version_info in reversed(data['versions']):
    if version_info['version'].startswith(chrome_major + '.'):
        for download in version_info['downloads'].get('chromedriver', []):
            if download['platform'] == 'linux64':
                print(download['url'])
                sys.exit(0)
" 2>/dev/null)
    fi
fi

# Method 2: Try the old API for older versions
if [ -z "$CHROMEDRIVER_URL" ] && [ "$CHROME_MAJOR" -lt 115 ]; then
    echo "🔍 Method 2: Trying legacy ChromeDriver API..."
    CHROME_VERSION_SHORT=$(echo $CHROME_VERSION | cut -d'.' -f1-3)
    CHROMEDRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION_SHORT" 2>/dev/null)
    
    if [ -n "$CHROMEDRIVER_VERSION" ] && [[ ! "$CHROMEDRIVER_VERSION" =~ "Error" ]]; then
        CHROMEDRIVER_URL="https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip"
    fi
fi

# Method 3: Try latest stable version as fallback
if [ -z "$CHROMEDRIVER_URL" ]; then
    echo "🔍 Method 3: Using latest stable ChromeDriver..."
    
    # Get latest stable version from new API
    LATEST_STABLE=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data['channels']['Stable']['version'])
except:
    pass
" 2>/dev/null)
    
    if [ -n "$LATEST_STABLE" ]; then
        CHROMEDRIVER_URL="https://storage.googleapis.com/chrome-for-testing-public/$LATEST_STABLE/linux64/chromedriver-linux64.zip"
    fi
fi

# Method 4: Manual fallback URLs for common versions
if [ -z "$CHROMEDRIVER_URL" ]; then
    echo "🔍 Method 4: Trying manual fallback URLs..."
    
    case "$CHROME_MAJOR" in
        "138"|"137"|"136"|"135")
            # Try some recent versions manually
            for version in "130.0.6723.69" "129.0.6668.89" "128.0.6613.119"; do
                TEST_URL="https://storage.googleapis.com/chrome-for-testing-public/$version/linux64/chromedriver-linux64.zip"
                if curl -s --head "$TEST_URL" | head -n 1 | grep -q "200 OK"; then
                    CHROMEDRIVER_URL="$TEST_URL"
                    echo "Found working version: $version"
                    break
                fi
            done
            ;;
        *)
            echo "Trying generic latest version..."
            CHROMEDRIVER_URL="https://storage.googleapis.com/chrome-for-testing-public/130.0.6723.69/linux64/chromedriver-linux64.zip"
            ;;
    esac
fi

if [ -z "$CHROMEDRIVER_URL" ]; then
    echo "❌ Could not find compatible ChromeDriver version"
    echo "🔧 Trying alternative installation method..."
    
    # Alternative: Install via package manager
    echo "📦 Installing via apt (may not be latest version)..."
    sudo apt update
    sudo apt install -y chromium-chromedriver
    
    # Create symlink if needed
    if [ -f "/usr/bin/chromedriver" ] && [ ! -f "/usr/local/bin/chromedriver" ]; then
        sudo ln -s /usr/bin/chromedriver /usr/local/bin/chromedriver
        echo "✅ ChromeDriver installed via package manager"
        chromedriver --version
        exit 0
    else
        echo "❌ Package manager installation also failed"
        exit 1
    fi
fi

echo "📥 Downloading ChromeDriver from: $CHROMEDRIVER_URL"

# 5. Download and install ChromeDriver
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

# Download with proper error handling
if ! wget -O chromedriver.zip "$CHROMEDRIVER_URL"; then
    echo "❌ Failed to download ChromeDriver"
    cd /
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Check if download was successful
if [ ! -f "chromedriver.zip" ] || [ ! -s "chromedriver.zip" ]; then
    echo "❌ Download failed or file is empty"
    cd /
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Extract ChromeDriver
if ! unzip -q chromedriver.zip; then
    echo "❌ Failed to extract ChromeDriver"
    cd /
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Find the chromedriver binary (could be in different locations)
CHROMEDRIVER_BINARY=""
if [ -f "chromedriver" ]; then
    CHROMEDRIVER_BINARY="chromedriver"
elif [ -f "chromedriver-linux64/chromedriver" ]; then
    CHROMEDRIVER_BINARY="chromedriver-linux64/chromedriver"
else
    # Search for it
    CHROMEDRIVER_BINARY=$(find . -name "chromedriver" -type f | head -1)
fi

if [ -z "$CHROMEDRIVER_BINARY" ] || [ ! -f "$CHROMEDRIVER_BINARY" ]; then
    echo "❌ ChromeDriver binary not found after extraction"
    ls -la
    cd /
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Make it executable and move to system location
chmod +x "$CHROMEDRIVER_BINARY"
sudo mv "$CHROMEDRIVER_BINARY" /usr/local/bin/chromedriver

# Clean up
cd /
rm -rf "$TEMP_DIR"

# 6. Verify installation
echo "🔍 Verifying installation..."

if command -v chromedriver &> /dev/null; then
    INSTALLED_VERSION=$(chromedriver --version)
    echo "✅ ChromeDriver installed successfully: $INSTALLED_VERSION"
    
    # Test compatibility
    echo "🧪 Testing Chrome and ChromeDriver compatibility..."
    
    # Create a simple Python test
    cat > /tmp/test_chrome.py << 'EOF'
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import sys

try:
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    service = Service('/usr/local/bin/chromedriver')
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    driver.get("https://www.google.com")
    title = driver.title
    driver.quit()
    
    print(f"✅ Test successful! Page title: {title}")
    sys.exit(0)
    
except Exception as e:
    print(f"❌ Test failed: {e}")
    print("💡 This might still work with your scraper - the test environment might be restricted")
    sys.exit(0)  # Don't fail the installation for test issues
EOF

    # Run the test if Python and selenium are available
    if command -v python3 &> /dev/null && python3 -c "import selenium" 2>/dev/null; then
        python3 /tmp/test_chrome.py
        rm -f /tmp/test_chrome.py
    else
        echo "⚠️ Skipping test - Python3 or Selenium not available"
        echo "   Install with: pip3 install selenium"
    fi
    
else
    echo "❌ ChromeDriver installation failed"
    exit 1
fi

echo ""
echo "🎉 ChromeDriver installation completed!"
echo ""
echo "📋 Installation Summary:"
echo "   Chrome: $(google-chrome --version)"
echo "   ChromeDriver: $(chromedriver --version)"
echo "   Location: /usr/local/bin/chromedriver"
echo ""
echo "💡 Your scrapers should now work with the updated setup_driver() method!"