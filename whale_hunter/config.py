import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    with open(path or ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["db_path"] = os.environ.get("WHALE_DB") or str(ROOT / cfg["db_path"])
    return cfg
