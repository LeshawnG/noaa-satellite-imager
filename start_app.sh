#!/bin/bash
cd "$(dirname "$0")"
source ./activate_venv.sh
echo "Starting Satellite Weather Imager..."
python3 app.py
