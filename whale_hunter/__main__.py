"""Run everything with one command: collector/detector loop + dashboard.

    .venv/bin/python -m whale_hunter          # dashboard at http://localhost:8050
"""
import logging
import os
import threading

from . import main, web

if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # keep the terminal for alerts
    port = int(os.environ.get("WHALE_PORT", 8050))
    threading.Thread(target=web.serve, args=(port,), daemon=True).start()
    print(f"Dashboard: http://localhost:{port}   (Ctrl-C stops everything)")
    try:
        main.main()
    except KeyboardInterrupt:
        pass
