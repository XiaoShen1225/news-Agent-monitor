// Operations drawer — alert management, story tracking, target management
var drawerOpsHTML = [
  // ── Alert Management ──
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">Alert Management</h2><div style="display:flex;gap:8px;align-items:center" id="alert-add-form">',
  '<input id="alert-keyword-input" type="text" placeholder="Enter keyword..." onkeydown="if(event.key===13)addAlertKeyword()" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none;min-width:180px">',
  '<button onclick="addAlertKeyword()" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:8px 18px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap">+ Add</button></div></div>',
  '<div style="overflow-x:auto;margin-top:12px"><table><thead><tr><th>Keyword</th><th>Created</th><th></th></tr></thead>',
  '<tbody id="alerts-keywords-body"><tr><td colspan="3" style="color:var(--muted)">Loading...</td></tr></tbody></table></div>',
  '<div id="alerts-config" style="margin-top:12px;font-size:12px;color:var(--muted);padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);border-left:3px solid var(--accent)"></div></section>',

  // ── Story Tracking ──
  '<section class="card" style="margin-bottom:16px"><h2 style="margin:0 0 12px">Story Tracking</h2>',
  '<div class="filters" id="story-status-tabs">',
  '<button class="tab active" onclick="loadStories(\x27\x27)">All</button>',
  '<button class="tab" onclick="loadStories(\x27active\x27)">Active</button>',
  '<button class="tab" onclick="loadStories(\x27completed\x27)">Completed</button>',
  '<button class="tab" onclick="loadStories(\x27dormant\x27)">Dormant</button></div>',
  '<div style="overflow-x:auto"><table><thead><tr><th>Title</th><th>Source</th><th>Status</th><th>Matches</th><th>Created</th><th>Last Match</th><th>Actions</th></tr></thead>',
  '<tbody id="stories-body"><tr><td colspan="7" style="color:var(--muted)">Loading...</td></tr></tbody></table></div>',
  '<div id="stories-config" style="margin-top:12px;font-size:12px;color:var(--muted);padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);border-left:3px solid var(--accent)"></div></section>',

  // ── Target Management ──
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">Monitoring Targets</h2>',
  '<button onclick="showAddTargetForm()" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:8px 18px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap">+ Add Site</button></div>',

  // Add target form (collapsed by default)
  '<div id="add-target-form" style="display:none;margin-top:12px;padding:16px;background:var(--bg);border-radius:var(--radius);border:1px solid var(--border)">',
  '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">',
  '<div><label style="font-size:12px;color:var(--muted)">URL <span style="color:var(--red)">*</span></label>',
  '<input id="new-target-url" type="text" placeholder="https://..." style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none;box-sizing:border-box"></div>',
  '<div><label style="font-size:12px;color:var(--muted)">Site Name <span style="color:var(--red)">*</span></label>',
  '<input id="new-target-name" type="text" placeholder="my_site" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none;box-sizing:border-box"></div>',
  '<div><label style="font-size:12px;color:var(--muted)">Interval (min)</label>',
  '<select id="new-target-interval" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="5">5</option><option value="10">10</option><option value="15">15</option><option value="30">30</option><option value="60" selected>60</option><option value="120">120</option><option value="360">360</option></select></div>',
  '<div><label style="font-size:12px;color:var(--muted)">Strategy</label>',
  '<select id="new-target-strategy" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="auto" selected>Auto-detect</option><option value="rss">RSS</option><option value="llm">LLM</option><option value="css_selector">CSS Selector</option><option value="section_walk">Section Walk</option></select></div>',
  '</div>',
  '<div style="display:flex;gap:16px;align-items:center;margin-top:12px;flex-wrap:wrap">',
  '<label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px"><input type="checkbox" id="new-target-browser"> Use Browser</label>',
  '<label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px"><input type="checkbox" id="new-target-article"> Article Source</label>',
  '<div style="flex:1"></div>',
  '<button onclick="validateTargetUrl()" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;font-size:12px">Validate URL</button>',
  '<button onclick="addTarget()" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:8px 24px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600">Confirm Add</button>',
  '</div>',
  '<div id="target-validate-result" style="margin-top:8px;font-size:12px"></div>',
  '</div>',

  // Edit target form (hidden)
  '<div id="edit-target-form" style="display:none;margin-top:12px;padding:16px;background:var(--bg);border-radius:var(--radius);border:1px solid var(--border)" data-editing="">',
  '<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">',
  '<label style="font-size:12px;color:var(--muted)">Interval:</label>',
  '<select id="edit-target-interval" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="5">5</option><option value="10">10</option><option value="15">15</option><option value="30">30</option><option value="60">60</option><option value="120">120</option><option value="360">360</option></select>',
  '<label style="font-size:12px;color:var(--muted)">Strategy:</label>',
  '<select id="edit-target-strategy" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="auto">Auto-detect</option><option value="rss">RSS</option><option value="llm">LLM</option><option value="css_selector">CSS Selector</option><option value="section_walk">Section Walk</option></select>',
  '<button onclick="saveTargetEdit()" style="background:var(--accent);border:none;color:var(--bg);padding:8px 16px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600">Save</button>',
  '<button onclick="cancelTargetEdit()" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--muted);padding:8px 16px;border-radius:20px;cursor:pointer;font-size:12px">Cancel</button>',
  '</div></div>',

  // Target table
  '<div style="overflow-x:auto;margin-top:12px"><table><thead><tr><th>Name</th><th>URL</th><th>Interval</th><th>Strategy</th><th>Browser</th><th>Article</th><th>Status</th><th>Actions</th></tr></thead>',
  '<tbody id="targets-body"><tr><td colspan="8" style="color:var(--muted)">Loading...</td></tr></tbody></table></div></section>'
].join('');

var storiesFilter='';
var targetListSave=[];

function initOpsDrawer(){loadAlerts();loadStories('');loadTargetsConfig();}

// ── Alert Management ─────────────────────────────────────────────

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

// ── Story Tracking ───────────────────────────────────────────────

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

// ── Target Management ─────────────────────────────────────────────

async function loadTargetsConfig(){
  try{
    var r=await fetch('/api/targets');var d=await r.json();
    targetListSave=d.targets||[];
    renderTargetsTable(targetListSave);
  }catch(e){}
}

function renderTargetsTable(targets){
  var body=document.getElementById('targets-body');
  if(!body)return;
  var rows=targets.map(function(t){
    var name=t.name||'';
    var url=(t.url||'').length>50?(t.url||'').slice(0,47)+'...':(t.url||'');
    var interval=t.interval_minutes||60;
    var strategy=t.strategy||'auto';
    var isBuiltin=t.source==='builtin';
    var enabled=t.enabled!==false;
    var isArticle=t.is_article===true;
    var useBrowser=t.use_browser===true;
    var statusColor=enabled?'var(--green)':'var(--muted)';
    var statusText=enabled?'Active':'Paused';
    var actions='';

    if(!isBuiltin){
      actions+='<button onclick="editTarget(\x27'+name+'\x27)" style="background:var(--bg);border:1px solid var(--border);color:var(--text);padding:3px 8px;border-radius:10px;cursor:pointer;font-size:10px;font-weight:500;margin:0 2px">Edit</button>';
      actions+='<button onclick="toggleTargetConfig(\x27'+name+'\x27,'+(!enabled)+')" style="background:var(--bg);border:1px solid var(--border);color:'+(enabled?'var(--orange)':'var(--green)')+';padding:3px 8px;border-radius:10px;cursor:pointer;font-size:10px;font-weight:500;margin:0 2px">'+(enabled?'Pause':'Resume')+'</button>';
      actions+='<button onclick="removeTargetConfig(\x27'+name+'\x27)" style="background:var(--bg);border:1px solid rgba(248,113,113,0.3);color:var(--red);padding:3px 8px;border-radius:10px;cursor:pointer;font-size:10px;font-weight:500;margin:0 2px">Del</button>';
    }else{
      actions='<span style="font-size:10px;color:var(--muted)" title="Built-in target">built-in</span>';
    }
    actions+='<button onclick="triggerTargetRun(\x27'+name+'\x27)" style="background:var(--bg);border:1px solid var(--accent);color:var(--accent);padding:3px 8px;border-radius:10px;cursor:pointer;font-size:10px;font-weight:500;margin:0 2px">Run</button>';

    return '<tr>'+
      '<td><span style="font-weight:500">'+name+'</span>'+(isBuiltin?' <span style="font-size:9px;color:var(--muted)">[sys]</span>':' <span style="font-size:9px;color:var(--accent)">[usr]</span>')+'</td>'+
      '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px" title="'+(t.url||'')+'">'+url+'</td>'+
      '<td style="font-size:12px;text-align:center">'+interval+'m</td>'+
      '<td><span class="tag">'+strategy+'</span></td>'+
      '<td style="text-align:center;font-size:12px">'+(useBrowser?'Y':'—')+'</td>'+
      '<td style="text-align:center;font-size:12px">'+(isArticle?'Y':'—')+'</td>'+
      '<td><span style="color:'+statusColor+';font-weight:500;font-size:12px">'+statusText+'</span></td>'+
      '<td style="white-space:nowrap">'+actions+'</td>'+
      '</tr>';
  });
  if(!targets.length){
    body.innerHTML='<tr><td colspan="8" style="color:var(--muted)">No monitoring targets configured. Click "+ Add Site" to add one.</td></tr>';
  }else{
    body.innerHTML=rows.join('');
  }
}

function showAddTargetForm(){
  var form=document.getElementById('add-target-form');
  if(form){
    form.style.display=form.style.display==='none'?'block':'none';
    if(form.style.display==='block'){
      var nameInput=document.getElementById('new-target-name');
      if(nameInput)nameInput.focus();
    }
  }
}

function slugifyDomain(url){
  try{
    var u=new URL(url);var host=u.hostname.replace('www.','');
    return host.replace(/[^a-zA-Z0-9]/g,'_').replace(/_+/g,'_').replace(/^_|_$/g,'').toLowerCase();
  }catch(e){return '';}
}

async function validateTargetUrl(){
  var urlEl=document.getElementById('new-target-url');var url=urlEl.value.trim();
  if(!url){alert('Please enter a URL first');return;}
  var resultDiv=document.getElementById('target-validate-result');
  resultDiv.innerHTML='<span style="color:var(--muted)">Checking...</span>';
  try{
    var r=await fetch('/api/targets/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})});
    var d=await r.json();
    if(d.reachable){
      resultDiv.innerHTML='<span style="color:var(--green)">&#x2713; Reachable</span> | '+
        'Status: '+d.status_code+' | '+
        'Detected: <strong>'+(d.strategy||'?')+'</strong>'+
        (d.detected_title?' | Title: <em>'+d.detected_title+'</em>':'')+
        (d.suggested_use_browser?' | <span style="color:var(--orange)">Suggests browser</span>':'');
      // auto-fill name + strategy
      var nameEl=document.getElementById('new-target-name');
      if(nameEl&&!nameEl.value){nameEl.value=slugifyDomain(url);}
      var stratEl=document.getElementById('new-target-strategy');
      if(stratEl&&d.strategy){stratEl.value=d.strategy;}
      var articleEl=document.getElementById('new-target-article');
      if(articleEl&&d.is_article_source){articleEl.checked=true;}
      var browserEl=document.getElementById('new-target-browser');
      if(browserEl&&d.suggested_use_browser){browserEl.checked=true;}
    }else{
      resultDiv.innerHTML='<span style="color:var(--red)">&#x2717; Not reachable</span> (status: '+d.status_code+' | content-type: '+d.content_type+')';
    }
  }catch(e){resultDiv.innerHTML='<span style="color:var(--red)">Validation failed: '+e.message+'</span>';}
}

async function addTarget(){
  var url=document.getElementById('new-target-url').value.trim();
  var name=document.getElementById('new-target-name').value.trim();
  if(!url||!name){alert('URL and Site Name are required');return;}
  var interval=parseInt(document.getElementById('new-target-interval').value)||60;
  var strategy=document.getElementById('new-target-strategy').value;
  var useBrowser=document.getElementById('new-target-browser').checked;
  var isArticle=document.getElementById('new-target-article').checked;
  try{
    var r=await fetch('/api/targets',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url:url,site_name:name,interval_minutes:interval,strategy:strategy,use_browser:useBrowser,is_article_source:isArticle})});
    var d=await r.json();
    if(!r.ok){alert(d.error||'Add failed');return;}
    // Clear form
    document.getElementById('new-target-url').value='';
    document.getElementById('new-target-name').value='';
    document.getElementById('new-target-interval').value='60';
    document.getElementById('new-target-strategy').value='auto';
    document.getElementById('new-target-browser').checked=false;
    document.getElementById('new-target-article').checked=false;
    document.getElementById('target-validate-result').innerHTML='';
    document.getElementById('add-target-form').style.display='none';
    loadTargetsConfig();
  }catch(e){alert('Request failed: '+e.message);}
}

async function removeTargetConfig(name){
  if(!confirm('Delete target "'+name+'"? This will stop monitoring but keep existing data.'))return;
  try{
    var r=await fetch('/api/targets/'+encodeURIComponent(name),{method:'DELETE'});
    var d=await r.json();
    if(!r.ok){alert(d.error||'Delete failed');return;}
    loadTargetsConfig();
  }catch(e){alert('Request failed: '+e.message);}
}

async function toggleTargetConfig(name, enabled){
  try{
    var r=await fetch('/api/targets/'+encodeURIComponent(name)+'/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled})});
    var d=await r.json();
    if(!r.ok){alert(d.error||'Toggle failed');return;}
    loadTargetsConfig();
  }catch(e){alert('Request failed: '+e.message);}
}

function editTarget(name){
  var t=null;for(var i=0;i<targetListSave.length;i++){if(targetListSave[i].name===name){t=targetListSave[i];break;}}
  if(!t)return;
  var form=document.getElementById('edit-target-form');
  form.style.display='block';form.setAttribute('data-editing',name);
  document.getElementById('edit-target-interval').value=t.interval_minutes||60;
  document.getElementById('edit-target-strategy').value=t.strategy||'auto';
}

async function saveTargetEdit(){
  var name=document.getElementById('edit-target-form').getAttribute('data-editing');
  if(!name)return;
  var interval=parseInt(document.getElementById('edit-target-interval').value)||60;
  var strategy=document.getElementById('edit-target-strategy').value;
  try{
    var r=await fetch('/api/targets/'+encodeURIComponent(name),{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({interval_minutes:interval,extraction_strategy:strategy})});
    var d=await r.json();
    if(!r.ok){alert(d.error||'Update failed');return;}
    cancelTargetEdit();loadTargetsConfig();
  }catch(e){alert('Request failed: '+e.message);}
}

function cancelTargetEdit(){
  var form=document.getElementById('edit-target-form');
  form.style.display='none';form.setAttribute('data-editing','');
}

function triggerTargetRun(name){
  var t=null;for(var i=0;i<targetListSave.length;i++){if(targetListSave[i].name===name){t=targetListSave[i];break;}}
  if(!t)return;
  var url=t.url||'';var ub=t.use_browser?'true':'false';
  if(!confirm('Trigger a manual run for "'+name+'"?'))return;
  fetch('/api/trigger-run?site='+encodeURIComponent(name)+'&url='+encodeURIComponent(url)+(ub?'&use_browser='+ub:''),{method:'POST'})
    .then(function(r){return r.json();}).then(function(d){alert(d.status||d.error||'Done');}).catch(function(e){alert(e.message);});
}
