"""1回だけ: 2026-11-07_ensemble.py の予測のキャッシュ(data/wf_jq_3m_ens.parquet)から、検証台の最初の案を作る"""
import lab
import pandas as pd

E = pd.read_parquet(lab.DATA / "wf_jq_3m_ens.parquet")
lab.PRED.mkdir(parents=True, exist_ok=True)
for m in ["M0", "M1"]:
    s = [f"{m}_s{i}" for i in range(10)]
    for name, v in [(f"{m}_s0", E[f"{m}_s0"]), (f"{m}_ens5", E[s[:5]].mean(axis=1)), (f"{m}_ens10", E[s].mean(axis=1)), (f"{m}_noES", E[f"{m}_noES"])]:
        E[["code", "date"]].assign(score=v.to_numpy()).to_parquet(lab.PRED / f"{name}.parquet")
D = {"M0_ens10": "本番と同じ特徴量、乱数10通りの平均(比べる相手 REF)", "M0_s0": "今の本番(乱数0のモデル1つ)",
     "M0_ens5": "本番と同じ特徴量、乱数5通りの平均", "M0_noES": "本番と同じ特徴量、early stopping なし",
     "M1_ens10": "M0 + 決算短信の特徴量8個、乱数10通りの平均", "M1_ens5": "M0 + 決算短信、乱数5通りの平均(並走中のチャレンジャー)",
     "M1_s0": "M0 + 決算短信、乱数0のモデル1つ", "M1_noES": "M0 + 決算短信、early stopping なし"}
for kind in ["final", "top5"]:
    for name, d in D.items():
        r = lab.record(name, d, kind)
        print(kind, name, round(r["3か月%"], 2), r.get("REFとの差%"), r.get("差のt"), r.get("上回った年"))
