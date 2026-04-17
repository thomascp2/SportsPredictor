#!/usr/bin/env bash
# Kill all FreePicks TUI processes
echo "Killing ingester..."
taskkill //F //IM ingester.exe 2>/dev/null && echo "  ingester stopped" || echo "  ingester not running"

echo "Killing TUI (textual python)..."
# Kill python processes running app.py or context_engine.py
wmic process where "commandline like '%app.py%'" delete 2>/dev/null
wmic process where "commandline like '%context_engine%'" delete 2>/dev/null

# Fallback: kill all mintty windows spawned by launch.sh
taskkill //F //FI "WINDOWTITLE eq Ingester" 2>/dev/null
taskkill //F //FI "WINDOWTITLE eq TUI" 2>/dev/null
taskkill //F //FI "WINDOWTITLE eq Context Engine" 2>/dev/null

echo "Done."
