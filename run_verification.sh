#!/bin/bash
# Run Verification Service using its venv

cd "$(dirname "$0")/03_verification"
./venv/bin/python main.py
