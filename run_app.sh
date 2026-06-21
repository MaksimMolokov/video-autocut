#!/bin/bash
# Launch the AI Video Producer UI
# Usage: ./run_app.sh [--legacy]

set -e
cd "$(dirname "$0")"

if [[ "$1" == "--legacy" ]]; then
    echo "Launching legacy UI (src/gui.py)..."
    streamlit run src/gui.py --server.port 8501
else
    echo "Launching AI Video Producer (frontend/app.py)..."
    streamlit run frontend/app.py --server.port 8502 \
        --server.fileWatcherType none \
        --theme.base dark \
        --theme.backgroundColor "#0B0F12" \
        --theme.secondaryBackgroundColor "#12171D" \
        --theme.textColor "#E8EDF2" \
        --theme.primaryColor "#00FF88"
fi
