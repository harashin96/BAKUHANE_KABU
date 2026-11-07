"""チャレンジャー(本番と並走させる候補モデル)を学習して models/challengers/<名前>.pkl に保存(手元のPCで、月1回くらい)

    python scripts/26_train_challenger.py            # jpstocks/challenger.py の SPECS をすべて
    python scripts/26_train_challenger.py M1_ens5    # 名前を指定

決算短信(J-Quants)は全期間が要るので、手元の C:\\Projects\\JP_STOCKS\\data\\jquants を使う(CI には3年分しかない)。
モデルのファイルには決算短信のデータそのものは入らない(木の分かれ目の値だけ)。
"""
import sys
import time

import _bootstrap  # noqa: F401

from jpstocks import challenger as C
from jpstocks import jquants as J
from jpstocks.config import setup_logging
from jpstocks.data import load_prices, load_universe
from jpstocks.jump import build_world

log = setup_logging("challenger")
t0 = time.time()
names = sys.argv[1:] or list(C.SPECS)
w = build_world(load_prices(), load_universe(), since="2016-10-01")
fins = J.load("fins") if any(C.SPECS[n][1] for n in names) else None
log.info(f"特徴量を作成 ({time.time()-t0:.0f}秒)")
for n in names:
    b = C.train(n, w, fins)
    C.save(b)
    log.info(f"保存: models/challengers/{n}.pkl  サンプル {b['n_samples']:,}  〜{b['trained_until']}  特徴量 {len(b['cols'])}  ({time.time()-t0:.0f}秒)")
