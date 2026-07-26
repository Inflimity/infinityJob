#!/bin/bash
# Change to the directory where this script is located
cd "$(dirname "$0")"

# Activate the virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the main script
python main.py
