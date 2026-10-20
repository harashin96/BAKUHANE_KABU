"""マイページ(メールアドレス+パスワードでログインし、保有銘柄・お気に入りを保存)

- データの保存先: Firebase(Authentication + Firestore)。設定は config/firebase_config.json
  {"apiKey": "...", "authDomain": "...", "projectId": "...", "appId": "..."}
  (この値は公開されても問題ない種類のもの。データは Firestore のルールで「本人だけ読み書き可」にする)
- 株価・順位などは、毎日のレポート作成時に書き出す stocks.json(全銘柄)から表示する
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import ROOT

FIREBASE_CONFIG = ROOT / "config" / "firebase_config.json"
FIELDS = ["name", "sector", "price", "rank", "p_jump", "p_crash", "PER", "PBR", "DY", "NCR", "RET1M", "HI52"]


def load_firebase_config() -> dict | None:
    try:
        cfg = json.loads(FIREBASE_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return None
    return cfg if cfg.get("apiKey") and cfg.get("projectId") else None


def stocks_json(today: pd.DataFrame, w, market: dict | None) -> str:
    """全銘柄の最新データ(ランキング外の銘柄も、株価と1か月の騰落は出す)"""
    d = pd.Timestamp(today["date"].iloc[0])
    uni = w.universe.set_index(w.universe["code"].astype(str))
    close = w.m.close.loc[:d].iloc[-5:].ffill().iloc[-1]
    adj = w.m.adj_close.loc[:d]
    ret1m = (adj.iloc[-1] / adj.iloc[-22] - 1) * 100 if len(adj) > 22 else pd.Series(dtype=float)
    hi52 = adj.iloc[-1] / adj.iloc[-252:].max() * 100
    rank = pd.Series(np.arange(1, len(today) + 1), index=today.index)

    def num(x, nd=2):
        return None if x is None or pd.isna(x) or np.isinf(x) else round(float(x), nd)

    out = {}
    for code in close.dropna().index:
        code = str(code)
        r = today.loc[code] if code in today.index else None
        out[code] = [
            str(uni["name"].get(code, "")) if code in uni.index else "",
            str(uni["sector33"].get(code, "")) if code in uni.index else "",
            num(close.get(code), 1),
            int(rank[code]) if code in rank.index else None,
            num(r["p_jump"], 3) if r is not None else None,
            num(r["p_crash"], 3) if r is not None else None,
            num(r["PER"], 1) if r is not None else None,
            num(r["PBR"], 2) if r is not None else None,
            num(r["DY"], 2) if r is not None else None,
            num(r["NCR"], 2) if r is not None else None,
            num(ret1m.get(code), 1),
            num(hi52.get(code), 0),
        ]
    return json.dumps({"date": str(d.date()), "fields": FIELDS, "n_ranked": len(today),
                       "market": market["level"] if market else None, "stocks": out}, ensure_ascii=False, separators=(",", ":"))


MYPAGE_HTML = """
<section class="pane" id="tab-mypage">
  <div id="mp-login" class="note"></div>
  <div id="mp-body" style="display:none">
    <h2>保有銘柄</h2>
    <div class="mp-form">
      <input id="h-code" placeholder="コード(例 7203)" size="10">
      <input id="h-date" type="date">
      <input id="h-price" type="number" step="any" placeholder="買値(円)" style="width:110px">
      <input id="h-shares" type="number" step="1" placeholder="株数" style="width:90px">
      <button class="btn" id="h-add">追加</button>
    </div>
    <div class="wrap" id="h-table"></div>
    <h2>お気に入り</h2>
    <div class="mp-form">
      <input id="f-code" placeholder="コード(例 6758)" size="10">
      <button class="btn" id="f-add">追加</button>
      <span class="note">各ランキングの ☆ を押しても追加できます</span>
    </div>
    <div class="wrap" id="f-table"></div>
  </div>
</section>
"""

MYPAGE_JS = r"""
<script type="module">
const FB = __FB_CONFIG__;
const H = __H__, STOP = __STOP__;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let S = null, state = {holdings: [], favorites: []}, user = null, save = async () => {};
try { S = await (await fetch('stocks.json', {cache: 'no-store'})).json(); } catch (e) {}
const get = (code) => {
  if (!S || !S.stocks[code]) return null;
  const o = {}; S.fields.forEach((f, i) => o[f] = S.stocks[code][i]); return o;
};
const fmt = (v, d = 1, suf = '') => (v === null || v === undefined || isNaN(v)) ? '−' : Number(v).toLocaleString('ja-JP', {minimumFractionDigits: d, maximumFractionDigits: d}) + suf;
const links = (c) => `<a href="https://nikkeiyosoku.com/stock/${esc(c)}/" target="_blank">${esc(c)}</a><a class="yb" href="https://finance.yahoo.co.jp/quote/${esc(c)}.T" target="_blank">Y!</a>`;
function addBdays(dstr, n) { const d = new Date(dstr + 'T00:00:00'); let k = 0; while (k < n) { d.setDate(d.getDate() + 1); if (d.getDay() % 6 !== 0) k++; } return d; }
function bdaysBetween(a, b) { let n = 0; const d = new Date(a); while (d < b) { d.setDate(d.getDate() + 1); if (d.getDay() % 6 !== 0) n++; } return n; }
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function render() {
  const today = S ? new Date(S.date + 'T00:00:00') : new Date();
  // 保有
  let rows = state.holdings.map((h, i) => {
    const s = get(h.code) || {}; const cur = s.price;
    const pl = cur ? cur / h.price - 1 : null;
    const due = addBdays(h.date, H); const left = bdaysBetween(today, due);
    let verdict = `保有継続(あと${left}営業日)`;
    if (pl !== null && pl <= STOP) verdict = '<span class="sell">損切りライン到達</span>';
    else if (today >= due) verdict = '<span class="sell">3か月経過: 売り時</span>';
    const yen = (pl !== null && h.shares) ? (cur - h.price) * h.shares : null;
    return `<tr><td>${links(h.code)}</td><td class="name">${esc(s.name || '?')}<div class="sec">${esc(s.sector || '')}</div></td>
      <td>${esc(h.date)}</td><td class="num">${fmt(h.price, 0)}</td><td class="num">${fmt(h.shares, 0)}</td><td class="num">${fmt(cur, 0)}</td>
      <td class="num ${pl >= 0 ? 'buy' : 'sell'}">${fmt(pl === null ? null : pl * 100, 1, '%')}</td><td class="num">${fmt(yen, 0, '円')}</td>
      <td>${iso(due)}</td><td class="num">${fmt(h.price * (1 + STOP), 0)}</td><td class="num">${s.rank ?? '圏外'}</td>
      <td class="num">${fmt(s.p_jump === null || s.p_jump === undefined ? null : s.p_jump * 100, 0, '%')}</td>
      <td class="num">${fmt(s.p_crash === null || s.p_crash === undefined ? null : s.p_crash * 100, 0, '%')}</td>
      <td>${verdict}</td><td><button class="del" data-h="${i}">削除</button></td></tr>`;
  }).join('');
  const tot = state.holdings.reduce((a, h) => { const s = get(h.code); if (s && s.price && h.shares) { a.cost += h.price * h.shares; a.val += s.price * h.shares; } return a; }, {cost: 0, val: 0});
  $('h-table').innerHTML = state.holdings.length ? `<table><tr><th>コード</th><th>銘柄</th><th>買った日</th><th>買値</th><th>株数</th><th>現在値</th><th>損益</th><th>損益(円)</th><th>売り時の目安</th><th>損切り目安</th><th>順位</th><th>爆ハネ確率</th><th>暴落確率</th><th>判定</th><th></th></tr>${rows}</table>`
    + (tot.cost ? `<p class="note">合計: 買値 ${fmt(tot.cost, 0, '円')} → 評価額 ${fmt(tot.val, 0, '円')}(${fmt((tot.val / tot.cost - 1) * 100, 1, '%')})</p>` : '')
    : '<p class="note">まだ登録がありません。</p>';
  // お気に入り
  rows = state.favorites.map((c, i) => {
    const s = get(c) || {};
    return `<tr><td>${links(c)}</td><td class="name">${esc(s.name || '?')}<div class="sec">${esc(s.sector || '')}</div></td>
      <td class="num">${fmt(s.price, 0)}</td><td class="num">${fmt(s.RET1M, 0, '%')}</td><td class="num">${s.rank ?? '圏外'}</td>
      <td class="num">${fmt(s.p_jump === null || s.p_jump === undefined ? null : s.p_jump * 100, 0, '%')}</td>
      <td class="num">${fmt(s.p_crash === null || s.p_crash === undefined ? null : s.p_crash * 100, 0, '%')}</td>
      <td class="num">${fmt(s.PER)}</td><td class="num">${fmt(s.PBR, 2)}</td><td class="num">${fmt(s.DY, 1, '%')}</td><td class="num">${fmt(s.NCR, 2)}</td>
      <td class="num">${fmt(s.HI52, 0, '%')}</td><td><button class="del" data-f="${i}">削除</button></td></tr>`;
  }).join('');
  $('f-table').innerHTML = state.favorites.length ? `<table><tr><th>コード</th><th>銘柄</th><th>株価</th><th>1か月</th><th>順位</th><th>爆ハネ確率</th><th>暴落確率</th><th>PER</th><th>PBR</th><th>配当利回り</th><th>ネットキャッシュ比率</th><th>52週高値比</th><th></th></tr>${rows}</table>` : '<p class="note">まだ登録がありません。</p>';
  document.querySelectorAll('.del').forEach(b => b.onclick = async () => {
    if (b.dataset.h !== undefined) state.holdings.splice(+b.dataset.h, 1); else state.favorites.splice(+b.dataset.f, 1);
    render(); await save();
  });
  document.querySelectorAll('.fav').forEach(b => { b.textContent = state.favorites.includes(b.dataset.code) ? '★' : '☆'; });
}

async function toggleFav(code) {
  if (!user) { document.querySelector(".tab[data-t='mypage']")?.click(); alert('お気に入りに追加するにはログインしてください'); return; }
  const i = state.favorites.indexOf(code);
  if (i >= 0) state.favorites.splice(i, 1); else state.favorites.push(code);
  render(); await save();
}
document.querySelectorAll('.fav').forEach(b => b.addEventListener('click', () => toggleFav(b.dataset.code)));

const login = $('mp-login');
if (!FB) {
  login.innerHTML = 'ログイン機能はまだ設定されていません(config/firebase_config.json)。';
} else if (location.protocol === 'file:') {
  login.innerHTML = 'ログインはWeb版(GitHub Pages)でのみ使えます。';
} else {
  const V = '10.12.2';
  const {initializeApp} = await import(`https://www.gstatic.com/firebasejs/${V}/firebase-app.js`);
  const A = await import(`https://www.gstatic.com/firebasejs/${V}/firebase-auth.js`);
  const F = await import(`https://www.gstatic.com/firebasejs/${V}/firebase-firestore.js`);
  const app = initializeApp(FB); const auth = A.getAuth(app); const db = F.getFirestore(app);
  A.onAuthStateChanged(auth, async (u) => {
    user = u;
    if (!u) {
      login.innerHTML = `<div class="mp-form">
        <input id="lg-email" type="email" placeholder="メールアドレス" autocomplete="username" style="width:220px">
        <input id="lg-pass" type="password" placeholder="パスワード(6文字以上)" autocomplete="current-password" style="width:170px">
        <button class="btn" id="btn-login">ログイン</button>
        <button class="btn" id="btn-signup">新規登録</button>
        <a href="#" id="btn-reset" style="font-size:12px">パスワードを忘れた</a></div>
        <span id="lg-msg"></span><br>ログインすると、保有銘柄とお気に入りをPC・スマホで同じように見られます。`;
      $('mp-body').style.display = 'none';
      const msg = (t, bad) => { $('lg-msg').innerHTML = `<span class="${bad ? 'sell' : 'buy'}">${esc(t)}</span>`; };
      const jp = (e) => ({'auth/invalid-credential': 'メールアドレスかパスワードが違います', 'auth/wrong-password': 'パスワードが違います',
        'auth/user-not-found': 'このメールアドレスは登録されていません', 'auth/email-already-in-use': 'このメールアドレスは登録済みです(ログインしてください)',
        'auth/weak-password': 'パスワードは6文字以上にしてください', 'auth/invalid-email': 'メールアドレスの形式が正しくありません',
        'auth/admin-restricted-operation': '新規登録は締め切られています', 'auth/operation-not-allowed': 'Firebaseでメール/パスワードのログインが有効になっていません',
        'auth/too-many-requests': '試行回数が多すぎます。しばらく待ってからやり直してください'}[e.code] || e.message);
      const em = () => $('lg-email').value.trim(), pw = () => $('lg-pass').value;
      $('btn-login').onclick = async () => { try { await A.signInWithEmailAndPassword(auth, em(), pw()); } catch (e) { msg(jp(e), true); } };
      $('lg-pass').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') $('btn-login').click(); });
      $('btn-signup').onclick = async () => { try { await A.createUserWithEmailAndPassword(auth, em(), pw()); } catch (e) { msg(jp(e), true); } };
      $('btn-reset').onclick = async (ev) => { ev.preventDefault(); if (!em()) { msg('メールアドレスを入れてから押してください', true); return; }
        try { await A.sendPasswordResetEmail(auth, em()); msg('パスワード再設定のメールを送りました'); } catch (e) { msg(jp(e), true); } };
      state = {holdings: [], favorites: []}; render(); return;
    }
    login.innerHTML = `${esc(u.displayName || u.email)} でログイン中 <button class="btn" id="btn-logout">ログアウト</button>`
      + (S ? ` <span class="note">(株価: ${esc(S.date)} 終値)</span>` : '');
    $('btn-logout').onclick = () => A.signOut(auth);
    const ref = F.doc(db, 'users', u.uid);
    try { const snap = await F.getDoc(ref); if (snap.exists()) state = Object.assign({holdings: [], favorites: []}, snap.data()); }
    catch (e) { login.innerHTML += ' <span class="sell">データを読めません(Firestoreのルールを確認)</span>'; }
    save = async () => { try { await F.setDoc(ref, {holdings: state.holdings, favorites: state.favorites, updated: new Date().toISOString()}); } catch (e) { alert('保存できませんでした: ' + e.message); } };
    $('mp-body').style.display = 'block'; render();
  });
}
$('h-add') && ($('h-add').onclick = async () => {
  const code = $('h-code').value.trim().toUpperCase(), date = $('h-date').value, price = parseFloat($('h-price').value), shares = parseInt($('h-shares').value || '0');
  if (!code || !date || !(price > 0)) { alert('コード・買った日・買値を入れてください'); return; }
  if (S && !S.stocks[code]) { if (!confirm(`${code} はデータにない銘柄です。このまま登録しますか？`)) return; }
  state.holdings.push({code, date, price, shares}); ['h-code', 'h-price', 'h-shares'].forEach(id => $(id).value = ''); render(); await save();
});
$('f-add') && ($('f-add').onclick = async () => {
  const code = $('f-code').value.trim().toUpperCase(); if (!code) return;
  if (!state.favorites.includes(code)) state.favorites.push(code); $('f-code').value = ''; render(); await save();
});
if ($('h-date')) $('h-date').value = iso(new Date());
</script>
"""


def mypage_parts(h: int, stop_loss: float) -> tuple[str, str]:
    cfg = load_firebase_config()
    js = (MYPAGE_JS.replace("__FB_CONFIG__", json.dumps(cfg) if cfg else "null")
          .replace("__H__", str(h)).replace("__STOP__", str(stop_loss)))
    return MYPAGE_HTML, js
