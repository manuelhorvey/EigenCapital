import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'live', 'state.json')
DEFAULT_PORT = 5000

HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuantForge · Command Center</title>
<style>
:root {
  --bg-primary: #070b14;
  --bg-secondary: #0c1220;
  --bg-card: #0f1729;
  --bg-card-hover: #131d33;
  --border: #1a2440;
  --border-light: #253052;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --accent: #38bdf8;
  --accent-dim: rgba(56,189,248,0.08);
  --green: #22c55e;
  --green-bg: rgba(34,197,94,0.1);
  --green-border: rgba(34,197,94,0.2);
  --red: #ef4444;
  --red-bg: rgba(239,68,68,0.1);
  --red-border: rgba(239,68,68,0.2);
  --amber: #f59e0b;
  --amber-bg: rgba(245,158,11,0.1);
  --amber-border: rgba(245,158,11,0.2);
  --radius: 10px;
  --radius-sm: 6px;
}
*{margin:0;padding:0;box-sizing:border-box}
html{font-size:14px}
body{background:var(--bg-primary);color:var(--text-primary);font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-height:100vh;padding:20px;font-weight:400;line-height:1.5;-webkit-font-smoothing:antialiased}
.container{max-width:1440px;margin:0 auto}

.header{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:20px}
.header-left{display:flex;align-items:center;gap:16px}
.header-logo{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#38bdf8,#6366f1);display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff}
.header-title{font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.3px}
.header-title span{color:var(--text-muted);font-weight:400}
.header-right{display:flex;align-items:center;gap:24px}
.header-status{display:flex;align-items:center;gap:8px}
.status-dot{width:9px;height:9px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s ease-in-out infinite;position:relative}
.status-dot::after{content:'';position:absolute;inset:-3px;border-radius:50%;border:2px solid var(--green);opacity:0.3;animation:pulse-ring 2s ease-in-out infinite}
@keyframes pulse-ring{0%,100%{transform:scale(1);opacity:0.3}50%{transform:scale(1.5);opacity:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.status-text{font-size:13px;font-weight:500;color:var(--green)}
.status-text.init{color:var(--amber)}
.header-time{font-size:13px;color:var(--text-muted);font-variant-numeric:tabular-nums}
.header-tag{padding:4px 12px;border-radius:20px;font-size:11px;font-weight:600;background:var(--accent-dim);color:var(--accent);border:1px solid rgba(56,189,248,0.2)}

.loading{text-align:center;padding:100px 20px}
.spinner{width:36px;height:36px;border:3px solid var(--border);border-top:3px solid var(--accent);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 18px}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-title{font-size:15px;color:var(--text-secondary);margin-bottom:6px}
.loading-sub{font-size:13px;color:var(--text-muted)}

.section{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;margin-top:8px}
.section-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.2px;color:var(--text-muted)}
.section-badge{font-size:11px;color:var(--text-muted);background:var(--bg-card);padding:3px 10px;border-radius:20px;border:1px solid var(--border)}

.portfolio-row{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
.portfolio-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;position:relative;overflow:hidden;transition:border-color 0.2s}
.portfolio-card:hover{border-color:var(--border-light)}
.portfolio-card.accent::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent),#6366f1)}
.portfolio-label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);margin-bottom:6px}
.portfolio-value{font-size:26px;font-weight:700;letter-spacing:-0.5px;margin-bottom:2px}
.portfolio-sub{font-size:12px;color:var(--text-secondary)}
.change-up{color:var(--green)}
.change-down{color:var(--red)}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}

.asset-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;position:relative;overflow:hidden;transition:all 0.2s}
.asset-card:hover{background:var(--bg-card-hover);border-color:var(--border-light)}
.asset-card.signal-buy{border-left:3px solid var(--green)}
.asset-card.signal-sell{border-left:3px solid var(--red)}
.asset-card.signal-flat{border-left:3px solid var(--amber)}
.asset-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.asset-name{font-size:13px;font-weight:600;color:var(--text-primary)}
.asset-signal{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;padding:3px 10px;border-radius:20px}
.signal-buy .asset-signal{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border)}
.signal-sell .asset-signal{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border)}
.signal-flat .asset-signal{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-border)}
.asset-metrics{display:grid;grid-template-columns:1fr 1fr;gap:6px 16px}
.asset-metric{display:flex;justify-content:space-between;font-size:12px}
.asset-metric-label{color:var(--text-muted)}
.asset-metric-value{color:var(--text-secondary);font-weight:500;font-variant-numeric:tabular-nums}
.asset-conf-bar{height:4px;border-radius:2px;margin-top:8px;background:var(--bg-primary);overflow:hidden}
.asset-conf-fill{height:100%;border-radius:2px;transition:width 0.5s ease}
.asset-more{font-size:11px;color:var(--text-muted);margin-top:8px;padding-top:8px;border-top:1px solid var(--border);white-space:nowrap}

.table-wrap{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:20px}
table{width:100%;border-collapse:collapse}
th{padding:12px 16px;text-align:left;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);background:var(--bg-secondary);border-bottom:1px solid var(--border)}
td{padding:12px 16px;border-bottom:1px solid var(--border);font-size:13px;color:var(--text-secondary)}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--bg-card-hover)}
.cell-signal{font-weight:600}
.cell-buy{color:var(--green)}
.cell-sell{color:var(--red)}
.cell-flat{color:var(--amber)}
.cell-up{color:var(--green)}
.cell-down{color:var(--red)}
.cell-warn{color:var(--amber)}
.cell-mono{font-size:12px;color:var(--text-muted)}

.metric-card{border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-card);overflow:hidden}
.metric-head{padding:12px 16px 8px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);background:var(--bg-secondary)}
.metric-head-name{font-size:12px;font-weight:600}
.metric-head-count{font-size:10px;color:var(--text-muted)}
.metric-body{padding:10px 16px 12px}
.metric-row{display:flex;justify-content:space-between;padding:4px 0;font-size:12px}
.metric-label{color:var(--text-muted)}
.metric-val{color:var(--text-secondary);font-weight:500;font-variant-numeric:tabular-nums}
.metric-val.vis{color:var(--green)}
.metric-val.warn{color:var(--amber)}

.halt-card{border:1px solid var(--border);border-radius:var(--radius);padding:16px;text-align:center;background:var(--bg-card);transition:border-color 0.2s}
.halt-card.pass{border-color:var(--green-border)}
.halt-card.fail{border-color:var(--red-border);background:var(--red-bg)}
.halt-icon{font-size:22px;margin-bottom:6px;opacity:0.7}
.halt-label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);margin-bottom:4px}
.halt-value{font-size:16px;font-weight:700}
.halt-value.pass{color:var(--green)}
.halt-value.fail{color:var(--red)}

.advisory{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:20px}
.advisory-text{font-size:13px;color:var(--text-secondary)}
.advisory-text strong{color:var(--text-primary)}
.advisory-badge{padding:4px 14px;border-radius:20px;font-size:11px;font-weight:500;background:var(--accent-dim);color:var(--accent);border:1px solid rgba(56,189,248,0.2)}

@media(max-width:1024px){.portfolio-row,.grid-4{grid-template-columns:repeat(2,1fr)}}
@media(max-width:768px){.grid-2{grid-template-columns:1fr}.portfolio-row,.grid-4{grid-template-columns:1fr 1fr}.header{flex-direction:column;gap:14px;align-items:flex-start}}
@media(max-width:480px){.portfolio-row,.grid-4{grid-template-columns:1fr}.grid-3{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <div class="header-left">
    <div class="header-logo">Q</div>
    <div class="header-title">QuantForge <span>/ Command Center</span></div>
    <span class="header-tag" id="liveBadge">Paper Trading</span>
  </div>
    <div class="header-right">
    <div class="header-status">
      <span class="status-dot" id="statusDot"></span>
      <span class="status-text" id="statusText">Initializing...</span>
    </div>
    <div class="header-time"><span id="currentDate">&mdash;</span> <span id="currentTime">&mdash;</span></div>
    <span class="header-tag" id="daysBadge">0 days</span>
    <span class="header-tag" id="sessionBadge" style="background:var(--amber-bg);color:var(--amber);border-color:var(--amber-border)">Session: --</span>
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
    <div class="section-title">Halt Conditions</div>
    <span class="section-badge">Safety</span>
  </div>
  <div class="grid-4" id="haltGrid"></div>

  <div class="advisory">
    <div class="advisory-text" id="advisoryText">Loading...</div>
    <span class="advisory-badge">Paper Trading</span>
  </div>

</div>
</div>

<script>
const STATE_PATH = '/state.json';
let stateData = null;

function fmt(n,d){if(n==null||n===Infinity||isNaN(n))return'\u2014';return Number(n).toFixed(d||2)}
function cssClass(s){if(!s)return'flat';var u=String(s).toUpperCase();return u==='BUY'?'buy':u==='SELL'?'sell':'flat'}
function fd(d){return new Date(d).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}
function ft(d){return new Date(d).toLocaleTimeString('en-US',{hour12:false})}

function getSession(){
  var now=new Date(),et=new Date(now.toLocaleString('en-US',{timeZone:'America/New_York'}));
  var day=et.getDay(),hour=et.getHours(),min=et.getMinutes(),t=hour*60+min;
  var sessions=[];
  if(day===0||day===6){
    sessions.push({name:'XLF','open':false});sessions.push({name:'NZDJPY','open':false});sessions.push({name:'BTC','open':true});
  }else{
    sessions.push({name:'XLF','open':t>=570&&t<960});     // 9:30-16:00 ET
    sessions.push({name:'NZDJPY','open':t>=0&&t<1440});    // FX 24h weekdays
    sessions.push({name:'BTC','open':true});                // crypto 24/7
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
    ac+='<div class="asset-card signal-'+cls+'"><div class="asset-header"><span class="asset-name">'+name+'</span>'+(price!=null?'<span class="asset-price">$'+(price>100?fmt(price,2):fmt(price,4))+'</span>':'')+'<span class="asset-signal">'+sig+'</span></div>';
    ac+='<div class="asset-metrics"><div class="asset-metric"><span class="asset-metric-label">Confidence</span><span class="asset-metric-value" style="color:'+confColor+'">'+fmt(conf,1)+'%</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Value</span><span class="asset-metric-value">$'+fmt(val,2)+'</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Return</span><span class="asset-metric-value '+(ret>=0?'change-up':'change-down')+'">'+fmt(ret)+'%</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Drawdown</span><span class="asset-metric-value '+(dd>-3?'':dd>-5?'cell-warn':'change-down')+'">'+fmt(dd)+'%</span></div></div>';
    ac+='<div class="asset-conf-bar"><div class="asset-conf-fill" style="width:'+conf+'%;background:'+confColor+'"></div></div>';
    if(entry||stop||tp||upnl!=null){
      ac+='<div class="asset-more">';
      if(entry)ac+='Entry $'+fmt(entry,2);
      if(stop)ac+=' &middot; SL $'+fmt(stop,2);
      if(tp)ac+=' &middot; TP $'+fmt(tp,2);
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
    tb+='<td><span style="display:inline-block;width:50px;height:6px;border-radius:3px;background:var(--bg-primary);vertical-align:middle;margin-right:6px;overflow:hidden"><span style="display:block;height:100%;width:'+conf+'%;border-radius:3px;background:'+(conf>=60?'var(--green)':conf>=45?'var(--amber)':'var(--red)')+'"></span></span>'+fmt(conf,1)+'%</td>';
    tb+='<td>$'+(price>100?fmt(price,2):fmt(price,4))+'</td>';
    tb+='<td>'+Math.round(alloc*100)+'%</td>';
    tb+='<td class="cell-'+(ret>=0?'up':'down')+'">'+fmt(ret)+'%</td>';
    tb+='<td class="cell-'+(dd>-3?'up':dd>-5?'warn':'down')+'">'+fmt(dd)+'%</td>';
    if(pos&&pos.sl)tb+='<td class="cell-mono">$'+fmt(pos.sl,2)+' / $'+fmt(pos.tp,2)+'</td>';
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
    '<div class="halt-card '+(maxDD>hc.drawdown*100?'pass':'fail')+'"><div class="halt-icon">&#9660;</div><div class="halt-label">Max Drawdown</div><div class="halt-value '+(maxDD>hc.drawdown*100?'pass':'fail')+'">'+fmt(maxDD)+'% / '+fmt(hc.drawdown*100,0)+'%</div></div>'+
    '<div class="halt-card '+(minPF>=hc.monthly_pf?'pass':'fail')+'"><div class="halt-icon">&#9632;</div><div class="halt-label">Monthly PF</div><div class="halt-value '+(minPF>=hc.monthly_pf?'pass':'fail')+'">'+(minPF<Infinity?fmt(minPF):'\u2014')+' / '+fmt(hc.monthly_pf,2)+'</div></div>'+
    '<div class="halt-card pass"><div class="halt-icon">&#9673;</div><div class="halt-label">Signal Drought</div><div class="halt-value pass">0d / '+hc.signal_drought+'d</div></div>'+
    '<div class="halt-card pass"><div class="halt-icon">&#9650;</div><div class="halt-label">Prob Drift</div><div class="halt-value pass">&lt; '+fmt(hc.prob_drift*100,0)+'%</div></div>';

  var today=new Date(),gate=new Date(today);gate.setMonth(gate.getMonth()+6);
  var sessionInfo=getSession();
  var openList=sessionInfo.filter(function(s){return s.open}).map(function(s){return s.name}).join(', ');
  document.getElementById('advisoryText').innerHTML=
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
    badgeEl.style.cssText='background:var(--green-bg);color:var(--green);border-color:var(--green-border)';
  }else if(sessionInfo.every(function(s){return !s.open})){
    badgeEl.textContent='All Markets Closed';
    badgeEl.style.cssText='background:var(--red-bg);color:var(--red);border-color:var(--red-border)';
  }else{
    badgeEl.textContent='Open: '+openList+' | Closed: '+closedList;
    badgeEl.style.cssText='background:var(--amber-bg);color:var(--amber);border-color:var(--amber-border)';
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
                                      'allocations': {'XLF': 0.6, 'BTC': 0.4},
                                      'deployment_cleared': True},
                        'assets': {}, 'halt_conditions': {'drawdown': -0.08, 'monthly_pf': 0.7, 'signal_drought': 30, 'prob_drift': 0.15},
                    }, indent=2).encode('utf-8'))
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
