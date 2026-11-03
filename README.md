# 爆ハネ期待値ランキング(日本株)

平日の夕方に GitHub Actions が自動で実行され、結果を GitHub Pages で公開します。

- 並び順: 期待スコア = 3か月後のリターンが全対象銘柄の中で何番目くらいになるかの予測(2026-11 から。以前は「爆ハネ確率−暴落確率」)
- 絞り込み: 週1回、このPCの Claude Code(スケジュール実行)がランキング上位10銘柄を調べて A/B/C を付ける(`research/weekly_prompt.md` → `research/qualitative.csv`)。A を優先、C は外す
- 買い時: ランキングに新しく入った日 → 翌営業日の寄り付き / 売り時: 約3か月(63営業日)保有、損切り目安 -20%(任意)
- データ: 株価 yfinance(リポジトリには保存しない)、財務 EDINET API(提出日以降のみ使用)
- 検証(2019〜2026年、walk-forward): 毎日の上位5銘柄の3か月リターンは全銘柄平均より +2.6%、上がっていた割合 58%、-30%以下 3%。投資判断はご自身で。

## 最初の設定(1回だけ)
1. Settings → Secrets and variables → Actions → New repository secret
   - Name: `EDINET_API_KEY` / Secret: EDINETのAPIキー
2. Settings → Pages → Build and deployment → Source を **GitHub Actions** にする
3. Actions タブ → 「爆ハネランキング」→ **Run workflow**(初回は予測モデルの学習も行うので 20〜40分)

公開URL: `https://<ユーザー名>.github.io/<リポジトリ名>/`

## 自動で行うこと
- 平日 16:00(日本時間)ごろ: 株価・EDINETを更新 → ランキング作成 → Webページ更新
- 平日の場中(9:30・11:00・13:00・14:30ごろ): ランキングはそのままで、株価と「ランクイン後」の騰落率だけ更新(live.yml)
- 毎月第1月曜: 銘柄一覧・株式分割の履歴を更新し、予測モデルを学習し直す
- 手動で学習し直す: Run workflow で「予測モデルを学習し直す」にチェック
