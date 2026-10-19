"""STEP 1: JPXの東証上場銘柄一覧から、対象銘柄のリストを作る
(settings.yaml の data.markets / data.sizes で絞り込み。初期設定は TOPIX500 + Small 1 の約1,000銘柄)

    python scripts/01_fetch_universe.py
"""
import _bootstrap  # noqa: F401

from jpstocks.config import load_config, setup_logging
from jpstocks.data import fetch_universe

setup_logging("fetch")
cfg = load_config()
df = fetch_universe(cfg["data"]["markets"], cfg["data"].get("sizes"))
print(df.groupby(["market", "size"]).size().to_string())
print(f"\n合計 {len(df)} 銘柄")
