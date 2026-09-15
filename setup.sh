#!/bin/bash

# Surahs Chromecast Setup Script
# This script sets up the environment for the Quran Surahs Chromecast player

set -e  # Exit on error

echo "📖 Surahs Chromecast Setup"
echo "==========================="

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed."
    echo "Please install Python 3.8 or higher and try again."
    exit 1
fi

echo "✓ Found Python $(python3 --version)"

# Ask if user wants to use virtual environment
echo ""
read -p "Create a virtual environment? (recommended) [Y/n]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"

    echo "Activating virtual environment..."
    source venv/bin/activate
    echo "✓ Virtual environment activated"
fi

# Install requirements
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Configuration reminder
echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo "1. Edit config.json with your settings:"
echo "   - speaker_or_group_name: Your Chromecast device name(s)"
echo "   - surahs: one entry per surah, each with its own play_time and days"
echo ""
echo "2. Test it:"
echo "   python3 surahs.py --duration   # confirm audio durations"
echo "   python3 surahs.py --next       # confirm each surah's next scheduled run"
echo "   python3 surahs.py --test       # cast the first configured surah immediately"
echo "   python3 surahs.py --test Al-Baqarah   # cast a specific surah by name"
echo ""
echo "3. Run the scheduler:"
echo "   python3 surahs.py"
echo ""
echo "Note: If you created a virtual environment, activate it before running:"
echo "   source venv/bin/activate"
