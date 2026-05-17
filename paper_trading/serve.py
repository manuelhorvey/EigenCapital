import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'live', 'state.json')
DEFAULT_PORT = 5000

HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuantForge · Paper Trading</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0e17;color:#c8d6e5;font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:13px;min-height:100vh;padding:16px}
.container{max-width:1400px;margin:0 auto}

.header{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;background:linear-gradient(135deg,#0d1520,#162033);border:1px solid #1e3a5f;border-radius:8px;margin-bottom:16px}
.header-left{display:flex;align-items:center;gap:16px}
.header-title{font-size:18px;font-weight:700;color:#4fc3f7;letter-spacing:1px}
.header-title span{color:#7c4dff}
.header-badge{padding:4px 10px;border-radius:4px;font-size:11px;font-weight:600;background:#1b5e20;color:#81c784;border:1px solid #2e7d32}
.header-right{display:flex;align-items:center;gap:20px}
.header-time{color:#78909c;font-size:13px}
.header-time .date{color:#b0bec5}
.status-dot{width:8px;height:8px;border-radius:50%;background:#4caf50;display:inline-block;animation:pulse 2s ease-in-out infinite;margin-right:6px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.status-text{color:#81c784;font-size:12px}
.status-text.init{color:#ffa726}

.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.card{background:linear-gradient(135deg,#0d1520,#111d2e);border:1px solid #1a2d44;border-radius:8px;padding:16px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#4fc3f7,transparent)}
.card-title{font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#546e7a;margin-bottom:8px}
.card-value{font-size:24px;font-weight:700;margin-bottom:4px}
.card-sub{font-size:11px;color:#78909c}
.card-buy .card-value,.card-buy .card-title{color:#4caf50}
.card-sell .card-value,.card-sell .card-title{color:#ef5350}
.card-flat .card-value,.card-flat .card-title{color:#ffa726}

.section-title{font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#546e7a;margin-bottom:10px;padding-left:4px}

table{width:100%;border-collapse:collapse;margin-bottom:16px;background:#0d1520;border:1px solid #1a2d44;border-radius:8px;overflow:hidden}
th{padding:10px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#546e7a;background:#0a111f;border-bottom:1px solid #1a2d44;font-weight:600}
td{padding:10px 12px;border-bottom:1px solid #111d2e;font-size:13px}
tr:last-child td{border-bottom:none}
tr:hover{background:rgba(79,195,247,0.03)}
.signal-buy{color:#4caf50;font-weight:700}
.signal-sell{color:#ef5350;font-weight:700}
.signal-flat{color:#ffa726}
.conf-bar{display:inline-block;height:6px;border-radius:3px;min-width:10px;vertical-align:middle;margin-right:6px}

.metrics-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.metric-card{background:#0d1520;border:1px solid #1a2d44;border-radius:8px;padding:14px}
.metric-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.metric-title{font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#546e7a}
.metric-row{display:flex;justify-content:space-between;padding:4px 0;font-size:12px}
.metric-label{color:#78909c}
.metric-value{color:#b0bec5;font-weight:600}
.metric-value.ok{color:#4caf50}
.metric-value.warn{color:#ffa726}
.metric-value.fail{color:#ef5350}

.halt-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.halt-card{background:#0d1520;border:1px solid #1a2d44;border-radius:8px;padding:12px;text-align:center}
.halt-icon{font-size:20px;margin-bottom:4px}
.halt-label{font-size:10px;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
.halt-value{font-size:16px;font-weight:700}
.halt-value.pass{color:#4caf50}
.halt-value.fail{color:#ef5350}

.advisory{background:linear-gradient(135deg,#0d1520,#0f1a2b);border:1px solid #1a2d44;border-radius:8px;padding:14px 18px;display:flex;justify-content:space-between;align-items:center;margin-top:8px}
.advisory-text{color:#78909c;font-size:12px}
.advisory-text strong{color:#b0bec5}
.advisory-badge{padding:4px 12px;border-radius:4px;font-size:11px;background:rgba(79,195,247,0.1);color:#4fc3f7;border:1px solid rgba(79,195,247,0.3)}

.loading{text-align:center;padding:80px 20px;color:#546e7a}
.spinner{width:32px;height:32px;border:3px solid #1a2d44;border-top:3px solid #4fc3f7;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}

@media(max-width:900px){.cards,.halt-grid{grid-template-columns:repeat(2,1fr)}.metrics-grid{grid-template-columns:1fr}.header{flex-direction:column;gap:12px}}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <div class="header-left">
    <div class="header-title">&#9889; QuantForge <span>&middot;</span> Paper Trading</div>
    <div class="header-badge" id="liveBadge">COMMAND CENTER</div>
  </div>
  <div class="header-right">
    <div><span class="status-dot" id="statusDot"></span><span class="status-text" id="statusText">Loading...</span></div>
    <div class="header-time"><span class="date" id="currentDate">&mdash;</span> &middot; <span id="currentTime">&mdash;</span></div>
    <div class="header-badge" id="daysBadge">0 days</div>
  </div>
</div>

<div id="loadingState" class="loading">
  <div class="spinner"></div>
  <div style="font-size:14px;margin-bottom:8px;">Connecting to paper trading engine...</div>
  <div style="font-size:12px;color:#546e7a;" id="loadingDetail">waiting for signal data</div>
</div>

<div id="dashboardContent" style="display:none;">
  <div class="cards" id="assetCards"></div>
  <div class="section-title">Execution Tickets</div>
  <table><thead><tr>
    <th>Asset</th><th>Regime</th><th>Signal</th><th>Confidence</th>
    <th>Close Price</th><th>Allocation</th><th>Total Return</th><th>Drawdown</th><th>SL / TP</th>
  </tr></thead><tbody id="signalsBody"></tbody></table>
  <div class="section-title">Live Metrics</div>
  <div class="metrics-grid" id="metricsGrid"></div>
  <div class="section-title">Halt Conditions</div>
  <div class="halt-grid" id="haltGrid"></div>
  <div class="advisory">
    <div class="advisory-text" id="advisoryText">Loading...</div>
    <span class="advisory-badge">Paper Trading</span>
  </div>
</div>
</div>

<script>
const STATE_PATH = '/state.json';
let stateData = null;

function fmt(n,d){if(n==null||n===Infinity)return'\u2014';return Number(n).toFixed(d||2)}
function sc(s){if(!s)return'flat';var u=String(s).toUpperCase();return u==='BUY'?'buy':u==='SELL'?'sell':'flat'}
function sl(s){if(!s)return'FLAT';return String(s).toUpperCase()}
function cc(c){return c>=60?'#4caf50':c>=45?'#ffa726':'#ef5350'}
function fd(d){return new Date(d).toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric'})}
function ft(d){return new Date(d).toLocaleTimeString('en-US',{hour12:false})}

function render(state){
  var assets=state.assets||{},p=state.portfolio||{};
  var cards='',i=0;
  for(var name in assets){
    var d=assets[name],m=d.metrics||{},s=d.last_signal,pos=m.position;
    var sig=s?s.signal:'FLAT',conf=s?s.confidence||0:0;
    var entry=pos?pos.entry:(s?s.close_price:null);
    var sl=pos?pos.sl:null,tp=pos?pos.tp:null;
    cards+='<div class="card card-'+sc(sig)+'"><div class="card-title">'+name+' &middot; '+sl(sig)+'</div>';
    cards+='<div class="card-value">'+fmt(conf,1)+'%</div>';
    cards+='<div class="card-sub">Value: $'+fmt(m.current_value)+' | Ret: '+fmt(m.total_return)+'% | DD: '+fmt(m.drawdown)+'%</div>';
    if(entry){
      cards+='<div class="card-sub" style="margin-top:4px;font-size:10px">';
      cards+='Entry: $'+fmt(entry,2);
      if(sl)cards+=' | SL: $'+fmt(sl,2);
      if(tp)cards+=' | TP: $'+fmt(tp,2);
      if(pos&&pos.unrealized_pnl!=null)cards+=' | P&L: <span style="color:'+(pos.unrealized_pnl>=0?'#4caf50':'#ef5350')+'">'+fmt(pos.unrealized_pnl,2)+'%</span>';
      cards+='</div>';
    }
    cards+='</div>';
  cards+='<div class="card"><div class="card-title">Portfolio</div>';
  cards+='<div class="card-value" style="color:#4fc3f7">$'+fmt(p.total_value)+'</div>';
  cards+='<div class="card-sub">Ret: '+fmt(p.total_return)+'% | Capital: $'+fmt(p.capital)+' | '+p.days_running+' days</div></div>';
  document.getElementById('assetCards').innerHTML=cards;

  var tb='';
  for(var name in assets){
    var d=assets[name],m=d.metrics||{},s=d.last_signal;
    var sig=s?s.signal:'FLAT',conf=s?s.confidence||0:0,price=s?s.close_price:0,date=s?s.date:'\u2014';
    var alloc=Math.round((p.allocations?p.allocations[name]:0.25)*100)+'%';
    var scls=sc(sig);
    tb+='<tr><td><strong>'+name+'</strong></td>';
    tb+='<td style="color:#78909c">'+(sig==='BUY'?'Bullish':sig==='SELL'?'Bearish':'Neutral')+'</td>';
    tb+='<td class="signal-'+scls+'">'+sl(sig)+'</td>';
    tb+='<td><span class="conf-bar" style="width:'+Math.max(conf*0.6,5)+'px;background:'+cc(conf)+'"></span>'+fmt(conf,1)+'%</td>';
    tb+='<td>$'+(price>100?fmt(price,2):fmt(price,4))+'</td>';
    var pos=m.position;
    tb+='<td>'+alloc+'</td>';
    tb+='<td style="color:'+(m.total_return>=0?'#4caf50':'#ef5350')+'">'+fmt(m.total_return)+'%</td>';
    tb+='<td style="color:'+(m.drawdown>-3?'#4caf50':m.drawdown>-5?'#ffa726':'#ef5350')+'">'+fmt(m.drawdown)+'%</td>';
    if(pos&&pos.sl)tb+='<td style="font-size:10px;color:#78909c">$'+fmt(pos.sl,2)+' / $'+fmt(pos.tp,2)+'</td>';
    else tb+='<td style="font-size:10px;color:#546e7a">\u2014</td></tr>';
  }
  document.getElementById('signalsBody').innerHTML=tb;

  var mg='';
  for(var name in assets){
    var d=assets[name],m=d.metrics||{},pf=m.profit_factor;
    var pfStr=(pf!=null&&pf!=Infinity)?fmt(pf):'\u2014';
    var monthlyPf=m.monthly_pf;var mpfStr=(monthlyPf!=null&&monthlyPf!=Infinity)?fmt(monthlyPf):'\u2014';
    mg+='<div class="metric-card"><div class="metric-header"><span class="metric-title">'+name+'</span><span style="font-size:10px;color:#78909c">'+m.n_trades+' trades</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Profit Factor</span><span class="metric-value '+(pfStr!='\u2014'&&parseFloat(pfStr)>=1?'ok':'')+'">'+pfStr+'</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Win Rate</span><span class="metric-value">'+fmt(m.win_rate)+'%</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Signal Dist (B/S/F)</span><span class="metric-value">'+(m.signal_distribution?m.signal_distribution.BUY||0+'/'+m.signal_distribution.SELL||0+'/'+m.signal_distribution.FLAT||0:'0/0/0')+'</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Mean Confidence</span><span class="metric-value">'+fmt(m.mean_confidence)+'%</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">P(Long)/P(Short)</span><span class="metric-value">'+fmt(m.mean_prob_long)+'% / '+fmt(m.mean_prob_short)+'%</span></div>';
    mg+='<div class="metric-row"><span class="metric-label">Monthly PF</span><span class="metric-value '+(monthlyPf!=null&&monthlyPf>=0.7?'ok':'warn')+'">'+mpfStr+'</span></div></div>';
  }
  document.getElementById('metricsGrid').innerHTML=mg;

  var maxDD=0,minPF=Infinity,hc=state.halt_conditions||{drawdown:-0.08,monthly_pf:0.7,signal_drought:30,prob_drift:0.15};
  for(var name in assets){var m=(assets[name].metrics||{});if(m.drawdown<maxDD)maxDD=m.drawdown;if(m.monthly_pf!=null&&m.monthly_pf<minPF)minPF=m.monthly_pf}
  document.getElementById('haltGrid').innerHTML=
    '<div class="halt-card"><div class="halt-icon">&#128201;</div><div class="halt-label">Max Drawdown</div><div class="halt-value '+(maxDD>-8?'pass':'fail')+'">'+fmt(maxDD)+'% / '+fmt(hc.drawdown*100,0)+'%</div></div>'+
    '<div class="halt-card"><div class="halt-icon">&#128202;</div><div class="halt-label">Monthly PF</div><div class="halt-value '+(minPF>=0.7?'pass':'fail')+'">'+(minPF<Infinity?fmt(minPF):'\u2014')+' / '+fmt(hc.monthly_pf,2)+'</div></div>'+
    '<div class="halt-card"><div class="halt-icon">&#128263;</div><div class="halt-label">Signal Drought</div><div class="halt-value pass">0d / '+hc.signal_drought+'d</div></div>'+
    '<div class="halt-card"><div class="halt-icon">&#127919;</div><div class="halt-label">Prob Drift</div><div class="halt-value pass">&lt; '+fmt(hc.prob_drift*100,0)+'%</div></div>';

  var today=new Date(),gate=new Date(today);gate.setMonth(gate.getMonth()+6);
  var retrain=new Date(today.getFullYear()+1,0,1);
  document.getElementById('advisoryText').innerHTML=
    '<strong>Next retrain:</strong> '+fd(retrain)+' &middot; <strong>Started:</strong> '+(p.start_date?fd(p.start_date):'\u2014')+
    ' &middot; <strong>6-month gate:</strong> '+fd(gate)+' &middot; <strong>Cleared:</strong> '+(p.deployment_cleared?'&#10003; YES':'&#10007; NO')+
    ' &middot; <strong>Refresh:</strong> every 30s';
  document.getElementById('liveBadge').textContent='COMMAND CENTER';
  document.getElementById('daysBadge').textContent=p.days_running+' days';
  document.getElementById('statusText').textContent='Live Market Feed Active';
  document.getElementById('statusText').className='status-text';
  document.getElementById('statusDot').style.background='#4caf50';
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
    document.getElementById('statusDot').style.background='#ffa726';
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
