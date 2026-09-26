#!/usr/bin/env bash
# Run Latent Studio from source on macOS or Linux.
# (On macOS you can also double-click "Launch Latent.command".)
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Latent Studio needs Python 3.9 or newer: https://www.python.org/downloads/"
  exit 1
fi
if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
  echo "Python is missing Tk support."
  echo "  Debian/Ubuntu: sudo apt install python3-tk"
  echo "  Fedora:        sudo dnf install python3-tkinter"
  echo "  macOS:         use the installer from python.org (includes Tk)"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Latent Studio. This takes a minute..."
  "$PY" -m venv .venv
fi
if ! .venv/bin/python -c 'import cv2, numpy, PIL' >/dev/null 2>&1; then
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
fi
exec .venv/bin/python -m latent "$@"
