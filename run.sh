#!/bin/bash
# run.sh — Single entry point for cron and manual runs.
# Called as: /path/to/run.sh >> /path/to/logs/analyzer.log 2>&1

cd /path/to/discord-analyzer
python3 main.py
