"""決算短信の数字(J-Quants の /v2/fins/summary)から、業績回復の特徴量を作る(日付 × 銘柄、開示日以降だけ)

- rev_up    : 会社予想(今期の営業利益)の上方修正。前回の開示より5%以上の引き上げ。開示から60営業日
- guide_up  : 会社予想の増益。今期の営業利益の予想が、前期の実績より10%以上多い(次の開示まで)
- guide_turn: 増益予想への転換。前期は減益(前々期より営業利益が減った)で、今期は増益の予想
- q_turn    : 四半期の増益転換。今期の累計営業利益が前年同期より増え、前回の開示(前の四半期)では前年同期より減っていた
決算短信は決算発表の当日に出るので、有価証券報告書(1〜2か月後)より早く分かる。開示が取引時間中・引け後でも、買うのは翌営業日の寄り付きなので先読みにはならない。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LABELS = {"rev_up": "上方修正", "guide_up": "増益予想", "guide_turn": "増益予想に転換", "q_turn": "四半期の増益転換"}


def tidy_fins(raw: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame({"date": pd.to_datetime(raw["DiscDate"]), "time": raw["DiscTime"].astype(str), "code": raw["Code"].astype(str).str[:4],
                      "doc": raw["DocType"].astype(str), "per": raw["CurPerType"].astype(str),
                      "fy_st": pd.to_datetime(raw["CurFYSt"], errors="coerce"), "fy_en": pd.to_datetime(raw["CurFYEn"], errors="coerce")})
    for c in ["OP", "Sales", "NP", "FOP", "NxFOP"]:
        f[c] = pd.to_numeric(raw[c].replace({"": np.nan, "None": np.nan, "nan": np.nan}), errors="coerce") if c in raw else np.nan
    f = f.dropna(subset=["date", "fy_en"])
    return f.sort_values(["code", "date", "time"]).reset_index(drop=True)


def disclosure_features(f: pd.DataFrame) -> pd.DataFrame:
    """開示ごとの特徴量。使う書類: 決算短信(FinancialStatements)と、通期の業績予想の修正(EarnForecastRevision で期間が FY)。
    REIT と配当予想の修正、第2四半期までの予想の修正は使わない"""
    stmt = f["doc"].str.contains("FinancialStatements")
    rev = (f["doc"] == "EarnForecastRevision") & (f["per"] == "FY")
    f = f[(stmt | rev) & ~f["doc"].str.contains("REIT")].copy()
    f["stmt"] = f["doc"].str.contains("FinancialStatements")
    act = f[f["stmt"] & (f["per"] == "FY")].dropna(subset=["OP"]).drop_duplicates(["code", "fy_en"], keep="last")[["code", "fy_en", "OP"]] \
        .sort_values("fy_en").rename(columns={"fy_en": "k", "OP": "a"})

    def actual(codes, when) -> np.ndarray:
        """その決算期(when)の通期の営業利益の実績。決算期のずれ(変則決算)を吸収するため ±40日で探す。
        実績は開示の時点で分かっている前期以前のものだけを引く(when は開示している期より前)"""
        q = pd.DataFrame({"code": codes.to_numpy(), "k": pd.to_datetime(when).to_numpy(), "i": np.arange(len(codes))}).dropna(subset=["k"]).sort_values("k")
        m = pd.merge_asof(q, act, on="k", by="code", direction="nearest", tolerance=pd.Timedelta(days=40))
        out = np.full(len(codes), np.nan)
        out[m["i"].to_numpy()] = m["a"].to_numpy()
        return out

    one = pd.DateOffset(years=1)
    # 今期の会社予想: FY の書類は「来期の予想」(NxFOP)、それ以外は「今期の予想」(FOP)
    is_fy = f["stmt"] & (f["per"] == "FY")
    f["target_fy"] = np.where(is_fy, f["fy_en"] + one, f["fy_en"])
    f["target_fy"] = pd.to_datetime(f["target_fy"])
    f["fc"] = np.where(is_fy, f["NxFOP"], f["FOP"])
    f = f.reset_index(drop=True)
    f["prev_act"] = actual(f["code"], f["target_fy"] - one)
    f["prev2_act"] = actual(f["code"], f["target_fy"] - one - one)
    f["fc_g"] = ((f["fc"] - f["prev_act"]) / f["prev_act"].abs()).where(f["prev_act"].abs() > 0).clip(-3, 3)
    f["guide_up"] = (f["fc_g"] >= 0.10).astype(float).where(f["fc_g"].notna())
    f["guide_turn"] = ((f["fc_g"] > 0) & (f["prev_act"] < f["prev2_act"])).astype(float).where(f["fc_g"].notna() & f["prev2_act"].notna())
    # 上方修正: 同じ決算期の予想が、前回の開示より5%以上引き上げられた
    f["prev_fc"] = f.groupby(["code", "target_fy"])["fc"].shift(1)
    f["rev_up"] = ((f["fc"] >= f["prev_fc"] * 1.05) & (f["prev_fc"] > 0)).astype(float)
    # 四半期(累計)の前年同期比
    q = f[f["stmt"]].dropna(subset=["OP"]).drop_duplicates(["code", "fy_en", "per"], keep="last")
    py = q[["code", "per", "fy_en", "OP"]].assign(fy_en=q["fy_en"] + one).rename(columns={"OP": "OP_py"})   # 前年同期の累計
    q = q.merge(py.drop_duplicates(["code", "per", "fy_en"]), on=["code", "per", "fy_en"], how="left")
    q["q_yoy"] = ((q["OP"] - q["OP_py"]) / q["OP_py"].abs()).where(q["OP_py"].abs() > 0).clip(-3, 3)
    q = q.sort_values(["code", "date"])
    q["q_turn"] = ((q["q_yoy"] > 0) & (q.groupby("code")["q_yoy"].shift(1) < 0)).astype(float).where(q["q_yoy"].notna())
    f = f.merge(q[["code", "date", "per", "fy_en", "q_yoy", "q_turn"]], on=["code", "date", "per", "fy_en"], how="left")
    return f


def _daily(d: pd.DataFrame, col: str, dates, codes, max_age: int) -> pd.DataFrame:
    d = d.dropna(subset=[col])
    pos = dates.searchsorted(d["date"].to_numpy())
    ok = pos < len(dates)
    d = d[ok].assign(avail=dates[pos[ok]])
    p = d.drop_duplicates(["avail", "code"], keep="last").pivot(index="avail", columns="code", values=col)
    return p.reindex(index=dates, columns=codes).ffill(limit=max_age)


def earnings_panels(raw: pd.DataFrame, dates: pd.DatetimeIndex, codes) -> dict[str, pd.DataFrame]:
    f = disclosure_features(tidy_fins(raw))
    out = {c: _daily(f, c, dates, codes, 70) for c in ["guide_up", "guide_turn", "q_turn", "fc_g", "q_yoy"]}
    ev = f[f["rev_up"] == 1]
    out["rev_up"] = _daily(ev.assign(v=1.0), "v", dates, codes, 60).fillna(0)
    return out


GUIDE_DAYS = 1200   # 毎日の候補で使う決算短信の期間(前期・前々期の実績を引くため約3年分)


def latest_guide(raw: pd.DataFrame, asof, codes) -> pd.DataFrame:
    """毎日の候補用: 各銘柄の直近の会社予想(asof の日までに開示されたもの、100日以内)
    列: fc_g(今期の営業利益の予想 ÷ 前期の実績 − 1)、guide_up、guide_turn、guide(どちらか)、disc(開示日)、fc、prev_act"""
    cols = ["fc_g", "guide_up", "guide_turn", "guide", "disc", "fc", "prev_act"]
    if raw is None or not len(raw):
        return pd.DataFrame(columns=cols)
    f = disclosure_features(tidy_fins(raw))
    asof = pd.Timestamp(asof)
    f = f[(f["date"] <= asof) & (f["date"] > asof - pd.Timedelta(days=100)) & f["fc_g"].notna()]
    f = f.sort_values(["date", "time"]).drop_duplicates("code", keep="last").set_index("code")
    out = pd.DataFrame({"fc_g": f["fc_g"], "guide_up": f["guide_up"], "guide_turn": f["guide_turn"], "disc": f["date"],
                        "fc": f["fc"], "prev_act": f["prev_act"]})
    out["guide"] = (out["guide_up"] == 1) | (out["guide_turn"] == 1)
    return out.reindex(pd.Index([str(c) for c in codes]))[cols]
