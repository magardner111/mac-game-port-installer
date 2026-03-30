#!/bin/bash
# Load user shell config so their PATH is available
[ -f "$HOME/.zshrc" ]   && source "$HOME/.zshrc"   2>/dev/null
[ -f "$HOME/.bashrc" ]  && source "$HOME/.bashrc"  2>/dev/null
[ -f "$HOME/.profile" ] && source "$HOME/.profile" 2>/dev/null

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PYTHON=$(command -v python3)
if [ -z "$PYTHON" ]; then
    osascript -e 'display dialog "Python 3 was not found.\n\nInstall it from python.org or via Homebrew:\n  brew install python3" buttons {"OK"} with icon stop'
    exit 1
fi

"$PYTHON" "$DIR/main.py"
