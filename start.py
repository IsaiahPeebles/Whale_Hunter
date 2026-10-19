#!/usr/bin/env python3
"""One-command setup + launch. Works on macOS, Linux and Windows with only Python 3.9+ installed.

    python3 start.py              # set up (first run only), start everything, open the dashboard
    python3 start.py --check      # set up and run the tests, then exit (good first step for AI agents)
    python3 start.py --no-browser # start without opening a browser tab
    python3 start.py --port 8060  # use a different port (default 8050)
"""
import argparse
import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"  # reinstall only when requirements.txt changes


def setup():
    if sys.version_info < (3, 9):
        sys.exit(f"Python 3.9+ is required (found {sys.version.split()[0]}).")
    if not PY.exists():
        print("First run: creating a Python environment in .venv …")
        venv.create(VENV, with_pip=True)
    digest = hashlib.sha256(REQS.read_bytes()).hexdigest()
    if not STAMP.exists() or STAMP.read_text() != digest:
        print("Installing dependencies …")
        subprocess.run([str(PY), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                        "-r", str(REQS)], check=True)
        STAMP.write_text(digest)


def port_busy(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_when_ready(url):
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1)
            webbrowser.open(url)
            return
        except OSError:
            time.sleep(1)
    print("Dashboard did not answer within 60s — see messages above.")


def main():
    ap = argparse.ArgumentParser(description="Set up and run Whale Hunter.")
    ap.add_argument("--check", action="store_true", help="set up and run tests, then exit")
    ap.add_argument("--no-browser", action="store_true", help="don't open the dashboard in a browser")
    ap.add_argument("--port", type=int, default=8050)
    args = ap.parse_args()

    os.chdir(ROOT)
    setup()
    if args.check:
        sys.exit(subprocess.run([str(PY), "-m", "pytest", "-q", "tests"]).returncode)

    url = f"http://localhost:{args.port}"
    if port_busy(args.port):
        sys.exit(f"Port {args.port} is already in use (Whale Hunter may already be running at {url}).\n"
                 f"Stop it first, or pick another port: python3 start.py --port {args.port + 10}")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    env = {**os.environ, "WHALE_PORT": str(args.port)}
    try:
        sys.exit(subprocess.run([str(PY), "-m", "whale_hunter"], env=env).returncode)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
