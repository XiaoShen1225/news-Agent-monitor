// Operations drawer
var drawerOpsHTML = [
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">Alert Management</h2><div style="display:flex;gap:8px;align-items:center" id="alert-add-form">',
  '<input id="alert-keyword-input" type="text" placeholder="Enter keyword..." onkeydown="if(event.key===13)addAlertKeyword()" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none;min-width:180px">',
  '<button onclick="addAlertKeyword()" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:8px 18px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap">+ Add</button></div></div>',
  '<div style="overflow-x:auto;margin-top:12px"><table><thead><tr><th>Keyword</th><th>Created</th><th></th></tr></thead>',
  '<tbody id="alerts-keywords-body"><tr><td colspan="3" style="color:var(--muted)">Loading...</td></tr></tbody></table></div>',
  '<div id="alerts-config" style="margin-top:12px;font-size:12px;color:var(--muted);padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);border-left:3px solid var(--accent)"></div></section>',
  '<section class="card" style="margin-bottom:16px"><h2 style="margin:0 0 12px">Story Tracking</h2>',
  '<div class="filters" id="story-status-tabs">',
  '<button class="tab active" onclick="loadStories(\x27\x27)">All</button>',
  '<button class="tab" onclick="loadStories(\x27active\x27)">Active</button>',
  '<button class="tab" onclick="loadStories(\x27completed\x27)">Completed</button>',
  '<button class="tab" onclick="loadStories(\x27dormant\x27)">Dormant</button></div>',
  '<div style="overflow-x:auto"><table><thead><tr><th>Title</th><th>Source</th><th>Status</th><th>Matches</th><th>Created</th><th>Last Match</th><th>Actions</th></tr></thead>',
  '<tbody id="stories-body"><tr><td colspan="7" style="color:var(--muted)">Loading...</td></tr></tbody></table></div>',
  '<div id="stories-config" style="margin-top:12px;font-size:12px;color:var(--muted);padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);border-left:3px solid var(--accent)"></div></section>'
].join('');

var storiesFilter='';

function initOpsDrawer(){loadAlerts();loadStories('');}

async function loadAlerts(){
  try{var r=await fetch('/api/alerts');var d=await r.json();var keywords=d.keywords||[];var config=d.config||{};
    document.getElementById('alerts-keywords-body').innerHTML=keywords.length?keywords.map(function(k){
      var ek=k.keyword.replace(/'/g,"\'");
      return '<tr><td><span class="tag">'+k.keyword+'</span></td><td style="color:var(--muted);font-size:12px">'+(k.created_at||'').slice(0,19)+'</td><td><button onclick="removeAlertKeyword(\x27'+ek+'\x27)" style="background:var(--bg);border:1px solid rgba(248,113,113,0.3);color:var(--red);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500">Delete</button></td></tr>';
    }).join(''):'<tr><td colspan="3" style="color:var(--muted)">No alert keywords.</td></tr>';
    document.getElementById('alerts-config').innerHTML=keywords.length?'<strong>Config:</strong> Cooldown '+ (config.keyword_cooldown_hours||24)+'h | Anomaly '+(config.anomaly_enabled?'on (z-score '+(config.anomaly_zscore||2.5)+')':'off')+' | Sentiment '+(config.sentiment_enabled?'on':'off'):'';}catch(e){}
}

async function addAlertKeyword(){
  var input=document.getElementById('alert-keyword-input');var kw=input.value.trim();if(!kw)return;input.value='';input.disabled=true;
  try{var r=await fetch('/api/alerts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keyword:kw})});var d=await r.json();
    if(!r.ok){alert(d.error||d.msg||'Add failed');}loadAlerts();}catch(e){alert('Request failed: '+e.message);}input.disabled=false;input.focus();}

async function removeAlertKeyword(keyword){
  if(!confirm('Delete alert keyword "'+keyword+'"?'))return;
  try{var r=await fetch('/api/alerts?keyword='+encodeURIComponent(keyword),{method:'DELETE'});if(!r.ok){var d=await r.json();alert(d.error||'Delete failed');}loadAlerts();}catch(e){alert('Request failed: '+e.message);}}

async function loadStories(status){
  storiesFilter=status;
  document.querySelectorAll('#story-status-tabs .tab').forEach(function(t){t.classList.toggle('active',(status===''&&t.textContent==='All')||(status==='active'&&t.textContent==='Active')||(status==='completed'&&t.textContent==='Completed')||(status==='dormant'&&t.textContent==='Dormant'));});
  try{var url=status?'/api/stories?status='+encodeURIComponent(status):'/api/stories';var r=await fetch(url);var d=await r.json();
    var stories=d.stories||[];var config=d.config||{};
    document.getElementById('stories-body').innerHTML=stories.length?stories.map(function(s){
      var sc={active:'var(--green)',completed:'var(--muted)',dormant:'var(--orange)'};
      var sl={active:'Active',completed:'Completed',dormant:'Dormant'};var color=sc[s.status]||'var(--muted)';var label=sl[s.status]||s.status;
      var st=s.title||'';var et=st.replace(/'/g,"\'");
      var actions='';
      if(s.status==='active'){actions='<button onclick="completeStory(\x27'+s.id+'\x27)" style="background:var(--bg);border:1px solid var(--border);color:var(--muted);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500;margin-right:4px">Complete</button>';}
      else if(s.status==='dormant'){actions='<button onclick="reactivateStory(\x27'+s.id+'\x27)" style="background:var(--bg);border:1px solid var(--border);color:var(--accent);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500;margin-right:4px">Reactivate</button>';}
      actions+='<button onclick="removeStory(\x27'+s.id+'\x27,\x27'+et+'\x27)" style="background:var(--bg);border:1px solid rgba(248,113,113,0.3);color:var(--red);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:11px;font-weight:500">Delete</button>';
      return '<tr><td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+s.title+'</td><td><span class="tag">'+(s.source_site||'-')+'</span></td><td><span style="color:'+color+';font-weight:500;font-size:12px">'+label+'</span></td><td style="color:var(--accent)">'+(s.match_count||0)+'</td><td style="color:var(--muted);font-size:12px">'+(s.created_at||'').slice(0,10)+'</td><td style="color:var(--muted);font-size:12px">'+(s.last_match_at||'--').slice(0,16)+'</td><td style="white-space:nowrap">'+actions+'</td></tr>';
    }).join(''):'<tr><td colspan="7" style="color:var(--muted)">No tracked stories.</td></tr>';
    document.getElementById('stories-config').innerHTML=stories.length?'<strong>Config:</strong> Similarity threshold '+(config.similarity_threshold||0.7)+' | Cooldown '+(config.match_cooldown_hours||12)+'h | Dormant after '+(config.dormant_after_days||30)+'d | Auto-clean '+(config.remove_dormant_after_days||90)+'d':'';}catch(e){}
}

async function completeStory(id){if(!confirm('Mark this story as completed?'))return;
  try{var r=await fetch('/api/stories/'+encodeURIComponent(id)+'/complete',{method:'POST'});if(!r.ok){var d=await r.json();alert(d.error||'Failed');}loadStories(storiesFilter);}catch(e){alert('Request failed: '+e.message);}}

async function reactivateStory(id){if(!confirm('Reactivate this dormant story?'))return;
  try{var r=await fetch('/api/stories/'+encodeURIComponent(id)+'/reactivate',{method:'POST'});if(!r.ok){var d=await r.json();alert(d.error||'Failed');}loadStories(storiesFilter);}catch(e){alert('Request failed: '+e.message);}}

async function removeStory(id,title){if(!confirm('Delete story "'+title.slice(0,50)+'"?'))return;
  try{var r=await fetch('/api/stories/'+encodeURIComponent(id),{method:'DELETE'});if(!r.ok){var d=await r.json();alert(d.error||'Delete failed');}loadStories(storiesFilter);}catch(e){alert('Request failed: '+e.message);}}
