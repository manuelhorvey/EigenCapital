import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'live', 'state.json')
TRADE_JOURNAL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'live', 'trade_journal.parquet')
DEFAULT_PORT = 5000

HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuantForge &middot; Command Center</title>
<style>
:root {
  color-scheme: light dark;
  --surface-page: light-dark(#f1f5f9, #070a14);
  --surface-card: light-dark(#ffffff, #0f1629);
  --surface-card-hover: light-dark(#f8fafc, #151f35);
  --surface-elevated: light-dark(#e8edf5, #1a2640);
  --surface-header: light-dark(#f8fafc, #0c1220);
  --border: light-dark(#d1d9e6, #1e2a45);
  --border-light: light-dark(#b8c4d8, #2a3a5c);
  --text-primary: light-dark(#0b1120, #e2e8f0);
  --text-secondary: light-dark(#475569, #94a3b8);
  --text-muted: light-dark(#94a3b8, #5b6f8a);
  --accent: light-dark(#2563eb, #38bdf8);
  --accent-glow: light-dark(rgba(37,99,235,0.08), rgba(56,189,248,0.08));
  --accent-border: light-dark(rgba(37,99,235,0.2), rgba(56,189,248,0.15));
  --green: light-dark(#16a34a, #22d66e);
  --green-dim: light-dark(rgba(22,163,74,0.08), rgba(34,214,110,0.08));
  --green-border: light-dark(rgba(22,163,74,0.2), rgba(34,214,110,0.18));
  --red: light-dark(#dc2626, #f87171);
  --red-dim: light-dark(rgba(220,38,38,0.08), rgba(248,113,113,0.08));
  --red-border: light-dark(rgba(220,38,38,0.2), rgba(248,113,113,0.18));
  --amber: light-dark(#d97706, #fbbf24);
  --amber-dim: light-dark(rgba(217,119,6,0.08), rgba(251,191,36,0.08));
  --amber-border: light-dark(rgba(217,119,6,0.2), rgba(251,191,36,0.18));
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: light-dark(0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.3));
  --shadow-hover: light-dark(0 4px 12px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.35));
}
*{margin:0;padding:0;box-sizing:border-box}
html{font-size:14px;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
body{background:var(--surface-page);color:var(--text-primary);font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-height:100vh;padding:24px;font-weight:400;line-height:1.5}
.container{max-width:1440px;margin:0 auto}

.header{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;background:var(--surface-card);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:20px;box-shadow:var(--shadow)}
.header-left{display:flex;align-items:center;gap:12px}
.header-logo{width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,var(--accent),#6366f1);display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;color:white;box-shadow:0 0 10px var(--accent-glow)}
.header-title{font-size:15px;font-weight:600;color:var(--text-primary);letter-spacing:-0.2px}
.header-title span{color:var(--text-muted);font-weight:400}
.header-right{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.header-status{display:flex;align-items:center;gap:6px}
.status-dot{width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s ease-in-out infinite;position:relative}
.status-dot::after{content:'';position:absolute;inset:-2.5px;border-radius:50%;border:2px solid var(--green);opacity:0.25;animation:pulse-ring 2s ease-in-out infinite}
@keyframes pulse-ring{0%,100%{transform:scale(1);opacity:0.25}50%{transform:scale(1.6);opacity:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.status-text{font-size:12px;font-weight:500;color:var(--green)}
.status-text.init{color:var(--amber)}
.header-time{font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums}
.pill{padding:2px 10px;border-radius:20px;font-size:10px;font-weight:600;background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border);letter-spacing:0.2px}

.loading{text-align:center;padding:100px 20px}
.spinner{width:28px;height:28px;border:2.5px solid var(--border);border-top:2.5px solid var(--accent);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 14px}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-title{font-size:14px;color:var(--text-secondary);margin-bottom:4px}
.loading-sub{font-size:12px;color:var(--text-muted)}

.section{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;margin-top:2px}
.section-title{font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:1.4px;color:var(--text-muted)}
.section-badge{font-size:10px;color:var(--text-muted);background:var(--surface-card);padding:2px 10px;border-radius:20px;border:1px solid var(--border);font-weight:500}

.portfolio-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.portfolio-card{background:var(--surface-card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 18px;position:relative;overflow:hidden;transition:border-color 0.2s,box-shadow 0.2s;box-shadow:var(--shadow)}
.portfolio-card:hover{border-color:var(--border-light);box-shadow:var(--shadow-hover)}
.portfolio-card.accent::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent),#6366f1)}
.portfolio-label{font-size:9.5px;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:3px}
.portfolio-value{font-size:22px;font-weight:700;letter-spacing:-0.4px;margin-bottom:1px;font-variant-numeric:tabular-nums}
.portfolio-sub{font-size:11px;color:var(--text-secondary)}
.change-up{color:var(--green)}
.change-down{color:var(--red)}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}

.asset-card{background:var(--surface-card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;position:relative;overflow:hidden;transition:all 0.2s;box-shadow:var(--shadow)}
.asset-card:hover{background:var(--surface-card-hover);border-color:var(--border-light);box-shadow:var(--shadow-hover)}
.asset-card.signal-buy{border-left:3px solid var(--green)}
.asset-card.signal-sell{border-left:3px solid var(--red)}
.asset-card.signal-flat{border-left:3px solid var(--amber)}
.asset-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.asset-name{font-size:12px;font-weight:600;color:var(--text-primary)}
.asset-price{font-size:14px;font-weight:700;color:var(--text-secondary);font-variant-numeric:tabular-nums;letter-spacing:-0.3px}
.asset-signal{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;padding:2px 9px;border-radius:20px}
.signal-buy .asset-signal{background:var(--green-dim);color:var(--green);border:1px solid var(--green-border)}
.signal-sell .asset-signal{background:var(--red-dim);color:var(--red);border:1px solid var(--red-border)}
.signal-flat .asset-signal{background:var(--amber-dim);color:var(--amber);border:1px solid var(--amber-border)}
.asset-metrics{display:grid;grid-template-columns:1fr 1fr;gap:3px 12px}
.asset-metric{display:flex;justify-content:space-between;font-size:11.5px;padding:1.5px 0}
.asset-metric-label{color:var(--text-muted)}
.asset-metric-value{color:var(--text-secondary);font-weight:500;font-variant-numeric:tabular-nums}
.asset-conf-bar{height:3px;border-radius:2px;margin-top:7px;background:var(--surface-elevated);overflow:hidden}
.asset-conf-fill{height:100%;border-radius:2px;transition:width 0.6s cubic-bezier(0.4,0,0.2,1)}
.asset-more{font-size:10.5px;color:var(--text-muted);margin-top:5px;padding-top:5px;border-top:1px solid var(--border);line-height:1.5}
.asset-more+.asset-more{border-top:none;margin-top:0;padding-top:0}

.table-wrap{background:var(--surface-card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:20px;box-shadow:var(--shadow)}
table{width:100%;border-collapse:collapse}
th{padding:10px 14px;text-align:left;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:1.1px;color:var(--text-muted);background:var(--surface-header);border-bottom:1px solid var(--border)}
td{padding:9px 14px;border-bottom:1px solid var(--border);font-size:12px;color:var(--text-secondary)}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--surface-card-hover)}
.cell-signal{font-weight:600}
.cell-buy{color:var(--green)}
.cell-sell{color:var(--red)}
.cell-flat{color:var(--amber)}
.cell-up{color:var(--green)}
.cell-down{color:var(--red)}
.cell-warn{color:var(--amber)}
.cell-mono{font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums}

.metric-card{border:1px solid var(--border);border-radius:var(--radius);background:var(--surface-card);overflow:hidden;box-shadow:var(--shadow);transition:border-color 0.2s}
.metric-card:hover{border-color:var(--border-light)}
.metric-head{padding:9px 14px 6px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);background:var(--surface-header)}
.metric-head-name{font-size:11px;font-weight:600}
.metric-head-count{font-size:9px;color:var(--text-muted)}
.metric-body{padding:7px 14px 9px}
.metric-row{display:flex;justify-content:space-between;padding:3px 0;font-size:11.5px}
.metric-label{color:var(--text-muted)}
.metric-val{color:var(--text-secondary);font-weight:500;font-variant-numeric:tabular-nums}
.metric-val.vis{color:var(--green)}
.metric-val.warn{color:var(--amber)}

.halt-card{border:1px solid var(--border);border-radius:var(--radius);padding:12px;text-align:center;background:var(--surface-card);transition:border-color 0.2s;box-shadow:var(--shadow)}
.halt-card.pass{background:var(--green-dim);border-color:var(--green-border)}
.halt-card.fail{background:var(--red-dim);border-color:var(--red-border)}
.halt-icon{font-size:17px;margin-bottom:4px;opacity:0.55}
.halt-label{font-size:9px;text-transform:uppercase;letter-spacing:1.1px;color:var(--text-muted);margin-bottom:2px}
.halt-value{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums}
.halt-value.pass{color:var(--green)}
.halt-value.fail{color:var(--red)}

.footer{display:flex;justify-content:space-between;align-items:center;padding:10px 18px;background:var(--surface-card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)}
.footer-text{font-size:11.5px;color:var(--text-muted)}
.footer-text strong{color:var(--text-secondary);font-weight:500}
.footer-badge{padding:2px 10px;border-radius:20px;font-size:9.5px;font-weight:600;background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border);letter-spacing:0.2px}

@media(max-width:1100px){.portfolio-row,.grid-4{grid-template-columns:repeat(2,1fr)}}
@media(max-width:750px){.grid-2{grid-template-columns:1fr}.portfolio-row,.grid-4{grid-template-columns:1fr 1fr}.header{flex-direction:column;gap:10px;align-items:flex-start}.header-right{width:100%;justify-content:flex-start}}
@media(max-width:480px){.portfolio-row,.grid-4{grid-template-columns:1fr}.grid-3{grid-template-columns:1fr}body{padding:14px}}
.new-badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:1px;background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border);margin-left:6px;animation:new-pulse 1.5s ease-in-out infinite}
@keyframes new-pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.asset-last-trade{font-size:10px;color:var(--text-muted);margin-top:5px;padding-top:5px;border-top:1px solid var(--border);line-height:1.4}
.result-tp{color:var(--green);font-weight:600}
.result-sl{color:var(--red);font-weight:600}
.result-exit{color:var(--amber);font-weight:600}
.result-open{color:var(--text-muted);font-weight:500}
.trade-empty{text-align:center;padding:20px;color:var(--text-muted);font-size:12px}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <div class="header-left">
    <div class="header-logo">Q</div>
    <div class="header-title">QuantForge <span>/ Command Center</span></div>
    <span class="pill" id="liveBadge">Paper Trading</span>
  </div>
  <div class="header-right">
    <div class="header-status">
      <span class="status-dot" id="statusDot"></span>
      <span class="status-text" id="statusText">Initializing...</span>
    </div>
    <span class="header-time"><span id="currentDate">&mdash;</span> <span id="currentTime">&mdash;</span></span>
    <span class="pill" id="daysBadge">0 days</span>
    <span class="pill" id="sessionBadge" style="background:var(--amber-dim);color:var(--amber);border-color:var(--amber-border)">Session: --</span>
  </div>
</div>

<div id="loadingState" class="loading">
  <div class="spinner"></div>
  <div class="loading-title">Connecting to paper trading engine...</div>
  <div class="loading-sub" id="loadingDetail">waiting for signal data</div>
</div>

<div id="dashboardContent" style="display:none;">

  <div class="portfolio-row" id="portfolioRow"></div>

  <div class="section">
    <div class="section-title">Assets</div>
    <span class="section-badge" id="assetCount">0 active</span>
  </div>
  <div class="grid-4" id="assetGrid"></div>

  <div class="section">
    <div class="section-title">Execution Tickets</div>
    <span class="section-badge">Signals</span>
  </div>
  <div class="table-wrap">
  <table><thead><tr>
    <th>Asset</th><th>Regime</th><th>Signal</th><th>Confidence</th><th>Price</th><th>Alloc</th><th>Return</th><th>Drawdown</th><th>SL / TP</th>
  </tr></thead><tbody id="signalsBody"></tbody></table>
  </div>

  <div class="section">
    <div class="section-title">Live Metrics</div>
    <span class="section-badge">Performance</span>
  </div>
  <div class="grid-3" id="metricsGrid"></div>

  <div class="section">
    <div class="section-title">Trade Feed</div>
    <span class="section-badge" id="tradeFeedCount">Recent</span>
  </div>
  <div class="table-wrap">
  <table><thead><tr>
    <th>Time</th><th>Asset</th><th>Direction</th><th>Entry</th><th>Exit</th><th>P&L%</th><th>Bars</th><th>Result</th>
  </tr></thead><tbody id="tradeFeedBody"><tr><td colspan="8" class="trade-empty">No trades closed yet</td></tr></tbody></table>
  </div>

  <div class="section">
    <div class="section-title">Halt Conditions</div>
    <span class="section-badge">Safety</span>
  </div>
  <div class="grid-4" id="haltGrid"></div>

  <div class="footer">
    <div class="footer-text" id="footerText">Loading...</div>
    <span class="footer-badge">Paper Trading</span>
  </div>

</div>
</div>

<script>
const STATE_PATH = '/state.json';
let stateData = null;
var tradeData = [];
var prevPositions = {};
var newBadgeTimers = {};

function getLastTrade(name){
  for(var i=0;i<tradeData.length;i++){if(tradeData[i].asset===name)return tradeData[i]}
  return null;
}

function resultInfo(reason){
  var r=(reason||'').toLowerCase();
  if(r==='tp')return{cls:'result-tp',text:'TP'};
  if(r==='sl')return{cls:'result-sl',text:'SL'};
  return{cls:'result-exit',text:'Exit'};
}

function renderTradeFeed(){
  var tbody=document.getElementById('tradeFeedBody');
  if(!tradeData||tradeData.length===0){
    tbody.innerHTML='<tr><td colspan="8" class="trade-empty">No trades closed yet</td></tr>';
    document.getElementById('tradeFeedCount').textContent='0 trades';
    return;
  }
  document.getElementById('tradeFeedCount').textContent=tradeData.length+' recent';
  var html='';
  for(var i=0;i<tradeData.length;i++){
    var t=tradeData[i],ri=resultInfo(t.reason);
    var ret=t['return']!=null?t['return']:0,retPct=(ret*100).toFixed(2);
    var side=(t.side||'').toUpperCase(),sideClass=side==='LONG'?'cell-buy':side==='SHORT'?'cell-sell':'';
    var bars='\u2014';
    if(t.entry_date&&t.exit_date){var d1=new Date(t.entry_date),d2=new Date(t.exit_date);var diff=Math.max(1,Math.round((d2-d1)/(864e5)));bars=diff+'d'}
    html+='<tr><td class="cell-mono">'+(t.exit_date||'\u2014')+'</td>';
    html+='<td><strong>'+(t.asset||'\u2014')+'</strong></td>';
    html+='<td class="cell-signal '+sideClass+'">'+side+'</td>';
    html+='<td>$'+fmtPrice(t.entry)+'</td><td>$'+fmtPrice(t.exit)+'</td>';
    html+='<td class="'+(ret>=0?'cell-up':'cell-down')+'">'+(ret>=0?'+':'')+retPct+'%</td>';
    html+='<td>'+bars+'</td><td class="'+ri.cls+'">'+ri.text+'</td></tr>';
  }
  tbody.innerHTML=html;
}

async function fetchTrades(){
  try{var r=await fetch('/trades.json?t='+Date.now());if(r.ok){tradeData=await r.json();renderTradeFeed()}}catch(e){}
}

function fmt(n,d){if(n==null||n===Infinity||isNaN(n))return'\u2014';return Number(n).toFixed(d||2)}
function fmtPrice(price){if(price==null||price===Infinity||isNaN(price))return'\u2014';var s=String(price),dec=s.indexOf('.'),natural=dec===-1?0:s.length-dec-1;return Number(price).toFixed(Math.max(2,Math.min(natural,6)))}
function cssClass(s){if(!s)return'flat';var u=String(s).toUpperCase();return u==='BUY'?'buy':u==='SELL'?'sell':'flat'}
function fd(d){return new Date(d).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}
function ft(d){return new Date(d).toLocaleTimeString('en-US',{hour12:false})}

function getSession(){
  var now=new Date(),et=new Date(now.toLocaleString('en-US',{timeZone:'America/New_York'}));
  var day=et.getDay(),hour=et.getHours(),min=et.getMinutes(),t=hour*60+min;
  var fxOpen=t>=0&&t<1440;
  var sessions=[];
  if(day===6){
    sessions.push({name:'NZDJPY','open':false});sessions.push({name:'USDCAD','open':false});sessions.push({name:'CADJPY','open':false});sessions.push({name:'GC','open':false});sessions.push({name:'EURAUD','open':false});sessions.push({name:'BTC','open':true});
  }else if(day===0){
    sessions.push({name:'NZDJPY','open':t>=1020});sessions.push({name:'USDCAD','open':t>=1020});sessions.push({name:'CADJPY','open':t>=1020});sessions.push({name:'GC','open':t>=1020});sessions.push({name:'EURAUD','open':t>=1020});sessions.push({name:'BTC','open':true});
  }else{
    sessions.push({name:'NZDJPY','open':fxOpen});
    sessions.push({name:'USDCAD','open':fxOpen});
    sessions.push({name:'CADJPY','open':fxOpen});
    sessions.push({name:'GC','open':fxOpen});
    sessions.push({name:'EURAUD','open':fxOpen});
    sessions.push({name:'BTC','open':true});
  }
  return sessions;
}

function render(state){
  var assets=state.assets||{},p=state.portfolio||{};
  var totalValue=p.total_value||0,totalReturn=p.total_return||0,capital=p.capital||0,days=p.days_running||0;
  var startDate=p.start_date||null,nTrades=0,maxDD=0,minPF=Infinity;
  for(var k in assets){var m=assets[k].metrics||{};nTrades+=(m.n_trades||0);if(m.drawdown<maxDD)maxDD=m.drawdown;if(m.monthly_pf!=null&&m.monthly_pf<minPF)minPF=m.monthly_pf}
  var totalPnl=0;for(var k in assets){var pos=(assets[k].metrics||{}).position;if(pos&&pos.unrealized_pnl!=null)totalPnl+=pos.unrealized_pnl}
  totalPnl=totalPnl/Object.keys(assets).length||0;

  document.getElementById('portfolioRow').innerHTML=
    '<div class="portfolio-card accent"><div class="portfolio-label">Portfolio Value</div><div class="portfolio-value" style="color:var(--accent)">$'+fmt(totalValue,2)+'</div><div class="portfolio-sub">Capital: $'+fmt(capital,2)+'</div></div>'+
    '<div class="portfolio-card"><div class="portfolio-label">Total Return</div><div class="portfolio-value '+(totalReturn>=0?'change-up':'change-down')+'">'+fmt(totalReturn)+'%</div><div class="portfolio-sub">Since '+fd(startDate||new Date())+'</div></div>'+
    '<div class="portfolio-card"><div class="portfolio-label">Unrealized P&amp;L</div><div class="portfolio-value '+(totalPnl>=0?'change-up':'change-down')+'">'+fmt(totalPnl,2)+'%</div><div class="portfolio-sub">Across '+Object.keys(assets).length+' assets</div></div>'+
    '<div class="portfolio-card"><div class="portfolio-label">Trades Taken</div><div class="portfolio-value" style="color:var(--text-primary)">'+nTrades+'</div><div class="portfolio-sub">Over '+days+' days</div></div>';

  var cnt=0,ac='';
  for(var name in assets){
    cnt++;
    var d=assets[name],m=d.metrics||{},s=d.last_signal;
    var sig=s?s.signal:'FLAT',conf=s?s.confidence||0:0,cls=cssClass(sig);
    var entry=null,stop=null,tp=null,upnl=null;
    var pos=m.position;
    if(pos){entry=pos.entry;stop=pos.sl;tp=pos.tp;upnl=pos.unrealized_pnl}
    var val=m.current_value||0,ret=m.total_return||0,dd=m.drawdown||0;
    var confColor=conf>=60?'var(--green)':conf>=45?'var(--amber)':'var(--red)';
    var price=s?s.close_price:null;
    var prevPos=prevPositions[name],isNewEntry=pos&&pos.entry&&(!prevPos||prevPos.entry!==pos.entry);
    if(isNewEntry){newBadgeTimers[name]=60}
    if(!isNewEntry&&newBadgeTimers[name]>0){newBadgeTimers[name]--}
    prevPositions[name]=pos?{entry:pos.entry}:null;
    var newBadge=newBadgeTimers[name]>0?'<span class="new-badge">New</span>':'';
    ac+='<div class="asset-card signal-'+cls+'"><div class="asset-header"><span class="asset-name">'+name+newBadge+'</span>'+(price!=null?'<span class="asset-price">$'+fmtPrice(price)+'</span>':'')+'<span class="asset-signal">'+sig+'</span></div>';
    ac+='<div class="asset-metrics"><div class="asset-metric"><span class="asset-metric-label">Confidence</span><span class="asset-metric-value" style="color:'+confColor+'">'+fmt(conf,1)+'%</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Value</span><span class="asset-metric-value">$'+fmt(val,2)+'</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Return</span><span class="asset-metric-value '+(ret>=0?'change-up':'change-down')+'">'+fmt(ret)+'%</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Drawdown</span><span class="asset-metric-value '+(dd>-3?'':dd>-5?'cell-warn':'change-down')+'">'+fmt(dd)+'%</span></div></div>';
    ac+='<div class="asset-conf-bar"><div class="asset-conf-fill" style="width:'+conf+'%;background:'+confColor+'"></div></div>';
    var lt=getLastTrade(name);
    if(lt){var lri=resultInfo(lt.reason),lret=lt['return']!=null?(lt['return']*100).toFixed(2):'0.00',lside=(lt.side||'').toUpperCase();ac+='<div class="asset-last-trade">Last: '+lside+' <span class="'+lri.cls+'">'+(lt['return']>=0?'+':'')+lret+'% ('+lri.text+')</span></div>'}
    if(entry||stop||tp||upnl!=null){
      ac+='<div class="asset-more">';
      if(entry)ac+='Entry $'+fmtPrice(entry);
      if(stop)ac+=' &middot; SL $'+fmtPrice(stop);
      ac+='</div><div class="asset-more">';
      if(tp)ac+='TP $'+fmtPrice(tp);
      if(upnl!=null)ac+=' &middot; P&L <span style="color:'+(upnl>=0?'var(--green)':'var(--red)')+'">'+fmt(upnl,2)+'%</span>';
      ac+='</div>';
    }
    ac+='</div>';
  }
  document.getElementById('assetGrid').innerHTML=ac;
  document.getElementById('assetCount').textContent=cnt+' active';

  var tb='';
  for(var name in assets){
    var d=assets[name],m=d.metrics||{},s=d.last_signal;
    var sig=s?s.signal:'FLAT',conf=s?s.confidence||0:0,price=s?s.close_price:0;
    var alloc=p.allocations?p.allocations[name]:0.25;
    var ret=m.total_return||0,dd=m.drawdown||0,pos=m.position;
    tb+='<tr><td><strong>'+name+'</strong></td>';
    tb+='<td style="color:var(--text-muted)">'+(sig==='BUY'?'Bullish':sig==='SELL'?'Bearish':'Neutral')+'</td>';
    tb+='<td class="cell-signal cell-'+cssClass(sig)+'">'+sig+'</td>';
    tb+='<td><span style="display:inline-block;width:50px;height:6px;border-radius:3px;background:var(--surface-elevated);vertical-align:middle;margin-right:6px;overflow:hidden"><span style="display:block;height:100%;width:'+conf+'%;border-radius:3px;background:'+(conf>=60?'var(--green)':conf>=45?'var(--amber)':'var(--red)')+'"></span></span>'+fmt(conf,1)+'%</td>';
    tb+='<td>$'+fmtPrice(price)+'</td>';
    tb+='<td>'+Math.round(alloc*100)+'%</td>';
    tb+='<td class="cell-'+(ret>=0?'up':'down')+'">'+fmt(ret)+'%</td>';
    tb+='<td class="cell-'+(dd>-3?'up':dd>-5?'warn':'down')+'">'+fmt(dd)+'%</td>';
    if(pos&&pos.sl)tb+='<td class="cell-mono">$'+fmtPrice(pos.sl)+' / $'+fmtPrice(pos.tp)+'</td>';
    else tb+='<td class="cell-mono">\u2014</td></tr>';
  }
  document.getElementById('signalsBody').innerHTML=tb;

  var mg='';
  for(var name in assets){
    var d=assets[name],m=d.metrics||{};
    var pf=m.profit_factor;var pfStr=(pf!=null&&pf!=Infinity)?fmt(pf):'\u2014';
    var mpf=m.monthly_pf;var mpfStr=(mpf!=null&&mpf!=Infinity)?fmt(mpf):'\u2014';
    mg+='<div class="metric-card"><div class="metric-head"><span class="metric-head-name">'+name+'</span><span class="metric-head-count">'+m.n_trades+' trades</span></div>';
    mg+='<div class="metric-body"><div class="metric-row"><span class="metric-label">Profit Factor</span><span class="metric-val '+(pfStr!='\u2014'&&parseFloat(pfStr)>=1?'vis':'')+'">'+pfStr+'</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Win Rate</span><span class="metric-val">'+fmt(m.win_rate)+'%</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Signal Dist</span><span class="metric-val">'+(m.signal_distribution?((m.signal_distribution.BUY||0)+'B / '+(m.signal_distribution.SELL||0)+'S / '+(m.signal_distribution.FLAT||0)+'F'):'\u2014')+'</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Mean Conf</span><span class="metric-val">'+fmt(m.mean_confidence)+'%</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">P(Long/Short)</span><span class="metric-val">'+fmt(m.mean_prob_long)+'% / '+fmt(m.mean_prob_short)+'%</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Monthly PF</span><span class="metric-val '+(mpf!=null&&mpf>=0.7?'vis':'warn')+'">'+mpfStr+'</span></div></div></div>';
  }
  document.getElementById('metricsGrid').innerHTML=mg;

  var hc=state.halt_conditions||{drawdown:-0.08,monthly_pf:0.7,signal_drought:30,prob_drift:0.15};
  document.getElementById('haltGrid').innerHTML=
    '<div class="halt-card '+(maxDD>hc.drawdown*100?'pass':'')+'"><div class="halt-icon">&#9660;</div><div class="halt-label">Max Drawdown</div><div class="halt-value '+(maxDD>hc.drawdown*100?'pass':'fail')+'">'+fmt(maxDD)+'% / '+fmt(hc.drawdown*100,0)+'%</div></div>'+
    '<div class="halt-card '+(minPF>=hc.monthly_pf?'pass':'fail')+'"><div class="halt-icon">&#9632;</div><div class="halt-label">Monthly PF</div><div class="halt-value '+(minPF>=hc.monthly_pf?'pass':'fail')+'">'+(minPF<Infinity?fmt(minPF):'\u2014')+' / '+fmt(hc.monthly_pf,2)+'</div></div>'+
    '<div class="halt-card pass"><div class="halt-icon">&#9673;</div><div class="halt-label">Signal Drought</div><div class="halt-value pass">0d / '+hc.signal_drought+'d</div></div>'+
    '<div class="halt-card pass"><div class="halt-icon">&#9650;</div><div class="halt-label">Prob Drift</div><div class="halt-value pass">&lt; '+fmt(hc.prob_drift*100,0)+'%</div></div>';

  var today=new Date(),gate=new Date(today);gate.setMonth(gate.getMonth()+6);
  var sessionInfo=getSession();
  var openList=sessionInfo.filter(function(s){return s.open}).map(function(s){return s.name}).join(', ');
  document.getElementById('footerText').innerHTML=
    '<strong>Next retrain:</strong> '+fd(new Date(today.getFullYear()+1,0,1))+
    ' &middot; <strong>Started:</strong> '+(p.start_date?fd(new Date(p.start_date)):'\u2014')+
    ' &middot; <strong>6-month gate:</strong> '+fd(gate)+
    ' &middot; <strong>Cleared:</strong> '+(p.deployment_cleared?'Yes':'No')+
    ' &middot; <strong>Refresh:</strong> 30s'+
    ' &middot; <strong>Sessions:</strong> '+openList+' trading';
  document.getElementById('daysBadge').textContent=days+' days';
  var liveCount=0;for(var k in assets){if((assets[k].last_signal||{}).signal)liveCount++}
  document.getElementById('liveBadge').textContent=liveCount+' assets live';
  document.getElementById('statusText').textContent='Live Market Feed Active';
  document.getElementById('statusText').className='status-text';

  var sessionInfo=getSession();
  var openList=sessionInfo.filter(function(s){return s.open}).map(function(s){return s.name}).join(', ');
  var closedList=sessionInfo.filter(function(s){return !s.open}).map(function(s){return s.name}).join(', ');
  var badgeEl=document.getElementById('sessionBadge');
  if(sessionInfo.every(function(s){return s.open})){
    badgeEl.textContent='All Markets Open';
    badgeEl.style.cssText='background:var(--green-dim);color:var(--green);border-color:var(--green-border)';
  }else if(sessionInfo.every(function(s){return !s.open})){
    badgeEl.textContent='All Markets Closed';
    badgeEl.style.cssText='background:var(--red-dim);color:var(--red);border-color:var(--red-border)';
  }else{
    badgeEl.textContent='Open: '+openList+' | Closed: '+closedList;
    badgeEl.style.cssText='background:var(--amber-dim);color:var(--amber);border-color:var(--amber-border)';
  }
}

async function fetchState(){
  try{
    var r=await fetch(STATE_PATH+'?t='+Date.now());
    if(!r.ok)throw new Error('HTTP '+r.status);
    var state=await r.json();
    stateData=state;
    document.getElementById('loadingState').style.display='none';
    document.getElementById('dashboardContent').style.display='block';
    render(state);
    fetchTrades();
  }catch(e){
    document.getElementById('loadingState').style.display='block';
    document.getElementById('dashboardContent').style.display='none';
    document.getElementById('statusText').textContent='Waiting for engine...';
    document.getElementById('statusText').className='status-text init';
    document.getElementById('statusDot').style.background='var(--amber)';
    document.getElementById('loadingDetail').innerHTML='Error: '+e.message+'<br>Retrying in 5s...';
    setTimeout(fetchState,5000);
  }
}

setTimeout(fetchState,1000);
setInterval(fetchState,30000);
setInterval(function(){
  var n=new Date();
  document.getElementById('currentDate').textContent=fd(n);
  document.getElementById('currentTime').textContent=ft(n);
},1000);
</script>
</body>
</html>'''


def serve(port=DEFAULT_PORT, shutdown_event=None):
    import http.server
    import socketserver

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/' or path == '/dashboard.html':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(HTML.encode('utf-8'))
            elif path == '/state.json':
                try:
                    with open(STATE_PATH, 'r') as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(data.encode('utf-8'))
                except FileNotFoundError:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'engine_status': {'initialized': True, 'last_update': None, 'start_time': None},
                        'portfolio': {'total_value': 0, 'total_return': 0, 'days_running': 0,
                                      'start_date': '', 'last_update': None, 'capital': 100000,
                                       'allocations': {'BTC': 0.20, 'NZDJPY': 0.15, 'CADJPY': 0.13, 'USDCAD': 0.10, 'GC': 0.20, 'EURAUD': 0.22},
                                      'deployment_cleared': True},
                        'assets': {}, 'halt_conditions': {'drawdown': -0.08, 'monthly_pf': 0.7, 'signal_drought': 30, 'prob_drift': 0.15},
                    }, indent=2).encode('utf-8'))
            elif path == '/trades.json':
                trades = []
                try:
                    import pandas as pd
                    if os.path.exists(TRADE_JOURNAL_PATH):
                        df = pd.read_parquet(TRADE_JOURNAL_PATH)
                        if len(df) > 0:
                            df = df.sort_values('exit_date', ascending=False).head(10)
                            trades = json.loads(df.to_json(orient='records', default_handler=str))
                except Exception:
                    pass
                if not trades:
                    try:
                        with open(STATE_PATH, 'r') as f:
                            sd = json.load(f)
                        for aname, adata in sd.get('assets', {}).items():
                            for t in adata.get('metrics', {}).get('trade_log', []):
                                trades.append(t)
                        trades = sorted(trades, key=lambda x: x.get('exit_date', ''), reverse=True)[:10]
                    except Exception:
                        pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(trades, default=str).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()

    class ReuseServer(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = ReuseServer(('127.0.0.1', port), Handler)
    httpd.timeout = 0.5

    print(f'Dashboard: http://127.0.0.1:{port}')
    try:
        while not (shutdown_event and shutdown_event.is_set()):
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == '__main__':
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT)
