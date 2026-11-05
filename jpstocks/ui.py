"""Webページの見た目(CSS)と、表を使いやすくするスクリプト

report.py のページに埋め込む。表の HTML は今のまま(<table> の1行目が見出し)で、スクリプトがあとから機能を足す:
並べ替え・検索・絞り込みボタン(★/A評価/新規)・列の切り替え・スマホでの行の展開・評価の理由の表示・ライト/ダークの切り替え。
"""

# <head> に入れる: フォント(読み込めなくても端末のフォントで表示できる)と、表示前にテーマを決める小さなスクリプト
HEAD = """<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+JP:wght@400;500;700;800&display=swap" rel="stylesheet">
<meta name="theme-color" content="#0d1117">
<script>try{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>"""

# ヘッダー右のテーマ切り替えボタン
THEME_BTN = "<button id='theme' class='icon-btn' title='ライト/ダークの切り替え' aria-label='テーマの切り替え'>◐</button>"

_LIGHT = """--bg:#f4f5f7;--card:#ffffff;--card2:#fafbfc;--fg:#0f1419;--mut:#64707d;--line:#e6e8ec;--soft:#f1f3f5;
  --acc:#0fa47a;--acc2:#0b7d5d;--acc-soft:#e6f6f0;--ink:#0d1117;--ink-fg:#f5f7fa;--ink-mut:#8b96a3;
  --warn:#c2620a;--sell:#e5484d;--up:#0f9d6e;--dn:#e5484d;--hl:#effaf5;--gold:#e8a200;
  --shadow:0 1px 2px rgba(16,24,40,.04),0 6px 20px rgba(16,24,40,.05);--shadow2:0 12px 40px rgba(16,24,40,.18)"""
_DARK = """--bg:#0b0d10;--card:#13161b;--card2:#171b21;--fg:#e8ebef;--mut:#8f9aa6;--line:#242a31;--soft:#1b2027;
  --acc:#2fd09a;--acc2:#5ee0b4;--acc-soft:#123026;--ink:#07090c;--ink-fg:#f5f7fa;--ink-mut:#7d8894;
  --warn:#f0a35e;--sell:#ff6b70;--up:#2fd09a;--dn:#ff6b70;--hl:#11241d;--gold:#f5b82e;
  --shadow:0 1px 0 rgba(255,255,255,.02);--shadow2:0 12px 40px rgba(0,0,0,.6)"""

STYLE = """
:root{""" + _LIGHT + """;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){""" + _DARK + """;color-scheme:dark}}
:root[data-theme=dark]{""" + _DARK + """;color-scheme:dark}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);margin:0;font-size:14px;line-height:1.55;-webkit-text-size-adjust:100%;
  font-family:"Inter","Noto Sans JP","Hiragino Sans","Yu Gothic UI","Meiryo",system-ui,sans-serif;font-feature-settings:"palt" 1;
  -webkit-font-smoothing:antialiased}
main{max-width:1280px;margin:0 auto;padding:0 24px 72px}
a{color:var(--acc2);text-decoration:none} a:hover{text-decoration:underline}
h1{font-size:18px;margin:0;font-weight:800;letter-spacing:.01em}
h2{font-size:17px;margin:34px 0 12px;font-weight:800;display:flex;align-items:center;gap:10px}
h2::before{content:"";width:4px;height:18px;border-radius:2px;background:linear-gradient(180deg,var(--acc),#3b82f6)}
h3{font-size:12.5px;margin:0 0 10px;color:var(--mut);font-weight:700;letter-spacing:.04em}
.note{color:var(--mut);font-size:12.5px;line-height:1.8;max-width:1100px}
b{font-weight:700}
/* ヘッダー(濃い帯) */
.top{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--ink) 92%,transparent);backdrop-filter:saturate(1.4) blur(12px);
  -webkit-backdrop-filter:saturate(1.4) blur(12px);color:var(--ink-fg);border-bottom:1px solid rgba(255,255,255,.06)}
.top-in{max-width:1280px;margin:0 auto;padding:12px 24px 0;display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.brand{display:flex;align-items:center;gap:10px;margin-right:auto}
.logo{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;font-weight:800;font-size:15px;color:#06281d;
  background:linear-gradient(135deg,#34e5a6,#3b82f6);box-shadow:0 0 0 1px rgba(255,255,255,.12) inset}
.brand h1 span{background:linear-gradient(90deg,#5ef0b9,#7fb3ff);-webkit-background-clip:text;background-clip:text;color:transparent}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ink-mut);border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:2px 10px;
  font-variant-numeric:tabular-nums}
.chip .dot{width:6px;height:6px;border-radius:50%;background:#34e5a6;box-shadow:0 0 8px #34e5a6}
.icon-btn{font:inherit;width:32px;height:32px;border-radius:9px;border:1px solid rgba(255,255,255,.12);background:transparent;color:var(--ink-fg);cursor:pointer;font-size:15px}
.icon-btn:hover{background:rgba(255,255,255,.08)}
/* タブ(下線式・横スクロール) */
.tabs{max-width:1280px;margin:0 auto;padding:6px 24px 0;display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;font:inherit;font-size:13px;font-weight:600;padding:9px 12px 11px;border:none;background:transparent;color:var(--ink-mut);cursor:pointer;
  position:relative;border-radius:8px 8px 0 0;transition:color .15s}
.tab:hover{color:var(--ink-fg)}
.tab.on{color:var(--ink-fg)}
.tab.on::after{content:"";position:absolute;left:10px;right:10px;bottom:0;height:3px;border-radius:3px 3px 0 0;background:linear-gradient(90deg,#34e5a6,#3b82f6)}
.pane{display:none} .pane.on{display:block;animation:rise .22s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
/* カード */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:20px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.card .big{font-size:30px;font-weight:800;line-height:1.15;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.card .sub{font-size:12px;color:var(--mut)}
.card .more{display:inline-block;margin-top:10px;font-size:12.5px;font-weight:600}
.gauge{position:relative;height:8px;border-radius:999px;margin:14px 0 6px;
  background:linear-gradient(90deg,#9aa4ae 0 50%,#4fb286 50% 70%,#f2b01e 70% 85%,#f06a2a 85% 95%,#e5484d 95%)}
.gauge i{position:absolute;top:-5px;width:6px;height:18px;border-radius:3px;background:var(--fg);transform:translateX(-3px);box-shadow:0 0 0 3px var(--card)}
.gauge-l{display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut)}
.strip span{display:inline-block;width:10px;height:10px;margin-right:2px;border-radius:3px;vertical-align:-1px}
.plist{list-style:none;margin:0;padding:0}
.plist li{display:flex;align-items:center;gap:10px;padding:8px 6px;margin:0 -6px;border-top:1px solid var(--line);font-size:13.5px;border-radius:10px;cursor:pointer;transition:background .12s}
.plist li:first-child{border-top-color:transparent}
.plist li:hover{background:var(--soft)}
.plist .rk{min-width:38px;color:var(--mut);font-size:11.5px;font-weight:600;font-variant-numeric:tabular-nums}
.plist .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.plist .nm small{display:block;font-weight:400;font-size:11.5px;color:var(--mut);overflow:hidden;text-overflow:ellipsis}
/* 説明の折りたたみ */
details.about{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:0 16px;margin:12px 0;transition:background .15s}
details.about>summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--fg);list-style:none;padding:12px 0;display:flex;align-items:center;gap:8px}
details.about>summary::-webkit-details-marker{display:none}
details.about>summary::before{content:"";width:7px;height:7px;border-right:2px solid var(--mut);border-bottom:2px solid var(--mut);transform:rotate(-45deg);transition:transform .2s;margin:0 4px 0 2px}
details.about[open]>summary::before{transform:rotate(45deg)}
details.about[open]{padding-bottom:12px}
details>summary.note{cursor:pointer}
/* 表 */
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);-webkit-overflow-scrolling:touch}
table{border-collapse:separate;border-spacing:0;white-space:nowrap;width:100%}
th,td{border-bottom:1px solid var(--line);padding:9px 12px;text-align:left;vertical-align:middle}
tr:last-child td{border-bottom:none}
th{font-size:11px;color:var(--mut);font-weight:700;letter-spacing:.03em;position:sticky;top:0;background:var(--card2);z-index:1;
  border-bottom:1px solid var(--line)}
th.sortable{cursor:pointer;user-select:none} th.sortable:hover{color:var(--fg)}
th .ar{opacity:.3;margin-left:3px;font-size:9px} th.asc,th.desc{color:var(--acc2)} th.asc .ar,th.desc .ar{opacity:1}
tbody tr:hover td,table tr:hover td{background:var(--soft)}
td{font-size:13px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.name{min-width:160px;max-width:240px;white-space:normal;font-weight:600}
.sec{font-size:11px;color:var(--mut);font-weight:400} tr.new td{background:var(--hl)} tr.cx td{opacity:.45}
td.up,.up{color:var(--up)} td.dn,.dn{color:var(--dn)}
.why{white-space:normal;min-width:280px;max-width:520px}
.yb{display:inline-block;margin-left:6px;padding:0 5px;border:1px solid var(--line);border-radius:5px;font-size:10.5px;font-weight:700;line-height:17px;text-decoration:none;color:#7b3fe4}
.yb:hover{background:#7b3fe4;color:#fff;border-color:#7b3fe4;text-decoration:none}
.fav{margin-left:2px;padding:0 4px;border:none;background:transparent;color:var(--gold);font-size:15px;cursor:pointer;line-height:17px}
.g{display:inline-grid;place-items:center;min-width:24px;height:22px;border-radius:7px;font-weight:800;font-size:12px;padding:0 6px;cursor:pointer;margin:1px 0;
  transition:transform .1s}
.g:hover{transform:scale(1.08)}
.gA{background:linear-gradient(135deg,#19c48a,#0e9a6c);color:#fff;box-shadow:0 2px 8px rgba(15,164,122,.35)}
.gB{background:var(--soft);border:1px solid var(--line);color:var(--mut)}
.gC{background:linear-gradient(135deg,#f0646a,#d93a40);color:#fff}
.rkb{display:inline-grid;place-items:center;min-width:24px;height:24px;border-radius:50%;font-weight:800;font-size:12px}
.rk1{background:linear-gradient(135deg,#ffd75e,#e8a200);color:#3d2b00}.rk2{background:linear-gradient(135deg,#e9edf2,#b6c0cb);color:#26303a}
.rk3{background:linear-gradient(135deg,#f4c39b,#c97a3f);color:#3a1d06}
.bar{display:inline-block;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--acc),#3b82f6);vertical-align:middle;margin-left:8px}
/* 表の上の操作 */
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0 10px}
.search{position:relative;flex:0 1 280px;min-width:200px}
.search input{width:100%;font:inherit;font-size:13px;padding:8px 12px 8px 32px;border:1px solid var(--line);border-radius:11px;background:var(--card);color:var(--fg);
  outline:none;transition:border-color .15s,box-shadow .15s}
.search input:focus{border-color:var(--acc);box-shadow:0 0 0 3px var(--acc-soft)}
.search::before{content:"";position:absolute;left:12px;top:50%;width:10px;height:10px;border:2px solid var(--mut);border-radius:50%;transform:translateY(-62%)}
.search::after{content:"";position:absolute;left:22px;top:58%;width:5px;height:2px;background:var(--mut);transform:rotate(45deg)}
.search kbd{position:absolute;right:9px;top:50%;transform:translateY(-50%);font:inherit;font-size:10.5px;color:var(--mut);border:1px solid var(--line);border-radius:5px;padding:0 5px}
.flt{display:inline-flex;gap:6px;flex-wrap:wrap}
.flt button,.seg button{font:inherit;font-size:12px;font-weight:600;padding:6px 11px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--mut);cursor:pointer;
  transition:all .12s}
.flt button:hover,.seg button:hover{color:var(--fg)}
.flt button.on{background:var(--acc-soft);border-color:var(--acc);color:var(--acc2)}
.seg{display:inline-flex;padding:3px;border:1px solid var(--line);border-radius:11px;background:var(--soft)}
.seg button{border:none;border-radius:8px;background:transparent;padding:5px 11px}
.seg button.on{background:var(--card);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.12)}
.cnt{font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums}
/* その他 */
.buy{color:var(--acc2);font-weight:700} .warn{color:var(--warn);font-size:11px} .sell{color:var(--sell);font-weight:700}
.btn{font:inherit;font-size:13px;font-weight:600;padding:7px 14px;border:none;border-radius:10px;background:var(--acc);color:#fff;cursor:pointer}
.btn:hover{filter:brightness(1.06)}
.del{font:inherit;font-size:12px;border:1px solid var(--line);background:transparent;color:var(--mut);border-radius:7px;cursor:pointer}
.mp-form{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}
.mp-form input{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg)}
.picks{line-height:1.8;max-width:1100px;padding-left:20px}
/* 評価の理由のシート */
#veil{position:fixed;inset:0;z-index:19;background:rgba(5,8,12,.35);backdrop-filter:blur(2px);display:none}
#veil.on{display:block;animation:fade .15s}
#sheet{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);width:min(560px,calc(100% - 24px));z-index:20;background:var(--card);color:var(--fg);
  border:1px solid var(--line);border-radius:18px;padding:16px 18px 18px;box-shadow:var(--shadow2);font-size:13.5px;line-height:1.75;display:none;max-height:70vh;overflow:auto}
#sheet.on{display:block;animation:up .2s ease-out}
@keyframes up{from{opacity:0;transform:translate(-50%,16px)}to{opacity:1;transform:translate(-50%,0)}}
#sheet .sh-h{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-weight:700;font-size:14.5px}
#sheet .sh-h .x{margin-left:auto;font:inherit;border:none;background:var(--soft);color:var(--mut);width:28px;height:28px;border-radius:50%;cursor:pointer}
#sheet .sh-b{white-space:pre-wrap;color:var(--fg)}
#totop{position:fixed;right:16px;bottom:16px;z-index:15;width:42px;height:42px;border-radius:14px;border:1px solid var(--line);background:var(--card);
  color:var(--fg);font-size:17px;cursor:pointer;box-shadow:var(--shadow2);display:none}
#totop.on{display:block;animation:fade .2s}
tr.det td{background:var(--soft);white-space:normal}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px 16px;font-size:12.5px}
.kv div span{display:block;font-size:10.5px;color:var(--mut)}
.pc-only{display:inline} .hint{display:none;font-size:11.5px;color:var(--mut)}
.empty{padding:28px;text-align:center;color:var(--mut);font-size:13px}
@media (min-width:721px){table.dt.core .popt{display:none}}
/* 横にスクロールしても銘柄名は左に残す */
table.dt .stick{position:sticky;left:0;z-index:1;background:var(--card);box-shadow:1px 0 0 var(--line)}
table.dt th.stick{z-index:3;background:var(--card2)}
/* 行の多い表は、画面の高さに収まる枠の中でスクロールし、見出しの行を上に残す */
.wrap.tall{max-height:calc(100vh - 170px);max-height:calc(100svh - 170px);overflow:auto}
.wrap.tall th{z-index:2} table.dt tr.new td.stick{background:var(--hl)} table.dt tr:hover td.stick{background:var(--soft)}
/* スマホ */
@media (max-width:720px){
  main{padding:0 12px 80px} .top-in{padding:10px 12px 0} .tabs{padding:4px 8px 0}
  h1{font-size:14.5px;white-space:nowrap} .card .big{font-size:26px} .logo{width:24px;height:24px;font-size:13px;border-radius:7px}
  .top-in{flex-wrap:nowrap;gap:8px} .brand{gap:8px;min-width:0}
  .chip{white-space:nowrap;min-width:0;overflow:hidden;padding:2px 8px;font-size:11px} .chip .dot{display:none}
  .chip.upd{display:none} .icon-btn{flex:0 0 auto;width:30px;height:30px}
  .cards{grid-template-columns:1fr;gap:10px;margin-top:14px}
  .card{border-radius:16px;padding:14px 15px}
  th,td{padding:8px 9px}
  table.dt.core .mhide{display:none}
  table.dt.core tr[data-i]{cursor:pointer}
  .hint{display:inline}
  .name{min-width:110px;max-width:150px}
  .why{min-width:200px}
  .search{flex:1 1 100%} .search kbd{display:none}
  .pc-only{display:none}
  #sheet{bottom:0;width:100%;border-radius:20px 20px 0 0;padding-bottom:calc(18px + env(safe-area-inset-bottom))}
}
"""

SCRIPT = r"""
<div id="veil"></div><div id="sheet" role="dialog" aria-modal="true"><div class="sh-h"><span class="sh-t"></span><button class="x" aria-label="閉じる">✕</button></div><div class="sh-b"></div></div>
<button id="totop" title="上へ" aria-label="上へ">↑</button>
<script>
(function(){
  var MOBILE = function(){ return window.matchMedia('(max-width:720px)').matches; };
  // スマホで見せる列(見出しの文字)。ここに無い列は、行をタップすると下に開いて見られる
  var CORE = ['#','コード','銘柄','Claude','期待スコア','ランクイン後','当てはまる条件','評価','損益','判定','1か月','順位','株価'];
  var num = function(s){
    s = (s||'').replace(/[,円%倍万\s]/g,'').replace('−','-').replace('+','');
    var v = parseFloat(s); return isNaN(v) ? null : v;
  };
  // 並べ替えに使う値: セルの最初の部分(下の小さい補足 .sec は除く)。非表示のタブの中でも読めるよう textContent を使う
  function cellText(td){
    if (!td) return '';
    if (td.dataset.v !== undefined) return td.dataset.v;
    var n = td.firstChild; while (n && n.nodeType === 3 && !n.textContent.trim()) n = n.nextSibling;
    return (n ? n.textContent : td.textContent).trim();
  }

  function enhance(table){
    if (table.dataset.dt) return; var rows = table.rows; if (!rows.length) return;
    var head = rows[0]; if (!head.querySelector('th')) return;
    table.dataset.dt = '1'; table.classList.add('dt');
    // 枠(.wrap)に入っていない表も、横にスクロールできる枠に入れる(スマホで画面からはみ出さないように)
    if (!table.closest('.wrap')){ var w0 = document.createElement('div'); w0.className = 'wrap'; table.parentNode.insertBefore(w0, table); w0.appendChild(table); }
    var heads = Array.prototype.map.call(head.cells, function(th){ return th.textContent.trim(); });
    var body = Array.prototype.slice.call(rows, 1).filter(function(r){ return !r.classList.contains('det'); });
    body.forEach(function(r, i){ r.dataset.i = i; });
    // 「#」の列の1〜3位はメダルの形に
    var nr = heads.indexOf('#');
    if (nr >= 0) body.forEach(function(r){ var c = r.cells[nr]; if (!c) return; var v = c.textContent.trim();
      if (v === '1' || v === '2' || v === '3'){ c.dataset.v = v; c.innerHTML = '<span class="rkb rk' + v + '">' + v + '</span>'; } });
    // 列の多い表は、横にスクロールしても「銘柄」の列を左に残す
    var ns = heads.indexOf('銘柄');
    if (ns >= 0 && heads.length > 5){
      head.cells[ns].classList.add('stick');
      body.forEach(function(r){ if (r.cells[ns]) r.cells[ns].classList.add('stick'); });
    }
    // スマホで隠す列: CORE にない列(ただし最大5列は見せる)
    var shown = 0;
    heads.forEach(function(h, k){
      var core = CORE.indexOf(h) >= 0 && shown < 5;
      if (core) shown++;
      if (!core && heads.length > 5){
        head.cells[k].classList.add('mhide');
        body.forEach(function(r){ if (r.cells[k]) r.cells[k].classList.add('mhide'); });
      }
      if (CORE.indexOf(h) < 0){   // PC の「主要な列だけ」で隠す列(スマホより多めに見せる)
        head.cells[k].classList.add('popt');
        body.forEach(function(r){ if (r.cells[k]) r.cells[k].classList.add('popt'); });
      }
    });
    // 見出しをクリックで並べ替え
    Array.prototype.forEach.call(head.cells, function(th, k){
      if (!heads[k]) return;
      th.classList.add('sortable'); th.insertAdjacentHTML('beforeend','<span class="ar">↕</span>');
      th.addEventListener('click', function(){
        var dir = th.classList.contains('desc') ? 'asc' : 'desc';
        Array.prototype.forEach.call(head.cells, function(x){ x.classList.remove('asc','desc'); var a = x.querySelector('.ar'); if (a) a.textContent = '↕'; });
        th.classList.add(dir); th.querySelector('.ar').textContent = dir === 'desc' ? '↓' : '↑';
        table.querySelectorAll('tr.det').forEach(function(d){ d.remove(); });
        var vals = body.map(function(r){ var t = cellText(r.cells[k]); var v = num(t); return {r:r, v:v, t:t}; });
        var isNum = vals.filter(function(x){ return x.v !== null; }).length >= vals.length * 0.6;
        vals.sort(function(a, b){
          var c;
          if (isNum){ if (a.v === null) return 1; if (b.v === null) return -1; c = a.v - b.v; }
          else c = a.t.localeCompare(b.t, 'ja');
          return dir === 'asc' ? c : -c;
        });
        var parent = body[0] ? body[0].parentNode : table;
        vals.forEach(function(x){ parent.appendChild(x.r); });
      });
    });
    // 「主要な列だけ」にしたスマホでは、行をタップすると隠れている列を下に開く
    body.forEach(function(r){
      r.addEventListener('click', function(ev){
        if (!MOBILE() || !table.classList.contains('core') || ev.target.closest('a,button,.g')) return;
        var nx = r.nextElementSibling;
        if (nx && nx.classList.contains('det')){ nx.remove(); return; }
        var kv = heads.map(function(h, k){
          var c = r.cells[k]; if (!c || getComputedStyle(c).display !== 'none' || !h) return '';
          return '<div><span>' + h + '</span>' + c.innerHTML + '</div>';
        }).join('');
        if (!kv) return;
        var d = document.createElement('tr'); d.className = 'det';
        d.innerHTML = '<td colspan="' + heads.length + '"><div class="kv">' + kv + '</div></td>';
        r.after(d);
      });
    });
    // 行が多い表には、検索・絞り込み・「主要な列だけ」の切り替えを付ける
    if (body.length >= 8){
      var box = document.createElement('div'); box.className = 'tools';
      var flt = [['all','すべて']];
      if (table.querySelector('.fav')) flt.push(['fav','★ お気に入り']);
      if (table.querySelector('td .gA')) flt.push(['A','Claude A']);
      if (table.querySelector('tr.new')) flt.push(['new','新規ランクイン']);
      box.innerHTML = '<label class="search"><input type="search" placeholder="銘柄名・コード・業種で絞り込み"><kbd>/</kbd></label>'
        + (flt.length > 1 ? '<span class="flt">' + flt.map(function(f, i){ return '<button data-f="' + f[0] + '"' + (i ? '' : ' class="on"') + '>' + f[1] + '</button>'; }).join('') + '</span>' : '')
        + '<span class="cnt"></span>'
        + (heads.length > 8 ? '<span class="seg"><button class="on" data-c="all">全部の列</button><button data-c="core">主要な列だけ</button></span>'
           + '<span class="hint">表は横にスクロールできます</span>' : '');
      var wrap = table.closest('.wrap') || table; wrap.parentNode.insertBefore(box, wrap);
      if (wrap.classList.contains('wrap')) wrap.classList.add('tall');
      var input = box.querySelector('input'), cnt = box.querySelector('.cnt'), mode = 'all';
      var test = {
        all: function(){ return true; },
        fav: function(r){ var b = r.querySelector('.fav'); return b && b.textContent.trim() === '★'; },
        A: function(r){ return !!r.querySelector('td .gA'); },
        'new': function(r){ return r.classList.contains('new'); }
      };
      function apply(){
        var q = input.value.trim().toLowerCase(), n = 0;
        table.querySelectorAll('tr.det').forEach(function(d){ d.remove(); });
        body.forEach(function(r){ var ok = (!q || r.textContent.toLowerCase().indexOf(q) >= 0) && test[mode](r); r.style.display = ok ? '' : 'none'; if (ok) n++; });
        cnt.textContent = (q || mode !== 'all') ? n + ' / ' + body.length + ' 銘柄' : '';
        if (mode === 'fav' && !n) cnt.textContent = '★が付いた銘柄はありません(マイページでログインすると使えます)';
      }
      input.addEventListener('input', apply);
      box.querySelectorAll('.flt button').forEach(function(b){
        b.addEventListener('click', function(){
          box.querySelectorAll('.flt button').forEach(function(x){ x.classList.toggle('on', x === b); });
          mode = b.dataset.f; apply();
        });
      });
      box.querySelectorAll('.seg button').forEach(function(b){
        b.addEventListener('click', function(){
          box.querySelectorAll('.seg button').forEach(function(x){ x.classList.toggle('on', x === b); });
          table.classList.toggle('core', b.dataset.c === 'core');
          table.querySelectorAll('tr.det').forEach(function(d){ d.remove(); });
        });
      });
    }
  }
  function enhanceAll(root){ (root || document).querySelectorAll('main table').forEach(enhance); }
  enhanceAll();
  // マイページの表は後から作られるので、変化を見て付け直す
  new MutationObserver(function(ms){ ms.forEach(function(m){ m.addedNodes.forEach(function(n){ if (n.nodeType === 1) enhanceAll(n.parentNode || document); }); }); })
    .observe(document.querySelector('main'), {childList: true, subtree: true});

  // 「/」で、今見ているタブの検索欄へ
  document.addEventListener('keydown', function(ev){
    if (ev.key !== '/' || /INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
    var p = document.querySelector('.pane.on .tools input'); if (p){ ev.preventDefault(); p.focus(); p.scrollIntoView({block: 'center'}); }
  });

  // Claude の評価(A/B/C)や最終候補の行を押すと、理由をシートで表示(スマホでもマウスなしで見られる)
  var sheet = document.getElementById('sheet'), veil = document.getElementById('veil');
  function openSheet(title, text){
    sheet.querySelector('.sh-t').innerHTML = title; sheet.querySelector('.sh-b').textContent = text;
    sheet.classList.add('on'); veil.classList.add('on');
  }
  function closeSheet(){ sheet.classList.remove('on'); veil.classList.remove('on'); }
  function nameOf(el){
    var row = el.closest('tr,li'); if (!row) return '';
    var n = row.querySelector('.name,.nm'); if (!n) return '';
    var t = n.cloneNode(true); t.querySelectorAll('.sec,small,.yb,.fav').forEach(function(x){ x.remove(); });
    return t.textContent.trim();
  }
  document.addEventListener('click', function(ev){
    var g = ev.target.closest('.g[title]') || (ev.target.closest('.plist li') && !ev.target.closest('a,button') ? ev.target.closest('.plist li').querySelector('.g[title]') : null);
    if (g){
      openSheet('<span class="g ' + g.className.replace(/^g\s*/, '') + '">' + g.textContent + '</span> ' + nameOf(g).replace(/[<>&]/g, ''), g.getAttribute('title'));
      ev.stopPropagation(); return;
    }
    if (ev.target.closest('#sheet .x') || !ev.target.closest('#sheet')) closeSheet();
  });
  document.addEventListener('keydown', function(ev){ if (ev.key === 'Escape') closeSheet(); });
  // 上に戻るボタン
  var tt = document.getElementById('totop');
  window.addEventListener('scroll', function(){ tt.classList.toggle('on', window.scrollY > 600); }, {passive: true});
  tt.addEventListener('click', function(){ window.scrollTo({top: 0}); });
  // ライト/ダークの切り替え(端末の設定 → 反対 → … の順。選んだものは覚えておく)
  var th = document.getElementById('theme');
  if (th) th.addEventListener('click', function(){
    var cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
    var nx = cur === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = nx;
    try { localStorage.setItem('theme', nx); } catch(e) {}
  });
  // カードの「一覧へ」リンク: タブを切り替えてから移動
  document.querySelectorAll('[data-go]').forEach(function(a){
    a.addEventListener('click', function(ev){
      ev.preventDefault(); var b = document.querySelector(".tab[data-t='" + a.dataset.go + "']"); if (b) b.click();
      var t = document.getElementById(a.dataset.anchor || ('tab-' + a.dataset.go)); if (t) t.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
  });
})();
</script>
"""
