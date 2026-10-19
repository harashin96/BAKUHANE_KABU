# 爆ハネ期待値ランキング(日本株)

平日の夕方に GitHub Actions が自動で実行され、結果を GitHub Pages で公開します。

- 並び順: 「3か月以内に+30%以上(爆ハネ)の確率」−「3か月以内に-30%以下(暴落)の確率」
- 買い時: ランキングに新しく入った日 → 翌営業日の寄り付き / 売り時: 約3か月(63営業日)保有、損切り目安 -20%(任意)
- データ: 株価 yfinance(リポジトリには保存しない)、財務 EDINET API(提出日以降のみ使用)
- 検証(2019〜2025年): 上位20銘柄の3か月リターンは全銘柄平均より約+2.8%。1銘柄ずつでは中央値+1%程度、3〜4銘柄に1つが大きく跳ねる分布。投資判断はご自身で。

## 最初の設定(1回だけ)
1. Settings → Secrets and variables → Actions → New repository secret
   - Name: `EDINET_API_KEY` / Secret: EDINETのAPIキー
2. Settings → Pages → Build and deployment → Source を **GitHub Actions** にする
3. Actions タブ → 「爆ハネランキング」→ **Run workflow**(初回は予測モデルの学習も行うので 20〜40分)

公開URL: `https://<ユーザー名>.github.io/<リポジトリ名>/`

## 自動で行うこと
- 平日 18:30(日本時間)ごろ: 株価・EDINETを更新 → ランキング作成 → Webページ更新
- 毎月第1月曜: 銘柄一覧・株式分割の履歴を更新し、予測モデルを学習し直す
- 手動で学習し直す: Run workflow で「予測モデルを学習し直す」にチェック
