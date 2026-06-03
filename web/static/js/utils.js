// Shared utilities: auth, theme, WebSocket, drawer
function getTheme(){return localStorage.getItem('theme')||'light';}
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);var b=document.getElementById('theme-toggle');b.innerHTML=t==='dark'?'☼':'☾';}
function toggleTheme(){var n=getTheme()==='dark'?'light':'dark';localStorage.setItem('theme',n);applyTheme(n);}
applyTheme(getTheme());

async function checkAuth(){
try{var r=await fetch('/api/health');if(r.status===401){document.getElementById('login-overlay').classList.add('show');return false;}return true;}catch(e){return true;}}

async function doLogin(){
var t=document.getElementById('login-token').value.trim();if(!t)return;
try{var r=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t})});
if(r.ok){document.getElementById('login-overlay').classList.remove('show');document.getElementById('login-error').style.display='none';}
else{document.getElementById('login-error').style.display='block';}}catch(e){document.getElementById('login-error').style.display='block';}}

var wsProtocol=location.protocol==='https:'?'wss:':'ws:';
var ws=new WebSocket(wsProtocol+'//'+location.host+'/ws');
ws.onopen=function(){document.getElementById('ws-dot').classList.remove('offline');document.getElementById('ws-text').textContent='在线';};
ws.onclose=function(){document.getElementById('ws-dot').classList.add('offline');document.getElementById('ws-text').textContent='离线';};
ws.onmessage=function(e){var d=JSON.parse(e.data);if(d.type==='pipeline_update'){if(d.chart_data){var s=d.chart_data.site_name;echartSiteData[s]=d.chart_data;var sel=document.getElementById('echart-site');if(sel&&!Array.from(sel.options).some(function(o){return o.value===s;})){sel.innerHTML+='<option value="'+s+'">'+s+'</option>';}if(s===echartCurrentSite||!echartCurrentSite){if(!echartCurrentSite){echartCurrentSite=s;if(sel)sel.value=s;}renderAllCharts(d.chart_data);}}loadStats();loadCharts();loadItems(itemsPage);loadRuns();}};
setInterval(function(){if(ws.readyState===WebSocket.OPEN)ws.send('ping');},30000);
setInterval(function(){document.getElementById('clock').textContent=new Date().toLocaleTimeString();},1000);

var currentDrawer=null;
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open');}
function focusChat(){closeDrawer();document.getElementById('chat-input').focus();}
function openDrawer(name){
currentDrawer=name;
document.querySelectorAll('.sidebar-item[data-drawer]').forEach(function(el){el.classList.toggle('active',el.dataset.drawer===name);});
document.getElementById('drawer-overlay').classList.add('show');
document.getElementById('drawer').classList.add('show');
var titles={monitor:'新闻监控',papers:'论文追踪',deep:'深度分析',ops:'运营管理'};
document.getElementById('drawer-title').textContent=titles[name]||'';
renderDrawerContent(name);}

function closeDrawer(){
currentDrawer=null;
document.querySelectorAll('.sidebar-item[data-drawer]').forEach(function(el){el.classList.remove('active');});
var cb=document.querySelector('.sidebar-item[data-drawer=chat]');
if(cb)cb.classList.add('active');
document.getElementById('drawer-overlay').classList.remove('show');
document.getElementById('drawer').classList.remove('show');}

function renderDrawerContent(name){
var body=document.getElementById('drawer-body');
switch(name){
case'monitor':body.innerHTML=drawerMonitorHTML;initMonitorDrawer();break;
case'papers':body.innerHTML=drawerPapersHTML;initPapersDrawer();break;
case'deep':body.innerHTML=drawerDeepHTML;initDeepDrawer();break;
case'ops':body.innerHTML=drawerOpsHTML;initOpsDrawer();break;
}}

// ── User behavior tracking (fire-and-forget) ─────────────────────

function trackEvent(type, value, meta) {
  meta = meta || {};
  fetch('/api/track', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({event_type: type, target_value: value || '', metadata: meta}),
  }).catch(function(){});
}

function trackClick(type, url, title, site, tag) {
  trackEvent(type, url, {title: title, site_name: site, tag: tag});
}
