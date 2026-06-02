// Deep Analysis drawer
var drawerDeepHTML = [
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">Entity Leaderboard</h2><div style="display:flex;gap:6px" id="entity-type-filters">',
  '<button class="tab active" onclick="loadEntities(\x27\x27)">All</button>',
  '<button class="tab" onclick="loadEntities(\x27PER\x27)">Person</button>',
  '<button class="tab" onclick="loadEntities(\x27ORG\x27)">Org</button>',
  '<button class="tab" onclick="loadEntities(\x27LOC\x27)">Location</button>',
  '<button class="tab" onclick="loadEntities(\x27PROD\x27)">Product</button>',
  '<button class="tab" onclick="loadEntities(\x27EVENT\x27)">Event</button></div></div>',
  '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px">',
  '<div class="echart-card"><h3>Top Entities</h3><div id="chart-entities-bar" style="height:360px"></div></div>',
  '<div class="echart-card" style="max-height:420px;overflow-y:auto"><h3>Entity Details</h3>',
  '<div id="entity-detail-list" style="color:var(--muted);font-size:13px;padding-top:10px">Click a bar to view articles.</div></div></div></section>',
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">Cross-site Events</h2><button onclick="loadEvents()" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 14px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:500">Refresh</button></div>',
  '<div id="events-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px;margin-top:12px"><div style="color:var(--muted);padding:20px">Loading events...</div></div></section>',
  '<section class="card" id="timeline-section" style="display:none"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><h2 style="margin:0">Event Timeline</h2><button onclick="closeTimeline()" style="background:var(--bg);border:1px solid var(--border);color:var(--muted);padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px">Close</button></div>',
  '<div id="timeline-title" style="font-size:16px;font-weight:600;color:var(--accent);margin-bottom:6px"></div>',
  '<div id="timeline-summary" style="color:var(--text);font-size:13px;line-height:1.7;margin-bottom:12px;padding:10px 14px;background:var(--bg);border-radius:var(--radius);border-left:3px solid var(--accent)"></div>',
  '<div style="overflow-x:auto"><table><thead><tr><th>Time</th><th>Site</th><th>Title</th><th>Sentiment</th></tr></thead>',
  '<tbody id="timeline-body"><tr><td colspan="4" style="color:var(--muted)">Loading...</td></tr></tbody></table></div></section>'
].join('');

var entitiesBar=null,allEntities=[];

function initDeepDrawer(){initEntitiesChart();loadEvents();loadEntities('');}

function initEntitiesChart(){
  if(entitiesBar)return;var dom=document.getElementById('chart-entities-bar');
  if(dom){entitiesBar=echarts.init(dom);}
}

async function loadEntities(type){
  document.querySelectorAll('#entity-type-filters .tab').forEach(function(b){b.classList.toggle('active',b.textContent===(type||'All'));});
  var url='/api/entities?limit=30';if(type)url+='&type='+type;
  try{var r=await fetch(url);var d=await r.json();allEntities=d.entities||[];renderEntitiesChart(allEntities);}catch(e){}
}

function renderEntitiesChart(entities){
  if(!entitiesBar)return;var top=entities.slice(0,20);var names=top.map(function(e){return e.name;});
  var values=top.map(function(e){return e.mentions;});
  var tc={PER:'#38bdf8',ORG:'#4ade80',LOC:'#f59e0b',PROD:'#a78bfa',EVENT:'#f87171','':'#64748b'};
  entitiesBar.setOption({
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:function(p){return p[0].name+'<br/>Mentions: '+p[0].value;}},
    xAxis:{type:'value',axisLabel:{color:'#64748b'}},
    yAxis:{type:'category',data:names.reverse(),axisLabel:{color:'#1e293b',fontSize:11,width:120,overflow:'truncate'},inverse:true},
    grid:{left:'3%',right:'4%',bottom:'10%',containLabel:true},
    series:[{type:'bar',data:values.reverse().map(function(v,i){return{value:v,itemStyle:{color:tc[top[top.length-1-i].type]||'#64748b',borderRadius:[0,4,4,0]}};}),
    barWidth:'60%',label:{show:true,position:'right',color:'#1e293b',fontSize:10}}]
  },true);
  entitiesBar.off('click');entitiesBar.on('click',function(params){var e=top[top.length-1-params.dataIndex];if(e)showEntityItems(e.name);});
}

async function showEntityItems(name){
  try{var r=await fetch('/api/entities/'+encodeURIComponent(name)+'?limit=15');var d=await r.json();var items=d.items||[];
    document.getElementById('entity-detail-list').innerHTML='<div style="color:var(--accent);font-weight:600;margin-bottom:8px;font-size:14px">'+name+' - '+items.length+' articles</div>'+
    items.map(function(it){return '<div style="padding:6px 0;border-bottom:1px solid var(--border-light);font-size:12px;line-height:1.5"><a href="'+(it.url||'#')+'" target="_blank" style="color:var(--accent)">'+(it.title||'').slice(0,70)+'</a><span style="color:var(--muted);margin-left:8px">['+(it.site_name||'?')+'] '+(it.snapshot_time||'').slice(0,10)+'</span></div>';}).join('');}catch(e){}
}

async function loadEvents(){
  try{var r=await fetch('/api/events?limit=12');var d=await r.json();var events=d.events||[];var grid=document.getElementById('events-grid');
    if(!events.length){grid.innerHTML='<div style="color:var(--muted);padding:20px">No cross-site events detected yet.</div>';return;}
    grid.innerHTML=events.map(function(evt){return '<div class="health-card ok" style="cursor:pointer" onclick="loadTimeline(\x27'+evt.event_id+'\x27)"><div class="health-card-header"><div class="health-dot ok"></div><span class="name" style="font-size:14px">'+evt.event_name+'</span><span class="status" style="color:var(--accent)">'+evt.item_count+' items</span></div><div class="health-metrics"><div class="health-metric">Sites: <span>'+(evt.sites||[]).join(', ')+'</span></div><div class="health-metric">Tags: <span>'+(evt.tags||[]).join(', ')+'</span></div><div class="health-metric" style="grid-column:1/-1">Time: <span>'+(evt.created_at||'').slice(0,19)+'</span></div></div></div>';}).join('');}catch(e){grid.innerHTML='<div style="color:var(--red)">Failed to load events.</div>';}
}

async function loadTimeline(eventId){
  try{var r=await fetch('/api/events/'+encodeURIComponent(eventId));var evt=await r.json();
    document.getElementById('timeline-section').style.display='';
    document.getElementById('timeline-title').textContent=evt.event_name||'Event';
    document.getElementById('timeline-summary').textContent='Cross-site event spanning '+(evt.sites||[]).join(', ')+'. '+evt.item_count+' related articles.';
    var items=evt.items||[];
    document.getElementById('timeline-body').innerHTML=items.length?items.map(function(it){
      return '<tr><td style="color:var(--muted);font-size:12px">'+(it.snapshot_time||'').slice(0,19)+'</td><td><span class="tag">'+(it.site_name||'-')+'</span></td><td><a href="'+(it.url||'#')+'" target="_blank" style="color:var(--accent)">'+(it.title||'').slice(0,70)+'</a></td><td style="color:'+(it.sentiment==='positive'?'var(--green)':it.sentiment==='negative'?'var(--red)':'var(--muted)')+'">'+(it.sentiment||'-')+'</td></tr>';
    }).join(''):'<tr><td colspan="4" style="color:var(--muted)">No timeline data.</td></tr>';
    document.getElementById('timeline-section').scrollIntoView({behavior:'smooth'});}catch(e){}
}

function closeTimeline(){document.getElementById('timeline-section').style.display='none';}
