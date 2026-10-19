#!/bin/bash
# Double-click in Finder to start Whale Hunter and open the dashboard.
# Close this Terminal window (or press Ctrl-C) to stop it.
cd "$(dirname "$0")" || exit 1
python3 start.py || { echo "Press Return to close."; read -r; }
