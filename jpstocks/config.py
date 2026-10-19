"""設定とパス"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load_config(path=None) -> dict:
    import os
    with open(path or ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if os.environ.get("JP_DATA_START"):          # クラウドでは取得期間を短くする(例: 2015-01-01)
        cfg["data"]["start"] = os.environ["JP_DATA_START"]
    if os.environ.get("JP_PUBLISH_DIR") is not None and "report" in cfg:
        cfg["report"]["publish_dir"] = os.environ["JP_PUBLISH_DIR"]
    return cfg


def setup_logging(name: str) -> logging.Logger:
    (ROOT / "logs").mkdir(exist_ok=True)
    lg = logging.getLogger("jpstocks")
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        for h in (logging.StreamHandler(), logging.FileHandler(ROOT / "logs" / f"{name}.log", encoding="utf-8")):
            h.setFormatter(fmt)
            lg.addHandler(h)
    return lg
