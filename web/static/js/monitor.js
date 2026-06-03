// Monitor drawer
var drawerMonitorHTML = [
  '<section class="card" style="margin-bottom:16px">',
  '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">',
  '<h2 style="margin:0">Overview</h2>',
  '<div style="display:flex;gap:8px;flex-wrap:wrap" id="action-buttons"></div>',
  '</div>',
  '<div class="stats" id="stats-grid" style="margin-top:12px">',
  '<div class="stat"><div class="val">--</div><div class="lbl">Total Runs</div></div>',
  '<div class="stat"><div class="val">--</div><div class="lbl">Items Collected</div></div>',
  '<div class="stat"><div class="val">--</div><div class="lbl">Sites</div></div>',
  '<div class="stat"><div class="val">--</div><div class="lbl">Last Run</div></div>',
  '</div></section>',
  '<section class="card" style="margin-bottom:16px"><h2>Site Health</h2><div class="site-health-grid" id="site-health-grid">',
  '<div class="health-card idle"><div class="health-card-header"><div class="health-dot idle"></div>',
  '<span class="name">Loading...</span><span class="status">--</span></div>',
  '<div class="health-metrics"><div class="health-metric">Last Run: <span>--</span></div>',
  '<div class="health-metric">Items: <span>--</span></div>',
  '<div class="health-metric">Snapshot: <span>--</span></div>',
  '<div class="health-metric">Failures: <span>0</span></div></div></div></div></section>',
  '<section class="card" style="margin-bottom:16px"><h2>Realtime Charts</h2>',
  '<div class="filters"><select id="echart-site" onchange="switchEChartsSite()"><option value="">Select site...</option></select></div>',
  '<div class="echarts-grid">',
  '<div class="echart-card"><h3>Tag Distribution</h3><div id="chart-tag-pie" style="height:300px"></div></div>',
  '<div class="echart-card"><h3>Count Trend</h3><div id="chart-trend-line" style="height:300px"></div></div>',
  '<div class="echart-card"><h3>Changes</h3><div id="chart-change-bar" style="height:300px"></div></div>',
  '<div class="echart-card"><h3>Update Summary</h3><div id="chart-update-summary" style="height:300px;overflow-y:auto;color:var(--text);font-size:13px;line-height:1.7;padding:4px 0">Select a site to view.</div></div>',
  '<div class="echart-card wide"><h3>Overview</h3><div id="chart-summary" style="min-height:100px;padding:8px 0;color:var(--muted)">Select a site.</div></div>',
  '</div></section>',
  '<section class="card" style="margin-bottom:16px"><h2>Historical Charts</h2>',
  '<div class="tabs" id="chart-tabs"></div><div class="chart-grid" id="chart-grid">',
  '<div style="color:var(--muted)">Loading...</div></div></section>',
  '<section class="card" style="margin-bottom:16px"><h2>News Items</h2>',
  '<div class="filters">',
  '<select id="filter-site" onchange="onSiteFilterChange()"><option value="">All sites</option></select>',
  '<select id="filter-tag"><option value="">All tags</option></select>',
  '<input type="text" id="filter-search" placeholder="Search..." onkeydown="if(event.key===13)loadItems(0)" style="min-width:180px">',
  '<button class="tab active" onclick="loadItems(0)" style="cursor:pointer">Search</button></div>',
  '<div class="tag-chips"><span style="font-size:11px;color:var(--muted);margin-right:4px">Quick:</span>',
  '<button onclick="quickFilter("Tech")" class="tag-chip">Tech</button>',
  '<button onclick="quickFilter("China")" class="tag-chip">China</button>',
  '<button onclick="quickFilter("Finance")" class="tag-chip">Finance</button>',
  '<button onclick="quickFilter("World")" class="tag-chip">World</button>',
  '<button onclick="quickFilter("",true)" class="tag-chip" style="border-color:var(--border);color:var(--muted)">Clear</button></div>',
  '<div style="overflow-x:auto"><table><thead><tr><th>Title</th><th>Tag</th><th>Site</th><th>Time</th><th></th></tr></thead>',
  '<tbody id="items-body"><tr><td colspan="5" style="color:var(--muted)">Loading...</td></tr></tbody></table></div>',
  '<div class="pagination" id="pagination"></div></section>',
  '<section class="card"><h2>Recent Runs</h2>',
  '<select id="run-site" onchange="loadRuns()" style="margin-bottom:10px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px"><option value="">All sites</option></select>',
  '<div style="overflow-x:auto"><table><thead><tr><th>Time</th><th>Site</th><th>Status</th><th>Items</th><th>Changes</th><th>Confidence</th><th>Duration</th></tr></thead>',
  '<tbody id="runs-body"><tr><td colspan="7" style="color:var(--muted)">Loading...</td></tr></tbody></table></div></section>',
].join('');

// Monitor state
var echartInstances={},echartSiteData={},echartCurrentSite=null;
var itemsPage=0,itemsPageSize=30,itemsTotal=0,allTags={},targetsData=[];

function initMonitorDrawer(){
  initMonitorCharts();loadChartData();loadStats();loadSiteHealth();loadCharts();loadTags();loadItems(0);loadRuns();loadTargets();
}

function initMonitorCharts(){
  echartInstances={};
  ['chart-tag-pie','chart-trend-line','chart-change-bar'].forEach(function(id){
    var dom=document.getElementById(id);if(dom)echartInstances[id]=echarts.init(dom);
  });
}

function switchEChartsSite(){
  var site=document.getElementById('echart-site').value;if(!site)return;
  echartCurrentSite=site;if(echartSiteData[site])renderAllCharts(echartSiteData[site]);
}

function renderAllCharts(d){if(!d)return;
  renderTagPie(d.tag_distribution);renderTrendLine(d.trends);renderChangeBar(d.changes);
  renderUpdateSummary(d.update_summary);renderSummary(d.summary);
}

function renderTagPie(data){var c=echartInstances['chart-tag-pie'];if(!c)return;
  c.setOption({tooltip:{trigger:'item',formatter:'{b}: {c} ({d}%)'},
    series:[{type:'pie',radius:['40%','72%'],center:['40%','50%'],
    label:{color:'#1e293b',fontSize:10},data:data||[]}]},true);
}

function renderTrendLine(data){var c=echartInstances['chart-trend-line'];if(!c)return;
  var counts=data.snapshot_counts||[];var times=(data.snapshot_times||[]).map(function(t){return t.slice(0,10);});
  c.setOption({tooltip:{trigger:'axis'},grid:{left:'3%',right:'4%',bottom:'12%',containLabel:true},
    xAxis:{type:'category',data:times,axisLabel:{color:'#64748b',rotate:45,fontSize:9}},
    yAxis:{type:'value',axisLabel:{color:'#64748b'}},
    series:[{type:'line',data:counts,smooth:true,symbolSize:6,
    lineStyle:{color:'#38bdf8',width:2},
    areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(59,130,246,0.15)'},{offset:1,color:'rgba(59,130,246,0.02)'}])}}]},true);
}

function renderChangeBar(data){var c=echartInstances['chart-change-bar'];if(!c)return;
  c.setOption({tooltip:{trigger:'axis'},
    xAxis:{type:'category',data:['New','Removed','Modified'],axisLabel:{color:'#64748b'}},
    yAxis:{type:'value',axisLabel:{color:'#64748b'}},
    series:[{type:'bar',data:[{value:data.new||0,itemStyle:{color:'#4ade80'}},{value:data.removed||0,itemStyle:{color:'#f87171'}},{value:data.modified||0,itemStyle:{color:'#fb923c'}}],
    barWidth:'50%',label:{show:true,position:'top',color:'#1e293b',fontWeight:'bold'}}]},true);
}

function renderUpdateSummary(text){var el=document.getElementById('chart-update-summary');if(!el)return;
  el.innerHTML=text?'<div style="padding:16px;background:rgba(59,130,246,0.06);border-radius:8px;border-left:3px solid var(--accent);line-height:1.7">'+text+'</div>':'<div style="color:var(--muted);padding:16px">No update data.</div>';
}

function renderSummary(s){var el=document.getElementById('chart-summary');if(!el||!s)return;
  var di=s.trend_direction==='up'?'\u2191':s.trend_direction==='down'?'\u2193':'\u2194';
  var dc=s.trend_direction==='up'?'var(--green)':s.trend_direction==='down'?'var(--red)':'var(--muted)';
  el.innerHTML='<div class="stats" style="margin-bottom:8px">'+
    '<div class="stat"><div class="val">'+(s.current_count||0)+'</div><div class="lbl">Current</div></div>'+
    '<div class="stat"><div class="val">'+(s.previous_count||0)+'</div><div class="lbl">Previous</div></div>'+
    '<div class="stat"><div class="val">'+(s.total_changes||0)+'</div><div class="lbl">Changes</div></div>'+
    '<div class="stat"><div class="val" style="color:'+dc+'">'+di+' '+(s.trend_direction||'stable')+'</div><div class="lbl">Trend</div></div></div>'+
    (s.llm_summary?'<div style="padding:10px 14px;background:rgba(59,130,246,0.06);border-radius:8px;border-left:3px solid var(--accent);font-size:13px;color:var(--text);line-height:1.6"><strong style="color:var(--accent)">AI Summary:</strong> '+s.llm_summary+'</div>':'')+
    '<div style="font-size:11px;color:var(--muted);margin-top:6px">Last update: '+(s.timestamp||'').slice(0,19)+'</div>';
}

function showModal(src){document.getElementById('modal-img').src=src;document.getElementById('modal').classList.add('show');}

async function loadChartData(){
  try{var r=await fetch('/api/chart-data');var d=await r.json();echartSiteData=d.chart_data||{};
    var sel=document.getElementById('echart-site');var sites=Object.keys(echartSiteData);
    sel.innerHTML='<option value="">Select...</option>'+sites.map(function(s){return '<option value="'+s+'">'+s+'</option>';}).join('');
    if(sites.length>0){sel.value=sites[0];echartCurrentSite=sites[0];renderAllCharts(echartSiteData[sites[0]]);}
  }catch(e){}
}

async function loadStats(){
  try{var r=await fetch('/api/stats');var d=await r.json();
    var runs=d.runs||[];var tr=runs.length;var ti=runs.reduce(function(s,r){return s+(r.items_found||0);},0);
    var lr=runs[0]?runs[0].created_at.slice(0,19):'N/A';
    document.getElementById('stats-grid').innerHTML='<div class="stat"><div class="val">'+tr+'</div><div class="lbl">Total Runs</div></div><div class="stat"><div class="val">'+ti+'</div><div class="lbl">Items</div></div><div class="stat"><div class="val">'+(d.sites||[]).length+'</div><div class="lbl">Sites</div></div><div class="stat"><div class="val">'+lr+'</div><div class="lbl">Last Run</div></div>';
    ['filter-site','run-site'].forEach(function(id){var sel=document.getElementById(id);if(!sel)return;var val=sel.value;
      sel.innerHTML='<option value="">All sites</option>'+(d.sites||[]).map(function(s){return '<option value="'+s+'">'+s+'</option>';}).join('');sel.value=val;});
  }catch(e){}
}

async function loadCharts(){
  try{var r=await fetch('/api/charts');var d=await r.json();var tabs=document.getElementById('chart-tabs');
    var grid=document.getElementById('chart-grid');var sets=Object.keys(d);
    if(!sets.length){grid.innerHTML='<div style="color:var(--muted)">No charts yet.</div>';tabs.innerHTML='';return;}
    tabs.innerHTML=sets.map(function(s,i){return '<span class="tab'+(i===0?' active':'')+'" onclick="showChartSet(\x27'+s+'\x27)">'+s+'</span>';}).join('');
    showChartSet(sets[0]);window._chartData=d;}catch(e){}
}

function showChartSet(name){var d=window._chartData||{};var grid=document.getElementById('chart-grid');
  var files=d[name]||[];document.querySelectorAll('#chart-tabs .tab').forEach(function(t){t.classList.toggle('active',t.textContent===name);});
  grid.innerHTML=files.length?files.map(function(f){return '<img src="/charts/'+name+'/'+f+'" alt="'+f+'" onclick="showModal(this.src)" loading="lazy">';}).join(''):'<div style="color:var(--muted)">No charts.</div>';
}

async function onSiteFilterChange(){itemsPage=0;await loadTags();loadItems(0);}

async function loadTags(){
  var site=document.getElementById('filter-site').value;var url='/api/query?limit=1';if(site)url+='&site='+encodeURIComponent(site);
  try{var r=await fetch(url);var d=await r.json();allTags=d.tags||{};var sel=document.getElementById('filter-tag');var val=sel.value;
    sel.innerHTML='<option value="">All tags</option>'+Object.keys(allTags).map(function(t){return '<option value="'+t+'">'+t+' ('+allTags[t]+')</option>';}).join('');sel.value=val;}catch(e){}
}

function quickFilter(tag,clear){
  if(clear){document.getElementById('filter-tag').value='';document.getElementById('filter-search').value='';}
  else{document.getElementById('filter-tag').value=tag;trackEvent('filter_tag', tag, {page: 'monitor'});}
  document.querySelectorAll('#drawer .tag-chip').forEach(function(c){c.classList.remove('active');
    if(!clear&&tag&&c.textContent===tag)c.classList.add('active');});
  loadItems(0);
}

async function loadItems(page){
  if(page!==undefined)itemsPage=page;var site=document.getElementById('filter-site').value;
  var tag=document.getElementById('filter-tag').value;var search=document.getElementById('filter-search').value;
  var url='/api/query?limit='+itemsPageSize+'&offset='+(itemsPage*itemsPageSize);
  if(site)url+='&site='+encodeURIComponent(site);if(tag)url+='&tag='+encodeURIComponent(tag);
  if(search){url+='&keyword='+encodeURIComponent(search);trackEvent('search', search, {page: 'monitor'});}
  try{var r=await fetch(url);var d=await r.json();var items=d.items||[];itemsTotal=d.total||items.length;
    document.getElementById('items-body').innerHTML=items.length?items.map(function(it){
      var eu=(it.url||'').replace(/'/g,"\'");var et=(it.title||'').replace(/'/g,"\'");var es=it.site_name||'-';var eg=it.tag||'-';
      return '<tr><td><a href="'+(it.url||'#')+'" target="_blank" style="color:var(--accent)" onclick="trackClick(\x27click_link\x27,\x27'+eu+'\x27,\x27'+et+'\x27,\x27'+es+'\x27,\x27'+eg+'\x27)">'+(it.title||'').slice(0,60)+'</a></td>'+
        '<td><span class="tag">'+eg+'</span></td><td style="color:var(--muted)">'+es+'</td>'+
        '<td style="color:var(--muted)">'+(it.snapshot_time||'').slice(0,19)+'</td>'+
        '<td><button onclick="trackClick(\x27click_summary\x27,\x27'+eu+'\x27,\x27'+et+'\x27,\x27'+es+'\x27,\x27'+eg+'\x27);fetchSummary(this,\x27'+eu+'\x27,\x27'+et+'\x27)" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500">Summary</button></td></tr>';
    }).join(''):'<tr><td colspan="5" style="color:var(--muted)">No items found.</td></tr>';
    renderPagination();}catch(e){}
}

function renderPagination(){
  var tp=Math.ceil(itemsTotal/itemsPageSize);var el=document.getElementById('pagination');
  if(tp<=1){el.innerHTML='';return;}
  el.innerHTML='<button onclick="loadItems(0)"'+(itemsPage===0?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">First</button>'+
    '<button onclick="loadItems('+(itemsPage-1)+')"'+(itemsPage===0?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">Prev</button>'+
    '<span style="color:var(--muted);font-size:12px">Page '+(itemsPage+1)+' / '+tp+' ('+itemsTotal+' items)</span>'+
    '<button onclick="loadItems('+(itemsPage+1)+')"'+(itemsPage>=tp-1?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">Next</button>'+
    '<button onclick="loadItems('+(tp-1)+')"'+(itemsPage>=tp-1?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">Last</button>';
}

async function loadRuns(){
  var site=document.getElementById('run-site').value;var url=site?'/api/stats?site='+encodeURIComponent(site):'/api/stats';
  try{var r=await fetch(url);var d=await r.json();var runs=d.runs||[];
    document.getElementById('runs-body').innerHTML=runs.length?runs.slice(0,30).map(function(rr){
      return '<tr class="run-row"><td style="color:var(--muted)">'+(rr.created_at||'').slice(0,19)+'</td><td>'+rr.site_name+'</td>'+
        '<td class="'+(rr.status==='success'?'status-ok':rr.status&&rr.status.startsWith('skip')?'status-skip':'status-err')+'">'+rr.status+'</td>'+
        '<td>'+(rr.items_found||0)+'</td><td>'+(rr.changes_detected||0)+'</td><td>'+(rr.extraction_confidence||0).toFixed(2)+'</td>'+
        '<td style="color:var(--muted)">'+(rr.processing_time_ms||0).toFixed(0)+'ms</td></tr>';}).join(''):'<tr><td colspan="7" style="color:var(--muted)">No runs yet.</td></tr>';
  }catch(e){}
}

async function loadTargets(){
  try{var r=await fetch('/api/targets');var d=await r.json();targetsData=d.targets||[];renderActionButtons();}catch(e){}
}

function renderActionButtons(){
  var el=document.getElementById('action-buttons');if(!el)return;
  el.innerHTML='<button onclick="refreshAll()" id="refresh-all-btn" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:6px 18px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600">Refresh All</button>'+
    targetsData.map(function(t){return '<button onclick="triggerRun(\x27'+t.name+'\x27,\x27'+t.url+'\x27,'+(t.use_browser||false)+')" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:6px 14px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:500">Run: '+t.name+'</button>'+
    '<button onclick="resetSite(\x27'+t.name+'\x27)" style="background:var(--bg);border:1px solid rgba(248,113,113,0.3);color:var(--red);padding:6px 14px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:500">Reset: '+t.name+'</button>';}).join('');
}

async function refreshAll(){var btn=document.getElementById('refresh-all-btn');if(!btn)return;btn.textContent='Running...';btn.disabled=true;btn.style.opacity='0.6';
  try{await fetch('/api/refresh-all',{method:'POST'});}catch(e){}
  setTimeout(function(){btn.textContent='Refresh All';btn.disabled=false;btn.style.opacity='1';},3000);}

async function triggerRun(name,url,useBrowser){
  var btns=document.querySelectorAll('#action-buttons button');btns.forEach(function(b){b.disabled=true;});
  try{var r=await fetch('/api/trigger-run?site='+encodeURIComponent(name)+'&url='+encodeURIComponent(url)+'&use_browser='+(useBrowser||false),{method:'POST'});var d=await r.json();
    if(d.status==='success'){alert('Run complete: '+name+' - '+d.items_found+' items');}
    else{alert('Run failed: '+name+' - '+(d.error||d.status||'Unknown'));}
  }catch(e){alert('Request failed: '+e.message);}
  btns.forEach(function(b){b.disabled=false;});setTimeout(function(){loadStats();loadItems(itemsPage);loadRuns();loadChartData();loadCharts();},1000);}

async function resetSite(name){if(!confirm('Reset all history for '+name+'? This cannot be undone.'))return;
  try{var r=await fetch('/api/reset?site='+encodeURIComponent(name),{method:'POST'});var d=await r.json();alert(d.message||'Reset complete');
    loadStats();loadItems(0);loadRuns();loadChartData();loadCharts();}catch(e){alert('Reset failed: '+e.message);}}

async function fetchSummary(btn,url,title){
  if(!url)return;btn.textContent='Loading...';btn.disabled=true;
  try{var r=await fetch('/api/summarize?url='+encodeURIComponent(url)+'&title='+encodeURIComponent(title));var d=await r.json();showSummaryModal(title,d.summary||'Summary failed');}
  catch(e){showSummaryModal(title,'Request failed: '+e.message);}btn.textContent='Summary';btn.disabled=false;}

function showSummaryModal(title,summary){
  var modal=document.getElementById('summary-modal');
  if(!modal){
    modal=document.createElement('div');modal.id='summary-modal';
    modal.style.cssText='display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(4px);z-index:200;justify-content:center;align-items:center';
    modal.onclick=function(e){if(e.target===modal)modal.style.display='none';};
    document.body.appendChild(modal);
  }
  var t=title.replace(/'/g,"\'");
  var s=summary.replace(/'/g,"\'");
  modal.innerHTML='<div style="background:var(--card);border:1px solid var(--border-light);border-radius:var(--radius-lg);padding:24px;max-width:560px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:var(--shadow-lg);animation:fadeSlideIn 0.25s ease"><div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:16px"><h3 style="color:var(--text);font-size:15px;margin:0;font-weight:600">Article Summary</h3><button onclick="document.getElementById(\x27summary-modal\x27).style.display=\x27none\x27" style="background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1;padding:0 4px">&times;</button></div><div style="color:var(--text);font-size:14px;line-height:1.7;margin-bottom:12px">'+summary+'</div><div style="color:var(--muted);font-size:12px;border-top:1px solid var(--border-light);padding-top:10px">'+title+'</div></div>';
  modal.style.display='flex';
}

function loadSiteHealth(){
  fetch('/api/stats').then(function(r){return r.json();}).then(function(d){
    var h=d.site_health||{};var sites=d.sites||[];var grid=document.getElementById('site-health-grid');
    if(!sites.length){grid.innerHTML='<div class="health-card idle"><div class="health-card-header"><span class="name">No sites configured</span></div></div>';return;}
    grid.innerHTML=sites.map(function(s){var hh=h[s]||{};var st=hh.last_run_status||'never';var cls,dotCls,label;
      if(hh.circuit_open){cls='warn';dotCls='warn';label='Circuit Open';}
      else if(st==='success'){cls='ok';dotCls='ok';label='OK';}
      else if(st==='error'){cls='error';dotCls='error';label='Error';}
      else if(st==='skipped_no_change'){cls='ok';dotCls='ok';label='No Change';}
      else{cls='idle';dotCls='idle';label='Waiting';}
      var rt=hh.last_run_time?hh.last_run_time.slice(0,19):'--';
      var sst=hh.last_snapshot_time?hh.last_snapshot_time.slice(0,19):'--';
      return '<div class="health-card '+cls+'"><div class="health-card-header"><div class="health-dot '+dotCls+'"></div><span class="name">'+s+'</span><span class="status">'+label+'</span></div><div class="health-metrics"><div class="health-metric">Last Run: <span>'+rt+'</span></div><div class="health-metric">Items: <span>'+(hh.last_run_items||0)+'</span></div><div class="health-metric">Snapshot: <span>'+sst+'</span></div><div class="health-metric">Snap Items: <span>'+(hh.last_snapshot_items||0)+'</span></div></div>'+(hh.consecutive_failures>0?'<div class="health-metric" style="grid-column:1/-1;margin-top:4px">Failures: <span style="color:var(--orange)">'+hh.consecutive_failures+'</span></div>':'')+(hh.error_message?'<div class="health-error-msg" title="'+hh.error_message.replace(/"/g,'&amp;quot;')+'">'+hh.error_message+'</div>':'')+'</div>';
    }).join('');
  }).catch(function(){});
}
