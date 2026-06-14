// Shared utilities: auth, theme, WebSocket, drawer, update notifier

// ── Theme ────────────────────────────────────────────────────────────
function getTheme(){return localStorage.getItem('theme')||'light';}
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);let b=document.getElementById('theme-toggle');b.innerHTML=t==='dark'?'☼':'☾';}
function toggleTheme(){let n=getTheme()==='dark'?'light':'dark';localStorage.setItem('theme',n);applyTheme(n);}
applyTheme(getTheme());

// ── Auth ─────────────────────────────────────────────────────────────
async function checkAuth(){
try{let r=await fetch('/api/health');if(r.status===401){document.getElementById('login-overlay').classList.add('show');return false;}return true;}catch(e){return true;}}

async function doLogin(){
let tokenVal=document.getElementById('login-token').value.trim();if(!tokenVal)return;
try{let r=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tokenVal})});
if(r.ok){document.getElementById('login-overlay').classList.remove('show');document.getElementById('login-error').style.display='none';}
else{document.getElementById('login-error').style.display='block';}}catch(e){showToast(t('login_failed_toast'), 'error');}}

// ── Toast notifications ────────────────────────────────────────────
function showToast(msg, type) {
  type = type || 'info';
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = 'toast toast-' + type + ' show';
  clearTimeout(el._tid);
  el._tid = setTimeout(function () { el.classList.remove('show'); }, 3500);
}

// ── WebSocket ────────────────────────────────────────────────────────
let wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
let ws = null, wsReconnectDelay = 1000, wsReconnectMax = 30000;
function createWS(){
if(ws){try{ws.close();}catch(e){}}
ws=new WebSocket(wsProtocol+'//'+location.host+'/ws');
ws.onopen=function(){document.getElementById('ws-dot').classList.remove('offline');document.getElementById('ws-text').textContent=t('ws_online');wsReconnectDelay=1000;};
ws.onclose=function(){document.getElementById('ws-dot').classList.add('offline');document.getElementById('ws-text').textContent=t('ws_offline');setTimeout(createWS,wsReconnectDelay);wsReconnectDelay=Math.min(wsReconnectDelay*2,wsReconnectMax);};
ws.onmessage=function(e){let d;try{d=JSON.parse(e.data);}catch(ex){return;}if(d.type==='pipeline_update'){if(d.chart_data){let s=d.chart_data.site_name;echartSiteData[s]=d.chart_data;let sel=document.getElementById('echart-site');if(sel&&!Array.from(sel.options).some(function(o){return o.value===s;})){sel.innerHTML+='<option value="'+s+'">'+s+'</option>';}if(s===echartCurrentSite||!echartCurrentSite){if(!echartCurrentSite){echartCurrentSite=s;if(sel)sel.value=s;}renderAllCharts(d.chart_data);}}if(currentDrawer==='monitor'){loadStats();loadItems(itemsPage);loadRuns();}}else if(d.type==='watch_summary'){let badge=document.getElementById('ops-badge');if(badge){let sc=(d.stale||[]).length;if(sc>0){badge.textContent=sc;badge.style.display='inline-block';badge.title=sc+' stale watches';}else{badge.style.display='none';}}if(currentDrawer==='ops'&&typeof loadWatches==='function')loadWatches(watchTypeFilter);}};
}
createWS();
setInterval(function(){if(ws&&ws.readyState===WebSocket.OPEN)ws.send('ping');},30000);
setInterval(function(){document.getElementById('clock').textContent=new Date().toLocaleTimeString();},1000);

// ── Update Notifier ──────────────────────────────────────────────────
let updateSeenMarker='';
function fetchUpdates(){
  fetch('/api/recent-updates?since=10').then(function(r){return r.json();}).then(function(d){
    let updates=d.updates||[];if(!updates.length)return;
    let latestTime=updates[0].time||'';
    if(latestTime===updateSeenMarker)return;
    let badge=document.getElementById('update-badge');
    let notifier=document.getElementById('update-notifier');
    let label=document.getElementById('update-label');
    if(badge&&notifier&&label){
      let fresh=0;
      for(let i=0;i<updates.length;i++){
        if(updates[i].time===updateSeenMarker)break;
        if(updates[i].status==='success'||updates[i].status==='skipped_no_change')fresh++;
      }
      if(fresh>0){
        badge.textContent=fresh;badge.style.display='block';
        notifier.classList.add('has-new');label.textContent=t('update_label_items',{count:fresh});
      }else{
        badge.style.display='none';notifier.classList.remove('has-new');
        label.textContent=t('update_label_latest');
      }
    }
    if(!updateSeenMarker)updateSeenMarker=latestTime;
  }).catch(function(){});
}
function toggleUpdatePanel(){
  let panel=document.getElementById('update-panel');
  if(!panel)return;
  if(panel.style.display==='none'||!panel.style.display){
    fetch('/api/recent-updates?since=20').then(function(r){return r.json();}).then(function(d){
      let updates=d.updates||[];let body=document.getElementById('update-panel-body');
      if(!updates.length){body.innerHTML='<div class="update-empty">'+t('update_panel_no_update')+'</div>';return;}
      let html='';
      for(let i=0;i<updates.length;i++){
        let u=updates[i];
        html+='<div class="update-item">';
        html+='<div class="update-item-site">'+u.site_name+' <span style="color:var(--muted);font-weight:400">'+u.time.slice(0,16)+'</span></div>';
        html+='<div class="update-item-summary">'+(u.update_summary||'('+t('update_label_checking')+')')+'</div>';
        html+='<div class="update-item-meta"><span>'+t('monitor_new')+' '+u.new_count+'</span><span>'+t('monitor_changes')+' '+u.total_changes+'</span></div>';
        html+='</div>';
      }
      body.innerHTML=html;
      panel.style.display='flex';
      if(updates.length>0){updateSeenMarker=updates[0].time||updateSeenMarker;}
      let badge=document.getElementById('update-badge');badge.style.display='none';
      let notifier=document.getElementById('update-notifier');notifier.classList.remove('has-new');
      let label=document.getElementById('update-label');label.textContent=t('update_label_latest');
    }).catch(function(){});
  }else{
    panel.style.display='none';
  }
}
function closeUpdatePanel(){
  document.getElementById('update-panel').style.display='none';
}
document.addEventListener('click',function(e){
  let panel=document.getElementById('update-panel');
  let btn=document.getElementById('update-notifier');
  if(panel&&btn&&panel.style.display!=='none'&&!panel.contains(e.target)&&!btn.contains(e.target)){
    panel.style.display='none';
  }
});
fetchUpdates();

// ── Drawer ───────────────────────────────────────────────────────────
let currentDrawer=null;
const drawerTitles={monitor:'drawer_monitor',papers:'drawer_papers',deep:'drawer_deep',ops:'drawer_ops'};

function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open');}
function focusChat(){closeDrawer();document.getElementById('chat-input').focus();}
function openDrawer(name){
currentDrawer=name;
document.querySelectorAll('.sidebar-item[data-drawer]').forEach(function(el){el.classList.toggle('active',el.dataset.drawer===name);});
var mp=document.querySelector('.main-panel');
if(mp)mp.classList.add('drawer-open');
document.getElementById('drawer-overlay').classList.add('show');
document.getElementById('drawer').classList.add('show');
document.getElementById('drawer-title').textContent=t(drawerTitles[name]||'');
renderDrawerContent(name);}

function closeDrawer(){
currentDrawer=null;
document.querySelectorAll('.sidebar-item[data-drawer]').forEach(function(el){el.classList.remove('active');});
var cb=document.querySelector('.sidebar-item[data-drawer=chat]');
if(cb)cb.classList.add('active');
var mp=document.querySelector('.main-panel');
if(mp)mp.classList.remove('drawer-open');
document.getElementById('drawer-overlay').classList.remove('show');
document.getElementById('drawer').classList.remove('show');}

function renderDrawerContent(name){
let body=document.getElementById('drawer-body');
// Dispose ECharts instances before destroying their DOM containers
if(typeof disposeMonitorCharts==='function')disposeMonitorCharts();
switch(name){
case'monitor':body.innerHTML=drawerMonitorHTML;initMonitorDrawer();break;
case'papers':body.innerHTML=drawerPapersHTML;initPapersDrawer();break;
case'deep':body.innerHTML=drawerDeepHTML;initDeepDrawer();break;
case'ops':body.innerHTML=drawerOpsHTML;initOpsDrawer();break;
}}

// ── User behavior tracking (fire-and-forget) ─────────────────────────
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
