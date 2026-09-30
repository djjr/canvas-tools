#!/bin/zsh
# Double-click in Finder to start Margin and open it in your browser.
# Close this Terminal window (or press Control-C) to stop the app.

cd "${0:A:h}" || exit 1
URL=http://127.0.0.1:5050

# Already running? Just open it.
if curl -s -o /dev/null "$URL"; then
  echo "Margin is already running at $URL"
  open "$URL"
  exit 0
fi

# Use the existing virtual environment (here or one level up), or create one.
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
elif [[ -x ../.venv/bin/python ]]; then
  PY=../.venv/bin/python
else
  echo "First run: creating a virtual environment and installing dependencies…"
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt || {
    echo "Setup failed. Install Python 3.12 or newer, then try again."
    read -k1 "?Press any key to close."
    exit 1
  }
  PY=.venv/bin/python
fi

# Open the browser once the server answers.
( for i in {1..40}; do curl -s -o /dev/null "$URL" && { open "$URL"; break; }; sleep 0.25; done ) &

echo "Starting Margin at $URL — close this window or press Control-C to stop."
"$PY" app.py
