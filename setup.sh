#!/bin/bash

# Kahf Chromecast Setup Script
# This script sets up the environment for the Surah Al-Kahf Chromecast player

set -e  # Exit on error

echo "📖 Surah Al-Kahf Chromecast Setup"
echo "=================================="

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
echo "   - play_time: 24h HH:MM, when to play daily"
echo "   - days: 0=Mon..6=Sun, which days to play on"
echo ""
echo "2. Test it:"
echo "   python3 kahf.py --duration   # confirm the audio duration"
echo "   python3 kahf.py --next       # confirm the next scheduled run"
echo "   python3 kahf.py --test       # cast immediately"
echo ""
echo "3. Run the scheduler:"
echo "   python3 kahf.py"
echo ""
echo "Note: If you created a virtual environment, activate it before running:"
echo "   source venv/bin/activate"
