// Papers drawer
var drawerPapersHTML = [
  '<section class="card" style="margin-bottom:16px">',
  '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">',
  '<h2 style="margin:0">Paper Tracking</h2>',
  '<div style="display:flex;gap:8px;flex-wrap:wrap" id="paper-action-buttons"></div>',
  '</div>',
  '<div class="stats" style="margin-top:12px">',
  '<div class="stat"><div class="val" id="papers-total">--</div><div class="lbl">Total Papers</div></div>',
  '<div class="stat"><div class="val" id="papers-deepmind">--</div><div class="lbl">DeepMind</div></div>',
  '<div class="stat"><div class="val" id="papers-openai">--</div><div class="lbl">OpenAI</div></div>',
  '</div></section>',
  '<section class="card" style="margin-bottom:16px"><h2>Papers</h2>',
  '<div class="filters">',
  '<select id="paper-filter-source" onchange="loadPapers(0)"><option value="">All sources</option></select>',
  '<input type="text" id="paper-filter-search" placeholder="Search titles...">',
  '<button class="tab active" onclick="loadPapers(0)" style="cursor:pointer">Search</button>',
  '</div>',
  '<div style="overflow-x:auto"><table><thead><tr><th>Title</th><th>Source</th><th>Summary</th><th>Date</th><th></th></tr></thead>',
  '<tbody id="papers-body"><tr><td colspan="5" style="color:var(--muted)">Loading...</td></tr></tbody></table></div>',
  '<div class="pagination" id="papers-pagination"></div></section>'
].join('');

var papersPage=0,papersPageSize=30,papersTotal=0,scheduleData=null;

function initPapersDrawer(){loadPapers(0);loadSchedule();}

async function loadPapers(page){
  if(page!==undefined)papersPage=page;
  var source=document.getElementById('paper-filter-source').value;
  var search=document.getElementById('paper-filter-search').value;
  var url='/api/papers?limit='+papersPageSize+'&offset='+(papersPage*papersPageSize);
  if(source)url+='&site='+encodeURIComponent(source);
  try{var r=await fetch(url);var d=await r.json();var items=d.items||[];papersTotal=d.total||items.length;
    if(search)items=items.filter(function(it){return it.title.toLowerCase().includes(search.toLowerCase());});
    document.getElementById('papers-total').textContent=papersTotal;
    var sources=d.sources||{};
    document.getElementById('papers-deepmind').textContent=sources['deepmind_blog']||0;
    document.getElementById('papers-openai').textContent=sources['openai_blog']||0;
    var sel=document.getElementById('paper-filter-source');
    if(sel.options.length<=1){sel.innerHTML='<option value="">All sources</option>'+Object.keys(sources).map(function(s){return '<option value="'+s+'">'+s+'</option>';}).join('');}
    document.getElementById('papers-body').innerHTML=items.length?items.map(function(it){
      return '<tr><td><a href="'+(it.url||'#')+'" target="_blank" style="color:var(--accent)">'+(it.title||'').slice(0,80)+'</a></td>'+
        '<td><span class="tag">'+(it.site_name||'-')+'</span></td>'+
        '<td style="color:var(--muted);font-size:12px;max-width:360px">'+(it.summary||'').slice(0,150)+'</td>'+
        '<td style="color:var(--muted);font-size:12px">'+(it.snapshot_time||'').slice(0,10)+'</td>'+
        '<td><button onclick="fetchSummary(this,\x27'+(it.url||'').replace(/'/g,"\'")+'\x27,\x27'+(it.title||'').replace(/'/g,"\'")+'\x27)" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500">Summary</button></td></tr>';
    }).join(''):'<tr><td colspan="5" style="color:var(--muted)">No papers found.</td></tr>';
    renderPapersPagination();}catch(e){}
}

function renderPapersPagination(){
  var tp=Math.ceil(papersTotal/papersPageSize);var el=document.getElementById('papers-pagination');
  if(tp<=1){el.innerHTML='';return;}
  el.innerHTML='<button onclick="loadPapers(0)"'+(papersPage===0?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">First</button>'+
    '<button onclick="loadPapers('+(papersPage-1)+')"'+(papersPage===0?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">Prev</button>'+
    '<span style="color:var(--muted);font-size:12px">Page '+(papersPage+1)+' / '+tp+' ('+papersTotal+' items)</span>'+
    '<button onclick="loadPapers('+(papersPage+1)+')"'+(papersPage>=tp-1?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">Next</button>'+
    '<button onclick="loadPapers('+(tp-1)+')"'+(papersPage>=tp-1?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">Last</button>';
}

async function loadSchedule(){
  try{var r=await fetch('/api/schedule');scheduleData=await r.json();renderPaperActions();}catch(e){}
}

function renderPaperActions(){
  if(!scheduleData)return;var el=document.getElementById('paper-action-buttons');var targets=scheduleData.targets||[];
  el.innerHTML=targets.filter(function(t){return t.is_article;}).map(function(t){
    return '<button onclick="triggerRun(\x27'+t.name+'\x27,\x27'+t.url+'\x27,false)" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:6px 14px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:500">Fetch: '+t.name+'</button>';
  }).join('');
}
