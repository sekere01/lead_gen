#!/bin/bash
# Run Discovery Service using its venv

cd "$(dirname "$0")/01_discovery"
./venv/bin/python main.py
