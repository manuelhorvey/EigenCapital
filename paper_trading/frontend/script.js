const STATE_PATH = '/state.json';
let stateData = null;
var tradeData = [];
var prevPositions = {};
var newBadgeTimers = {};
var equityHistory = [];
var lastUpdateTime = null;
var logsVisible = false;
var logFetchFailCount = 0;

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
    var ret=t['return']!=null&&!isNaN(t['return'])?t['return']:0,retPct=(ret*100).toFixed(2);
    var side=(t.side||'').toUpperCase(),sideClass=side==='LONG'?'cell-buy':side==='SHORT'?'cell-sell':'';
    var bars='\u2014';
    if(t.entry_date&&t.exit_date){var d1=new Date(t.entry_date),d2=new Date(t.exit_date);if(!isNaN(d1.getTime())&&!isNaN(d2.getTime())){var diff=Math.max(1,Math.round((d2-d1)/(864e5)));bars=diff+'d'}}
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

function getSession(state){
  var assets = state ? state.assets : (stateData ? stateData.assets : {});
  var now=new Date(),et=new Date(now.toLocaleString('en-US',{timeZone:'America/New_York'}));
  var day=et.getDay(),hour=et.getHours(),min=et.getMinutes(),t=hour*60+min;
  var fxOpen=t>=0&&t<1440;
  var sessions=[];
  for(var name in assets){
    var isCrypto = name.indexOf('BTC') !== -1 || name.indexOf('ETH') !== -1;
    if(day===6){
      sessions.push({name:name,'open':isCrypto});
    }else if(day===0){
      sessions.push({name:name,'open':isCrypto?true:t>=1020});
    }else{
      sessions.push({name:name,'open':isCrypto?true:fxOpen});
    }
  }
  return sessions;
}

function render(state){
  var assets=state.assets||{},p=state.portfolio||{};
  var totalValue=p.total_value||0,totalReturn=p.total_return||0,capital=p.capital||0,days=p.days_running||0;
  var startDate=p.start_date||null,nTrades=0,maxDD=0,minPF=Infinity;
  for(var k in assets){var m=assets[k].metrics||{};nTrades+=(m.n_trades||0);if(m.drawdown<maxDD)maxDD=m.drawdown;if(m.monthly_pf!=null&&m.monthly_pf<minPF)minPF=m.monthly_pf}
  var totalPnlPct=0;for(var k in assets){var pos=(assets[k].metrics||{}).position;if(pos&&pos.unrealized_pnl!=null)totalPnlPct+=pos.unrealized_pnl}
  totalPnlPct=totalPnlPct/Object.keys(assets).length||0;
  var totalPnlDollars=p.unrealized_pnl||0;

  var openPos=p.open_positions||0,closedPos=p.closed_trades||0;
  var realizedPct=p.realized_return!=null?p.realized_return:0;
  var runtimeStr='\u2014';
  if(days>0){runtimeStr=days+' days'}else if(p.start_datetime){var sd=new Date(p.start_datetime);if(!isNaN(sd.getTime())&&sd.getTime()>0){var elapsedH=(Date.now()-sd.getTime())/36e5;runtimeStr=Math.floor(elapsedH)+'h '+Math.round((elapsedH%1)*60)+'m'}}

  document.getElementById('portfolioRow').innerHTML=
    '<div class="portfolio-card accent"><div class="portfolio-label">Portfolio Value</div><div class="portfolio-value" style="color:var(--accent)">$'+fmt(totalValue,2)+'</div><div class="portfolio-sub">Capital: $'+fmt(capital,2)+'</div></div>'+
    '<div class="portfolio-card"><div class="portfolio-label">Total Return</div><div class="portfolio-value '+(totalReturn>=0?'change-up':'change-down')+'">'+fmt(totalReturn)+'%</div><div class="portfolio-sub">Run: '+runtimeStr+'</div></div>'+
    '<div class="portfolio-card"><div class="portfolio-label">Unrealized P&amp;L</div><div class="portfolio-value '+(totalPnlDollars>=0?'change-up':'change-down')+'">$'+fmt(totalPnlDollars,2)+'</div><div class="portfolio-sub">Realized: '+(realizedPct>=0?'+':'')+fmt(realizedPct)+'% &middot; Avg '+fmt(totalPnlPct,2)+'%</div></div>'+
    '<div class="portfolio-card"><div class="portfolio-label">Positions</div><div class="portfolio-value" style="color:var(--text-primary)">'+openPos+'</div><div class="portfolio-sub">Open: '+openPos+' | Closed: '+closedPos+'</div></div>';

  var cnt=0,ac='';
  for(var name in assets){
    cnt++;
    var d=assets[name],m=d.metrics||{},s=d.last_signal;
    var sig=s?s.signal:'FLAT',conf=s?s.confidence||0:0,cls=cssClass(sig);
    var entry=null,stop=null,tp=null,upnl=null;
    var pos=m.position;
    if(pos){entry=pos.entry;stop=pos.sl;tp=pos.tp;upnl=pos.unrealized_pnl}
    var val=m.current_value||0,ret=m.mtm_return!=null&&!isNaN(m.mtm_return)?m.mtm_return:(m.total_return||0),dd=m.drawdown||0;
    var confColor=conf>=60?'var(--green)':conf>=45?'var(--amber)':'var(--red)';
    var price=s&&s.close_price!=null&&!isNaN(s.close_price)?s.close_price:null;
    var prevPos=prevPositions[name],isNewEntry=pos&&pos.entry!=null&&!isNaN(pos.entry)&&(!prevPos||prevPos.entry!==pos.entry);
    if(isNewEntry){newBadgeTimers[name]=60}
    if(!isNewEntry&&newBadgeTimers[name]>0){newBadgeTimers[name]--}
    prevPositions[name]=pos?{entry:pos.entry}:null;
    var newBadge=newBadgeTimers[name]>0?'<span class="new-badge">New</span>':'';
    var curSLM = m.current_sl_mult, curTPM = m.current_tp_mult;
    var geomStr = curSLM && curTPM ? ' <span style="font-size:0.8em;opacity:0.6;font-weight:normal">('+fmt(curSLM,2)+'x / '+fmt(curTPM,2)+'x)</span>' : '';
    ac+='<div class="asset-card signal-'+cls+'"><div class="asset-header"><span class="asset-name">'+name+newBadge+'</span>'+(price!=null?'<span class="asset-price">$'+fmtPrice(price)+'</span>':'')+'<span class="asset-signal">'+sig+'</span></div>';
    ac+='<div class="asset-metrics"><div class="asset-metric"><span class="asset-metric-label">Confidence</span><span class="asset-metric-value" style="color:'+confColor+'">'+fmt(conf,1)+'%</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Value</span><span class="asset-metric-value">$'+fmt(val,2)+'</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Return</span><span class="asset-metric-value '+(ret>=0?'change-up':'change-down')+'">'+fmt(ret)+'%</span></div>';
    ac+='<div class="asset-metric"><span class="asset-metric-label">Drawdown</span><span class="asset-metric-value '+(dd>-3?'':dd>-5?'cell-warn':'change-down')+'">'+fmt(dd)+'%</span></div></div>';
    ac+='<div class="asset-conf-bar"><div class="asset-conf-fill" style="width:'+conf+'%;background:'+confColor+'"></div></div>';
    var lt=getLastTrade(name);
    ac+='<canvas class="asset-spark" width="180" height="24" data-asset="'+name+'"></canvas>';
    if(lt){var lri=resultInfo(lt.reason),lret=lt['return']!=null?(lt['return']*100).toFixed(2):'0.00',lside=(lt.side||'').toUpperCase();ac+='<div class="asset-last-trade">Last: '+lside+' <span class="'+lri.cls+'">'+(lt['return']>=0?'+':'')+lret+'% ('+lri.text+')</span></div>'}
    if(entry||stop||tp||upnl!=null){
      var pSLM = pos.sl_mult, pTPM = pos.tp_mult;
      var pGeom = pSLM && pTPM ? ' <span style="opacity:0.6">['+fmt(pSLM,2)+' / '+fmt(pTPM,2)+']</span>' : '';
      ac+='<div class="asset-more">';
      if(entry)ac+='Entry $'+fmtPrice(entry);
      if(stop)ac+=' &middot; SL $'+fmtPrice(stop);
      ac+='</div><div class="asset-more">';
      if(tp)ac+='TP $'+fmtPrice(tp);
      if(upnl!=null)ac+=' &middot; P&L <span style="color:'+(upnl>=0?'var(--green)':'var(--red)')+'">'+fmt(upnl,2)+'%</span>'+pGeom;
      ac+='</div>';
    }else{
      ac+='<div class="asset-more" style="text-align:center;margin-top:8px;border-top:1px solid var(--surface-elevated);padding-top:4px">Regime Geometry: '+geomStr+'</div>';
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
    var curSLM = m.current_sl_mult, curTPM = m.current_tp_mult;
    var geomStr = curSLM && curTPM ? '<br><span style="font-size:0.75em;opacity:0.5">'+fmt(curSLM,2)+'x / '+fmt(curTPM,2)+'x</span>' : '';

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
  var sessionInfo=getSession(state);
  var openList=sessionInfo.filter(function(s){return s.open}).map(function(s){return s.name}).join(', ');
  document.getElementById('footerText').innerHTML=
    '<strong>Next retrain:</strong> '+fd(new Date(today.getFullYear()+1,0,1))+
    ' &middot; <strong>Started:</strong> '+(p.start_date?fd(new Date(p.start_date)):'\u2014')+
    ' &middot; <strong>6-month gate:</strong> '+fd(gate)+
    ' &middot; <strong>Cleared:</strong> '+(p.deployment_cleared?'Yes':'No')+
    ' &middot; <strong>Refresh:</strong> 30s'+
    ' &middot; <strong>Sessions:</strong> '+openList+' trading';
  document.getElementById('daysBadge').textContent=runtimeStr;
  var liveCount=0;for(var k in assets){if((assets[k].last_signal||{}).signal)liveCount++}
  document.getElementById('liveBadge').textContent=liveCount+' assets live';
  document.getElementById('statusText').textContent='Live Market Feed Active';
  document.getElementById('statusText').className='status-text';

  var sessionInfo=getSession(state);
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

function drawSparkline(canvas, values, color){
  if(!canvas||!values||values.length<2)return;
  var ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
  var mn=Infinity,mx=-Infinity;
  for(var i=0;i<values.length;i++){
    var v=values[i];
    if(v!=null&&!isNaN(v)&&v!==Infinity&&v!==-Infinity){
      if(v<mn)mn=v;if(v>mx)mx=v;
    }
  }
  if(mn===Infinity||mx===mn){ctx.clearRect(0,0,w,h);return}
  var pad=2,drawW=w-pad*2,drawH=h-pad*2;
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle=color;
  ctx.lineWidth=1.5;
  ctx.lineJoin='round';
  ctx.lineCap='round';
  ctx.beginPath();
  for(var i=0;i<values.length;i++){
    var v=values[i];
    if(v==null||isNaN(v)||v===Infinity||v===-Infinity)continue;
    var x=pad+(i/(values.length-1))*drawW;
    var y=pad+(1-(v-mn)/(mx-mn))*drawH;
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  }
  ctx.stroke();
}

function renderEquityCurve(){
  if(!equityHistory||equityHistory.length<2)return;
  var canvas=document.getElementById('equityCanvas');
  if(!canvas)return;
  document.getElementById('equityCount').textContent=equityHistory.length+' points';
  var values=equityHistory.map(function(e){return e.portfolio_value});
  drawSparkline(canvas,values,'var(--accent)');
}

function renderAssetSparklines(){
  if(!equityHistory||equityHistory.length<2)return;
  var canvases=document.querySelectorAll('.asset-spark');
  for(var ci=0;ci<canvases.length;ci++){
    var cv=canvases[ci],name=cv.getAttribute('data-asset');
    if(!name)continue;
    var values=[];
    for(var i=0;i<equityHistory.length;i++){
      var av=equityHistory[i].assets?equityHistory[i].assets[name]:null;
      if(av!=null&&!isNaN(av))values.push(av);
    }
    if(values.length>=2){
      drawSparkline(cv,values,'var(--text-muted)');
    }
  }
}

async function fetchEquityHistory(){
  try{
    var r=await fetch('/equity_history.json?t='+Date.now());
    if(!r.ok)return;
    var data=await r.json();
    if(Array.isArray(data)&&data.length>0){
      equityHistory=data;
      renderEquityCurve();
      renderAssetSparklines();
    }
  }catch(e){}
}

function updateAgeDisplay(){
  if(!lastUpdateTime){document.getElementById('updateAgePill').textContent='Updated --s ago';return}
  var elapsed=Math.floor((Date.now()-lastUpdateTime)/1000);
  var pill=document.getElementById('updateAgePill');
  if(elapsed<30){
    pill.textContent='Updated '+elapsed+'s ago';
    pill.style.cssText='background:var(--green-dim);color:var(--green);border-color:var(--green-border)';
  }else if(elapsed<90){
    pill.textContent='Updated '+elapsed+'s ago';
    pill.style.cssText='background:var(--amber-dim);color:var(--amber);border-color:var(--amber-border)';
  }else{
    pill.textContent='Updated '+elapsed+'s ago';
    pill.style.cssText='background:var(--red-dim);color:var(--red);border-color:var(--red-border)';
  }
}

function toggleLogs(){
  var content=document.getElementById('logContent');
  var toggle=document.getElementById('logToggle');
  logsVisible=!logsVisible;
  content.style.display=logsVisible?'block':'none';
  toggle.textContent=logsVisible?'\u25BC':'\u25B6';
  if(logsVisible)fetchLogs();
}

async function fetchLogs(){
  try{
    var r=await fetch('/logs?t='+Date.now());
    if(!r.ok)return;
    var text=await r.text();
    document.getElementById('logContent').textContent=text;
    var lines=text.split('\n').length;
    document.getElementById('logLineCount').textContent=lines+' lines';
    logFetchFailCount=0;
  }catch(e){
    logFetchFailCount++;
    if(logFetchFailCount>3){
      document.getElementById('logContent').textContent='[log unavailable after '+logFetchFailCount+' retries]';
    }
  }
}

async function fetchAndRenderHealth(){
  try{
    var r=await fetch('/health.json?t='+Date.now());
    if(!r.ok)return;
    var data=await r.json();
    var assets=data.assets||{},sys=data.system_health||{};
    var hhtml='';
    for(var name in assets){
      var h=assets[name],score=h.health_score||0,label=h.health_label||'UNKNOWN',color=h.health_color||'grey';
      var pct=(score*100).toFixed(0);
      var bgColor=color==='green'?'var(--green)':color==='amber'?'var(--amber)':'var(--red)';
      var bgDim=color==='green'?'var(--green-dim)':color==='amber'?'var(--amber-dim)':'var(--red-dim)';
      var borderColor=color==='green'?'var(--green-border)':color==='amber'?'var(--amber-border)':'var(--red-border)';
      hhtml+='<div class="health-card" style="background:'+bgDim+';border-color:'+borderColor+'">';
      hhtml+='<div class="health-name">'+name+'</div>';
      hhtml+='<div class="health-value" style="color:'+bgColor+'">'+pct+'%</div>';
      hhtml+='<div class="health-bar"><div class="health-bar-fill" style="width:'+pct+'%;background:'+bgColor+'"></div></div>';
      hhtml+='<div class="health-label" style="color:'+bgColor+'">'+label+'</div>';
      var comps=h.components||{};
      hhtml+='<div class="health-comps">';
      for(var k in comps){
        var cv=(comps[k]*100).toFixed(0);
        var cc=cv>=70?'var(--green)':cv>=45?'var(--amber)':'var(--red)';
        hhtml+='<span class="health-comp" style="color:'+cc+'">'+k.substring(0,4)+' '+cv+'%</span>';
      }
      hhtml+='</div></div>';
    }
    document.getElementById('healthGrid').innerHTML=hhtml;
    if(sys.n_assets){
      document.getElementById('healthSystem').innerHTML=
        '<span class="system-health-pill">System: '+(sys.mean_health_score*100).toFixed(0)+'% &middot; '+
        sys.n_healthy+' healthy &middot; '+sys.n_degraded+' degraded &middot; '+sys.n_critical+' critical</span>';
    }
  }catch(e){}
}

var _origFetch=window.fetchState;
fetchState=async function(){
  await _origFetch();
  fetchEquityHistory();
  fetchAndRenderHealth();
};
var _origRender=render;
render=function(state){
  _origRender(state);
  var p=state.portfolio||{};
  if(p.last_update){
    var ts=new Date(p.last_update.replace(' ','T'));
    if(!isNaN(ts.getTime()))lastUpdateTime=ts.getTime();
  }
};

var _origFetchState=fetchState;
fetchState=async function(){
  await _origFetchState();
  fetchEquityHistory();
};

setTimeout(fetchState,1000);
setInterval(fetchState,30000);
setInterval(function(){
  var n=new Date();
  document.getElementById('currentDate').textContent=fd(n);
  document.getElementById('currentTime').textContent=ft(n);
  updateAgeDisplay();
},1000);
setInterval(fetchLogs,15000);
