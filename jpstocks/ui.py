"""Webページの見た目(CSS)と、表を使いやすくするスクリプト(並べ替え・検索・列の切り替え・スマホでの行の展開・評価の理由の表示)

report.py のページに埋め込む。表の HTML は今のまま(<table> の1行目が見出し)で、スクリプトがあとから機能を足す。
"""

STYLE = """
:root{--bg:#f6f6f3;--card:#ffffff;--fg:#1b1b19;--mut:#6b6b66;--line:#e4e3dd;--soft:#efeee9;--acc:#0b6e4f;--acc-soft:#e3f2ea;
  --warn:#b54708;--sell:#b42318;--up:#0b6e4f;--dn:#b42318;--hl:#eaf6ef;--shadow:0 1px 2px rgba(0,0,0,.05),0 4px 14px rgba(0,0,0,.04)}
@media (prefers-color-scheme:dark){:root{--bg:#121211;--card:#1b1b1a;--fg:#ecebe6;--mut:#a3a29b;--line:#2f2f2c;--soft:#242422;--acc:#4cc38a;
  --acc-soft:#1b2d24;--warn:#f0a35e;--sell:#f97066;--up:#4cc38a;--dn:#f97066;--hl:#1b2b22;--shadow:none}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font-family:"Hiragino Sans","Yu Gothic UI","Meiryo",system-ui,sans-serif;margin:0;font-size:14px;line-height:1.5;
  -webkit-text-size-adjust:100%}
main{max-width:1280px;margin:0 auto;padding:0 20px 60px}
a{color:var(--acc)}
h1{font-size:19px;margin:0;letter-spacing:.02em} h2{font-size:16px;margin:26px 0 10px} h3{font-size:14px;margin:0 0 8px}
.note{color:var(--mut);font-size:12.5px;line-height:1.7;max-width:1100px}
/* ヘッダー */
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.top-in{max-width:1280px;margin:0 auto;padding:10px 20px 0;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
.chip{display:inline-block;font-size:12px;color:var(--mut);background:var(--soft);border-radius:999px;padding:1px 10px}
/* タブ(横スクロール) */
.tabs{max-width:1280px;margin:0 auto;padding:8px 20px 10px;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;font:inherit;font-size:13px;padding:6px 14px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);cursor:pointer}
.tab.on{background:var(--acc);border-color:var(--acc);color:#fff}
.pane{display:none} .pane.on{display:block;animation:fade .15s ease-out}
@keyframes fade{from{opacity:.4}to{opacity:1}}
/* カード */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:16px 0 4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow)}
.card .big{font-size:26px;font-weight:700;line-height:1.2}
.card .sub{font-size:12px;color:var(--mut)}
.gauge{position:relative;height:10px;border-radius:999px;margin:10px 0 4px;
  background:linear-gradient(90deg,#8a8a85 0 50%,#5c8a6b 50% 70%,#e8a200 70% 85%,#d9480f 85% 95%,#b42318 95%)}
.gauge i{position:absolute;top:-4px;width:4px;height:18px;border-radius:2px;background:var(--fg);transform:translateX(-2px);box-shadow:0 0 0 2px var(--card)}
.gauge-l{display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut)}
.strip span{display:inline-block;width:11px;height:11px;margin-right:2px;border-radius:3px}
.plist{list-style:none;margin:0;padding:0}
.plist li{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--line);font-size:13px}
.plist li:first-child{border-top:none}
.plist .rk{min-width:34px;color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
.plist .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.more{font-size:12px}
/* 説明の折りたたみ */
details.about{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 14px;margin:12px 0}
details.about>summary{cursor:pointer;font-size:13px;color:var(--mut);list-style:none}
details.about>summary::before{content:"▸ ";} details.about[open]>summary::before{content:"▾ ";}
details>summary.note{cursor:pointer}
/* 表 */
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);-webkit-overflow-scrolling:touch}
table{border-collapse:separate;border-spacing:0;white-space:nowrap;width:100%}
th,td{border-bottom:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
tr:last-child td{border-bottom:none}
th{font-size:11.5px;color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card);z-index:1}
th.sortable{cursor:pointer;user-select:none} th.sortable:hover{color:var(--fg)}
th .ar{opacity:.35;margin-left:2px;font-size:10px} th.asc .ar,th.desc .ar{opacity:1;color:var(--acc)}
tbody tr:hover td,table tr:hover td{background:var(--soft)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.name{min-width:150px;max-width:230px;white-space:normal}
.sec{font-size:11px;color:var(--mut)} tr.new td{background:var(--hl)} tr.cx td{opacity:.5}
td.up,.up{color:var(--up)} td.dn,.dn{color:var(--dn)}
.why{white-space:normal;min-width:280px;max-width:520px}
.yb{display:inline-block;margin-left:6px;padding:0 5px;border:1px solid var(--line);border-radius:4px;font-size:11px;line-height:17px;text-decoration:none;color:#7b0099}
.yb:hover{background:#7b0099;color:#fff;border-color:#7b0099}
.fav{margin-left:4px;padding:0 4px;border:none;background:transparent;color:#e8a200;font-size:15px;cursor:pointer;line-height:17px}
.g{display:inline-block;min-width:20px;text-align:center;border-radius:5px;font-weight:700;font-size:12px;padding:0 5px;cursor:pointer;margin:1px 0}
.gA{background:var(--acc);color:#fff} .gB{border:1px solid var(--line);color:var(--mut)} .gC{background:var(--sell);color:#fff}
.bar{display:inline-block;height:6px;border-radius:3px;background:var(--acc);vertical-align:middle;margin-left:6px;opacity:.7}
/* 表の上の操作 */
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 8px}
.tools input[type=search]{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);min-width:200px;flex:0 1 260px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:var(--card)}
.seg button{font:inherit;font-size:12px;padding:5px 12px;border:none;background:transparent;color:var(--mut);cursor:pointer}
.seg button.on{background:var(--acc);color:#fff}
.cnt{font-size:12px;color:var(--mut)}
/* その他 */
.buy{color:var(--acc);font-weight:700} .warn{color:var(--warn);font-size:11px} .sell{color:var(--sell);font-weight:700}
.btn{font:inherit;font-size:13px;padding:5px 12px;border:1px solid var(--acc);border-radius:999px;background:transparent;color:var(--acc);cursor:pointer}
.del{font:inherit;font-size:12px;border:1px solid var(--line);background:transparent;color:var(--mut);border-radius:6px;cursor:pointer}
.mp-form{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}
.mp-form input{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.picks{line-height:1.8;max-width:1100px;padding-left:20px}
#sheet{position:fixed;left:12px;right:12px;bottom:12px;z-index:20;max-width:560px;margin:0 auto;background:var(--card);color:var(--fg);border:1px solid var(--line);
  border-radius:14px;padding:14px 16px;box-shadow:0 8px 30px rgba(0,0,0,.25);font-size:13px;line-height:1.7;white-space:pre-wrap;display:none}
#sheet.on{display:block;animation:fade .15s}
#totop{position:fixed;right:14px;bottom:14px;z-index:15;width:40px;height:40px;border-radius:50%;border:1px solid var(--line);background:var(--card);
  color:var(--fg);font-size:18px;cursor:pointer;box-shadow:var(--shadow);display:none}
#totop.on{display:block}
tr.det td{background:var(--soft);white-space:normal}
.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:4px 14px;font-size:12.5px}
.kv div span{display:block;font-size:10.5px;color:var(--mut)}
.pc-only{display:inline} .hint{display:none;font-size:11.5px;color:var(--mut)}
@media (min-width:721px){table.dt.core .popt{display:none}}
/* 横にスクロールしても銘柄名は左に残す */
table.dt .stick{position:sticky;left:0;z-index:1;background:var(--card);box-shadow:1px 0 0 var(--line)}
table.dt th.stick{z-index:3}
/* 行の多い表は、画面の高さに収まる枠の中でスクロールし、見出しの行を上に残す */
.wrap.tall{max-height:calc(100vh - 150px);max-height:calc(100svh - 150px);overflow:auto}
.wrap.tall th{z-index:2} table.dt tr.new td.stick{background:var(--hl)} table.dt tr:hover td.stick{background:var(--soft)}
/* スマホ */
@media (max-width:720px){
  main{padding:0 12px 70px} .top-in{padding:8px 12px 0} .tabs{padding:6px 12px 8px}
  h1{font-size:16px} .card .big{font-size:22px}
  .cards{grid-template-columns:1fr;gap:10px}
  th,td{padding:7px 8px}
  table.dt.core .mhide{display:none}
  table.dt.core tr[data-i]{cursor:pointer}
  .hint{display:inline}
  .name{min-width:110px;max-width:150px}
  .why{min-width:200px}
  .tools input[type=search]{flex:1 1 100%}
  .pc-only{display:none}
}
"""

SCRIPT = r"""
<div id="sheet" role="dialog"></div><button id="totop" title="上へ">↑</button>
<script>
(function(){
  var MOBILE = function(){ return window.matchMedia('(max-width:720px)').matches; };
  // スマホで見せる列(見出しの文字)。ここに無い列は、行をタップすると下に開いて見られる
  var CORE = ['#','コード','銘柄','Claude','期待スコア','ランクイン後','当てはまる条件','評価','損益','判定','1か月','順位','株価'];
  var num = function(s){
    s = (s||'').replace(/[,円%倍万\s]/g,'').replace('−','').replace('+','');
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
    var heads = Array.prototype.map.call(head.cells, function(th){ return th.textContent.trim(); });
    var body = Array.prototype.slice.call(rows, 1).filter(function(r){ return !r.classList.contains('det'); });
    body.forEach(function(r, i){ r.dataset.i = i; });
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
        Array.prototype.forEach.call(head.cells, function(x){ x.classList.remove('asc','desc'); });
        th.classList.add(dir);
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
    // 行が多い表には、検索と「主要な列だけ」の切り替えを付ける
    if (body.length >= 8){
      var box = document.createElement('div'); box.className = 'tools';
      box.innerHTML = '<input type="search" placeholder="銘柄名・コード・業種で絞り込み"><span class="cnt"></span>'
        + (heads.length > 8 ? '<span class="seg"><button class="on" data-c="all">全部の列</button><button data-c="core">主要な列だけ</button></span>'
           + '<span class="hint">表は横にスクロールできます。「主要な列だけ」では行を押すと残りが開きます</span>' : '');
      var wrap = table.closest('.wrap') || table; wrap.parentNode.insertBefore(box, wrap);
      if (wrap.classList.contains('wrap')) wrap.classList.add('tall');
      var input = box.querySelector('input'), cnt = box.querySelector('.cnt');
      input.addEventListener('input', function(){
        var q = input.value.trim().toLowerCase(), n = 0;
        table.querySelectorAll('tr.det').forEach(function(d){ d.remove(); });
        body.forEach(function(r){ var ok = !q || r.textContent.toLowerCase().indexOf(q) >= 0; r.style.display = ok ? '' : 'none'; if (ok) n++; });
        cnt.textContent = q ? n + ' / ' + body.length + ' 銘柄' : '';
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

  // Claude の評価(A/B/C)をタップすると、理由を下に表示(スマホでもマウスなしで見られる)
  var sheet = document.getElementById('sheet');
  document.addEventListener('click', function(ev){
    var g = ev.target.closest('.g[title]');
    if (g){ sheet.textContent = g.getAttribute('title'); sheet.classList.add('on'); ev.stopPropagation(); return; }
    if (!ev.target.closest('#sheet')) sheet.classList.remove('on');
  });
  // 上に戻るボタン
  var tt = document.getElementById('totop');
  window.addEventListener('scroll', function(){ tt.classList.toggle('on', window.scrollY > 600); }, {passive: true});
  tt.addEventListener('click', function(){ window.scrollTo({top: 0}); });
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
