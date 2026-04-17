#!/usr/bin/env bash
# launch.sh — Start all TUI-terminal processes in separate Git Bash (mintty) windows
# Usage: ./launch.sh  (from tui-terminal/ directory, or double-click in Explorer)

MINTTY="C:/Program Files/Git/usr/bin/mintty.exe"
BASH="C:/Program Files/Git/bin/bash.exe"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Launching TUI stack from: $DIR"

# Make runner scripts executable
chmod +x "$DIR/_run_ingester.sh" "$DIR/_run_tui.sh" "$DIR/_run_context.sh"

# Use empty title "" — Windows cmd.exe start requires this form.
# Named titles ("Ingester") get mistaken for the program name in Git Bash → "cannot find file".

# Window 1 — Rust ingester
start "" "$MINTTY" --title "Ingester" -e "$BASH" --login "$DIR/_run_ingester.sh"

# Window 2 — Python Textual TUI  (delayed 3s via runner script)
start "" "$MINTTY" --title "TUI" -e "$BASH" --login "$DIR/_run_tui.sh"

# Window 3 — Context engine (dry-run; edit _run_context.sh to remove --dry-run for live)
start "" "$MINTTY" --title "Context Engine" -e "$BASH" --login "$DIR/_run_context.sh"

echo "All 3 windows launched."
