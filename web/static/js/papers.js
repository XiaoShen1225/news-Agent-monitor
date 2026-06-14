// Papers drawer
var drawerPapersHTML = [
  '<section class="card" style="margin-bottom:16px">',
  '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">',
  '<h2 style="margin:0">'+t('papers_tracking')+'</h2>',
  '<div style="display:flex;gap:8px;flex-wrap:wrap" id="paper-action-buttons"></div>',
  '</div>',
  '<div class="stats" style="margin-top:12px">',
  '<div class="stat"><div class="val" id="papers-total">--</div><div class="lbl">'+t('papers_total')+'</div></div>',
  '<div class="stat"><div class="val" id="papers-deepmind">--</div><div class="lbl">'+t('papers_deepmind')+'</div></div>',
  '<div class="stat"><div class="val" id="papers-openai">--</div><div class="lbl">'+t('papers_openai')+'</div></div>',
  '</div></section>',
  '<section class="card" style="margin-bottom:16px"><h2>'+t('papers_title')+'</h2>',
  '<div class="filters">',
  '<select id="paper-filter-source" onchange="loadPapers(0)"><option value="">'+t('papers_all_sources')+'</option></select>',
  '<input type="text" id="paper-filter-search" placeholder="'+t('papers_search_titles')+'">',
  '<button class="tab active" onclick="loadPapers(0)" style="cursor:pointer">'+t('papers_search')+'</button>',
  '</div>',
  '<div style="overflow-x:auto"><table><thead><tr><th>'+t('papers_col_title')+'</th><th>'+t('papers_col_source')+'</th><th>'+t('papers_col_summary')+'</th><th>'+t('papers_col_date')+'</th><th></th></tr></thead>',
  '<tbody id="papers-body"><tr><td colspan="5" style="color:var(--muted)">'+t('papers_loading')+'</td></tr></tbody></table></div>',
  '<div class="pagination" id="papers-pagination"></div></section>'
].join('');

var papersPage=0,papersPageSize=30,papersTotal=0,scheduleData=null;

function initPapersDrawer(){loadPapers(0);loadSchedule();}

async function loadPapers(page){
  if(page!==undefined)papersPage=page;
  var source=document.getElementById('paper-filter-source').value;
  var search=document.getElementById('paper-filter-search').value;
  if(search) trackEvent('search', search, {page: 'papers'});
  var url='/api/papers?limit='+papersPageSize+'&offset='+(papersPage*papersPageSize);
  if(source)url+='&site='+encodeURIComponent(source);
  if(search)url+='&keyword='+encodeURIComponent(search);
  try{var r=await fetch(url);var d=await r.json();var items=d.items||[];papersTotal=d.total||items.length;
    document.getElementById('papers-total').textContent=papersTotal;
    var sources=d.sources||{};
    document.getElementById('papers-deepmind').textContent=sources['deepmind_blog']||0;
    document.getElementById('papers-openai').textContent=sources['openai_blog']||0;
    var sel=document.getElementById('paper-filter-source');
    if(sel.options.length<=1){sel.innerHTML='<option value="">'+t('papers_all_sources')+'</option>'+Object.keys(sources).map(function(s){return '<option value="'+s+'">'+s+'</option>';}).join('');}
    document.getElementById('papers-body').innerHTML=items.length?items.map(function(it){
      var es=it.site_name||'-';var eu=(it.url||'').replace(/'/g,"\\'");var et=(it.title||'').replace(/'/g,"\\'");
      return '<tr><td><a href="'+(it.url||'#')+'" target="_blank" style="color:var(--accent)" onclick="trackClick(\'click_link\',\''+eu+'\',\''+et+'\',\''+es+'\')">'+(it.title||'').slice(0,80)+'</a></td>'+
        '<td><span class="tag">'+es+'</span></td>'+
        '<td style="color:var(--muted);font-size:12px;max-width:360px">'+(it.summary||'').slice(0,150)+'</td>'+
        '<td style="color:var(--muted);font-size:12px">'+(it.snapshot_time||'').slice(0,10)+'</td>'+
        '<td><button onclick="trackClick(\'click_summary\',\''+eu+'\',\''+et+'\',\''+es+'\');fetchSummary(this,\''+eu+'\',\''+et+'\')" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500">'+t('papers_summary_btn')+'</button></td></tr>';
    }).join(''):'<tr><td colspan="5" style="color:var(--muted)">'+t('papers_no_found')+'</td></tr>';
    renderPapersPagination();}catch(e){}
}

function renderPapersPagination(){
  var tp=Math.ceil(papersTotal/papersPageSize);var el=document.getElementById('papers-pagination');
  if(tp<=1){el.innerHTML='';return;}
  el.innerHTML='<button onclick="loadPapers(0)"'+(papersPage===0?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">'+t('monitor_pagination_first')+'</button>'+
    '<button onclick="loadPapers('+(papersPage-1)+')"'+(papersPage===0?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">'+t('monitor_pagination_prev')+'</button>'+
    '<span style="color:var(--muted);font-size:12px">'+t('monitor_pagination_page',{page:papersPage+1,total:tp,count:papersTotal})+'</span>'+
    '<button onclick="loadPapers('+(papersPage+1)+')"'+(papersPage>=tp-1?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">'+t('monitor_pagination_next')+'</button>'+
    '<button onclick="loadPapers('+(tp-1)+')"'+(papersPage>=tp-1?' disabled':'')+' style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px">'+t('monitor_pagination_last')+'</button>';
}

async function loadSchedule(){
  try{var r=await fetch('/api/schedule');scheduleData=await r.json();renderPaperActions();}catch(e){}
}

function renderPaperActions(){
  if(!scheduleData)return;var el=document.getElementById('paper-action-buttons');var targets=scheduleData.targets||[];
  el.innerHTML=targets.filter(function(t){return t.is_article;}).map(function(t){
    return '<button onclick="triggerRun(\''+t.name+'\',\''+t.url+'\',false)" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:6px 14px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:500">'+t('papers_fetch_prefix')+t.name+'</button>';
  }).join('');
}
