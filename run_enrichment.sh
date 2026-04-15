#!/bin/bash
# Run Enrichment Service using its venv

cd "$(dirname "$0")/02_enrichment"
./venv/bin/python main.py
