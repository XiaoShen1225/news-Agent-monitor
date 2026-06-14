// Operations drawer — alert management, story tracking, target management
var drawerOpsHTML = [
  // ── Preferences & Memory ──
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">'+t('ops_preferences_memory')+'</h2><button onclick="loadPreferences()" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:12px;cursor:pointer;font-size:11px">'+t('ops_refresh')+'</button></div>',
  '<div id="preferences-display" style="margin-top:10px;font-size:13px;color:var(--muted);line-height:1.6">'+t('ops_loading')+'</div>',
  '<div id="memory-status" style="margin-top:8px;font-size:11px;color:var(--muted);padding:6px 10px;background:var(--bg);border-radius:var(--radius-sm);display:flex;gap:16px;flex-wrap:wrap"></div></section>',

  // ── Watch Management ──
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">'+t('ops_watch_management')+'</h2><button onclick="loadWatches(watchTypeFilter)" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:4px 12px;border-radius:12px;cursor:pointer;font-size:11px">'+t('ops_refresh')+'</button></div>',
  '<div class="filters" id="watch-type-tabs" style="margin-top:10px">',
  '<button class="tab active" onclick="loadWatches(\x27\x27)">'+t('ops_watch_all')+'</button>',
  '<button class="tab" onclick="loadWatches(\x27topic\x27)">'+t('ops_watch_topic')+'</button>',
  '<button class="tab" onclick="loadWatches(\x27event\x27)">'+t('ops_watch_event')+'</button></div>',
  '<div id="watches-list" style="margin-top:8px">',
  '<div style="color:var(--muted);padding:12px;text-align:center">'+t('ops_loading')+'</div></div>',
  '<div id="watches-config" style="margin-top:12px;font-size:12px;color:var(--muted);padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);border-left:3px solid var(--accent)"></div></section>',

  // ── Target Management ──
  '<section class="card" style="margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><h2 style="margin:0">'+t('ops_targets_title')+'</h2>',
  '<button onclick="showAddTargetForm()" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:8px 18px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap">'+t('ops_targets_add')+'</button></div>',

  // Add target form (collapsed by default)
  '<div id="add-target-form" style="display:none;margin-top:12px;padding:16px;background:var(--bg);border-radius:var(--radius);border:1px solid var(--border)">',
  '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">',
  '<div><label style="font-size:12px;color:var(--muted)">'+t('ops_targets_url_label')+' <span style="color:var(--red)">'+t('ops_targets_required')+'</span></label>',
  '<input id="new-target-url" type="text" placeholder="https://..." style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none;box-sizing:border-box"></div>',
  '<div><label style="font-size:12px;color:var(--muted)">'+t('ops_targets_name_label')+' <span style="color:var(--red)">'+t('ops_targets_required')+'</span></label>',
  '<input id="new-target-name" type="text" placeholder="my_site" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none;box-sizing:border-box"></div>',
  '<div><label style="font-size:12px;color:var(--muted)">'+t('ops_targets_interval')+'</label>',
  '<select id="new-target-interval" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="5">5</option><option value="10">10</option><option value="15">15</option><option value="30">30</option><option value="60" selected>60</option><option value="120">120</option><option value="360">360</option></select></div>',
  '<div><label style="font-size:12px;color:var(--muted)">'+t('ops_targets_strategy')+'</label>',
  '<select id="new-target-strategy" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="auto" selected>'+t('ops_targets_strategy_auto')+'</option><option value="rss">'+t('ops_targets_strategy_rss')+'</option><option value="llm">'+t('ops_targets_strategy_llm')+'</option><option value="css_selector">'+t('ops_targets_strategy_css')+'</option><option value="section_walk">'+t('ops_targets_strategy_walk')+'</option></select></div>',
  '</div>',
  '<div style="display:flex;gap:16px;align-items:center;margin-top:12px;flex-wrap:wrap">',
  '<label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px"><input type="checkbox" id="new-target-browser"> '+t('ops_targets_use_browser')+'</label>',
  '<label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px"><input type="checkbox" id="new-target-article"> '+t('ops_targets_article_source')+'</label>',
  '<div style="flex:1"></div>',
  '<button onclick="validateTargetUrl()" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;font-size:12px">'+t('ops_targets_validate_url')+'</button>',
  '<button onclick="addTarget()" style="background:linear-gradient(135deg, var(--accent), #2dd4bf);border:none;color:var(--bg);padding:8px 24px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600">'+t('ops_targets_confirm_add')+'</button>',
  '</div>',
  '<div id="target-validate-result" style="margin-top:8px;font-size:12px"></div>',
  '</div>',

  // Edit target form (hidden)
  '<div id="edit-target-form" style="display:none;margin-top:12px;padding:16px;background:var(--bg);border-radius:var(--radius);border:1px solid var(--border)" data-editing="">',
  '<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">',
  '<label style="font-size:12px;color:var(--muted)">'+t('ops_targets_edit_interval')+'</label>',
  '<select id="edit-target-interval" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="5">5</option><option value="10">10</option><option value="15">15</option><option value="30">30</option><option value="60">60</option><option value="120">120</option><option value="360">360</option></select>',
  '<label style="font-size:12px;color:var(--muted)">'+t('ops_targets_strategy')+'</label>',
  '<select id="edit-target-strategy" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:var(--radius-sm);font-size:13px;outline:none">',
  '<option value="auto">'+t('ops_targets_strategy_auto')+'</option><option value="rss">'+t('ops_targets_strategy_rss')+'</option><option value="llm">'+t('ops_targets_strategy_llm')+'</option><option value="css_selector">'+t('ops_targets_strategy_css')+'</option><option value="section_walk">'+t('ops_targets_strategy_walk')+'</option></select>',
  '<button onclick="saveTargetEdit()" style="background:var(--accent);border:none;color:var(--bg);padding:8px 16px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600">'+t('ops_targets_save_btn')+'</button>',
  '<button onclick="cancelTargetEdit()" style="background:var(--bg-tertiary);border:1px solid var(--border);color:var(--muted);padding:8px 16px;border-radius:20px;cursor:pointer;font-size:12px">'+t('ops_targets_cancel_btn')+'</button>',
  '</div></div>',

  // Target table
  '<div style="overflow-x:auto;margin-top:12px"><table><thead><tr><th>'+t('ops_targets_col_name')+'</th><th>'+t('ops_targets_col_url')+'</th><th>'+t('ops_targets_col_interval')+'</th><th>'+t('ops_targets_col_strategy')+'</th><th>'+t('ops_targets_col_browser')+'</th><th>'+t('ops_targets_col_article')+'</th><th>'+t('ops_targets_col_status')+'</th><th>'+t('ops_targets_col_actions')+'</th></tr></thead>',
  '<tbody id="targets-body"><tr><td colspan="8" style="color:var(--muted)">Loading...</td></tr></tbody></table></div></section>'
].join('');

var watchTypeFilter='';
var targetListSave=[];
var _opsCache = {prefs: null, watches: {}, targets: null};

function initOpsDrawer(){loadPreferences();loadWatches('');loadTargetsConfig();}

// ── Preferences & Memory ─────────────────────────────────────────

function renderPreferences(data){
  var pd=data.pd,md=data.md;
  var display=pd.display||t('ops_no_preferences');
  var el=document.getElementById('preferences-display');
  if(el)el.innerHTML=display.replace(/\n/g,'<br>').replace(/\[偏好分析\]/g,'<b>[偏好分析]</b>');
  var ms=document.getElementById('memory-status');
  if(ms){
    var parts=[];
    parts.push('Events: <b>'+(md.total_events||0)+'</b>');
    parts.push('30d clicks: <b>'+(md.stats_30d?.['click_link']||0)+'</b>');
    parts.push('30d searches: <b>'+((md.stats_30d?.['search']||0)+(md.stats_30d?.['filter_tag']||0))+'</b>');
    parts.push('L0 events: <b>'+((md.l0_event_count)||0)+'</b>');
    parts.push('Episodic: <b>'+(md.episodic_count||0)+'</b>');
    if(md.l2&&md.l2.identity)parts.push('Identity: <b>'+md.l2.identity+'</b>');
    ms.innerHTML=parts.join(' | ');
  }
}

async function loadPreferences(){
  try{
    if(_opsCache.prefs&&(Date.now()-_opsCache.prefs.ts<30000)){renderPreferences(_opsCache.prefs.data);return;}
    var pr=await fetch('/api/preferences');var pd=await pr.json();
    var mr=await fetch('/api/memory/status');var md=await mr.json();
    _opsCache.prefs={ts:Date.now(),data:{pd:pd,md:md}};
    renderPreferences(_opsCache.prefs.data);
  }catch(e){console.error('loadPreferences',e);}
}

// ── Watch Management ─────────────────────────────────────────────

async function loadWatches(type){
  watchTypeFilter=type||'';
  var tabs=document.querySelectorAll('#watch-type-tabs .tab');
  tabs.forEach(function(t){
    var tType=t.getAttribute('onclick')||'';
    var matchAll=(type===''||type===undefined)&&t.textContent.trim()==='All';
    var matchTopic=type==='topic'&&t.textContent.trim()==='Topic';
    var matchEvent=type==='event'&&t.textContent.trim()==='Event';
    t.classList.toggle('active',matchAll||matchTopic||matchEvent);
  });
  var cacheKey='watches-'+(type||'all');
  var cached=_opsCache.watches[cacheKey];
  var d;
  if(cached&&(Date.now()-cached.ts<30000)){
    d=cached.data;
  }else{
    try{
      var params=[];
      if(type)params.push('type='+encodeURIComponent(type));
      var r=await fetch('/api/watches'+(params.length?'?'+params.join('&'):''));
      d=await r.json();
      _opsCache.watches[cacheKey]={ts:Date.now(),data:d};
    }catch(e){console.error('loadWatches',e);return;}
  }
  try{
    var watches=d.watches||[];
    var config=d.config||{};
    var stale=d.stale||[];
    var listEl=document.getElementById('watches-list');
    if(!watches.length){
      listEl.innerHTML='<div style="color:var(--muted);padding:12px;text-align:center">No watches yet. Use the AI assistant to start tracking.</div>';
    }else{
      var sc={active:'var(--green)',completed:'var(--muted)',paused:'var(--orange)'};
      var sl={active:t('ops_watch_active'),completed:t('ops_watch_completed'),paused:t('ops_watch_paused')};
      var tc={topic:'var(--accent)',event:'#a78bfa'};
      listEl.innerHTML=watches.map(function(w){
        var color=sc[w.status]||'var(--muted)';
        var label=sl[w.status]||w.status;
        var typeColor=tc[w.type]||'var(--muted)';
        var typeLabel=w.type==='topic'?'Topic':'Event';
        var wid=(w.id||'').replace(/'/g,"\\'");
        var lastMatch=w.last_match_at?w.last_match_at.slice(0,16):'Never';
        return '<div class="watch-card" onclick="openWatchModal(\x27'+wid+'\x27)" style="background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;margin-bottom:6px;cursor:pointer;transition:all var(--transition)">'+
          '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'+
            '<span style="font-weight:500;font-size:13px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(w.title||t('ops_watch_untitled'))+'</span>'+
            '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:8px;color:'+typeColor+';background:'+typeColor+'18">'+typeLabel+'</span>'+
            '<span style="color:'+color+';font-weight:600;font-size:10px;padding:2px 8px;border-radius:8px;background:'+color+'18">'+label+'</span>'+
            '<span style="color:var(--accent);font-size:11px;font-weight:500">'+(w.match_count||0)+' matches</span>'+
            '<span style="color:var(--muted);font-size:10px">'+lastMatch+'</span>'+
          '</div></div>';
      }).join('');
    }
    var cfgEl=document.getElementById('watches-config');
    cfgEl.innerHTML='<strong>Config:</strong> Threshold '+(config.similarity_threshold||0.7)+' | Cooldown '+(config.match_cooldown_hours||12)+'h | Stale prompt after '+(config.stale_prompt_days||14)+'d'+
      (stale.length?' | <span style="color:var(--orange)">'+stale.length+' stale</span>':'');
  }catch(e){console.error('loadWatches',e);}
}

async function openWatchModal(watchId){
  try{
    var wr=await fetch('/api/watches/'+encodeURIComponent(watchId));
    var w=await wr.json();
    if(!w||w.error){alert(w.error||'Watch not found');return;}
    var sr=await fetch('/api/watches/'+encodeURIComponent(watchId)+'/summary');
    var sd=await sr.json();

    var sc={active:'var(--green)',completed:'var(--muted)',paused:'var(--orange)'};
    var sl={active:t('ops_watch_active'),completed:t('ops_watch_completed'),paused:t('ops_watch_paused')};
    var color=sc[w.status]||'var(--muted)';
    var typeColor=w.type==='topic'?'var(--accent)':'#a78bfa';
    var typeLabel=w.type==='topic'?'Topic':'Event';

    // Part 1: latest summary
    var summaryHTML='';
    if(sd.latest_summary){
      summaryHTML='<div class="watch-modal-section"><h3>Latest Summary</h3><div class="watch-summary-block">'+sd.latest_summary.replace(/\n/g,'<br>')+'</div></div>';
    }

    // Part 2+3: match history timeline + related news grid (single pass)
    var timelineHTML='';
    var newsHTML='';
    var matches=w.match_history||[];
    if(matches.length){
      timelineHTML='<div class="watch-modal-section"><h3>Match Timeline ('+matches.length+' items)</h3><div class="watch-timeline">';
      newsHTML='<div class="watch-modal-section"><h3>Related News</h3><div class="watch-news-grid">';
      matches.slice().reverse().forEach(function(m){
        var mu=m.url||'';
        var mt=(m.title||'N/A').slice(0,100);
        // Timeline entry
        var mt_display=mt.slice(0,80);
        if(mu)mt_display='<a href="'+mu+'" target="_blank" style="color:var(--text);text-decoration:none">'+mt_display+'</a>';
        timelineHTML+='<div class="watch-timeline-item">'+
          '<div class="watch-timeline-dot" style="background:'+(m.match_type==='keyword'?'var(--accent)':'#a78bfa')+'"></div>'+
          '<div class="watch-timeline-content">'+
            '<div class="watch-timeline-time">'+(m.time||'').slice(0,16)+' &middot; score: '+(m.score||0).toFixed(3)+' &middot; '+(m.match_type||'semantic')+'</div>'+
            '<div class="watch-timeline-title">'+mt_display+'</div>'+
          '</div></div>';
        // News grid card
        newsHTML+='<div class="watch-news-card">'+
          '<div class="watch-news-score">'+(m.score||0).toFixed(3)+'</div>'+
          '<div class="watch-news-title">'+(mu?'<a href="'+mu+'" target="_blank">'+mt+'</a>':'<span>'+mt+'</span>')+'</div>'+
          '<div class="watch-news-meta">'+(m.time||'').slice(0,16)+' &middot; '+(m.source_site||'')+' &middot; '+(m.match_type||'')+'</div>'+
        '</div>';
      });
      timelineHTML+='</div></div>';
      newsHTML+='</div></div>';
    }else{
      timelineHTML='<div class="watch-modal-section"><h3>Match Timeline</h3><div style="color:var(--muted);font-size:13px;padding:8px 0">No matches yet.</div></div>';
    }

    // Actions
    var actionsHTML='';
    if(w.status==='active'){
      actionsHTML+='<button onclick="event.stopPropagation();completeWatch(\x27'+watchId+'\x27)" class="watch-modal-btn watch-modal-btn-muted">Complete</button>';
      actionsHTML+='<button onclick="event.stopPropagation();pauseWatch(\x27'+watchId+'\x27)" class="watch-modal-btn watch-modal-btn-muted">Pause</button>';
    }else if(w.status==='paused'){
      actionsHTML+='<button onclick="event.stopPropagation();resumeWatch(\x27'+watchId+'\x27)" class="watch-modal-btn watch-modal-btn-accent">Resume</button>';
      actionsHTML+='<button onclick="event.stopPropagation();completeWatch(\x27'+watchId+'\x27)" class="watch-modal-btn watch-modal-btn-muted">Complete</button>';
    }
    actionsHTML+='<button onclick="event.stopPropagation();removeWatch(\x27'+watchId+'\x27,\x27'+(w.title||'').replace(/'/g,"\\'").slice(0,40)+'\x27)" class="watch-modal-btn watch-modal-btn-danger">Delete</button>';

    var modalHTML=
      '<div class="watch-modal-overlay" id="watch-modal-overlay" onclick="closeWatchModal()">'+
        '<div class="watch-modal" onclick="event.stopPropagation()">'+
          '<div class="watch-modal-header">'+
            '<div><h2 style="margin:0;font-size:16px">'+(w.title||t('ops_watch_detail'))+'</h2>'+
            '<span style="font-size:11px;color:var(--muted)">'+(w.keywords||[]).join(', ')+' &middot; ID: '+(w.id||'').slice(0,10)+'</span></div>'+
            '<div style="display:flex;gap:6px;align-items:center">'+
              '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:8px;color:'+typeColor+';background:'+typeColor+'18">'+typeLabel+'</span>'+
              '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:8px;color:'+color+';background:'+color+'18">'+(sl[w.status]||w.status)+'</span>'+
              '<button onclick="closeWatchModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--muted);padding:0 4px;line-height:1">&times;</button>'+
            '</div>'+
          '</div>'+
          '<div class="watch-modal-body">'+
            summaryHTML+
            timelineHTML+
            newsHTML+
          '</div>'+
          '<div class="watch-modal-footer">'+actionsHTML+'</div>'+
        '</div>'+
      '</div>';
    document.body.insertAdjacentHTML('beforeend',modalHTML);
  }catch(e){console.error('openWatchModal',e);}
}

function closeWatchModal(){
  var overlay=document.getElementById('watch-modal-overlay');
  if(overlay)overlay.remove();
}

async function completeWatch(id){
  if(!confirm('Mark this watch as completed?'))return;
  try{var r=await fetch('/api/watches/'+encodeURIComponent(id)+'/complete',{method:'POST'});if(!r.ok){var d=await r.json();alert(d.error||'Failed');return;}
    closeWatchModal();loadWatches(watchTypeFilter);}catch(e){alert('Request failed: '+e.message);}}

async function pauseWatch(id){
  if(!confirm('Pause this watch?'))return;
  try{var r=await fetch('/api/watches/'+encodeURIComponent(id)+'/pause',{method:'POST'});if(!r.ok){var d=await r.json();alert(d.error||'Failed');return;}
    closeWatchModal();loadWatches(watchTypeFilter);}catch(e){alert('Request failed: '+e.message);}}

async function resumeWatch(id){
  if(!confirm('Resume this watch?'))return;
  try{var r=await fetch('/api/watches/'+encodeURIComponent(id)+'/resume',{method:'POST'});if(!r.ok){var d=await r.json();alert(d.error||'Failed');return;}
    closeWatchModal();loadWatches(watchTypeFilter);}catch(e){alert('Request failed: '+e.message);}}

async function removeWatch(id,title){
  if(!confirm('Delete watch "'+title.slice(0,50)+'"?'))return;
  try{var r=await fetch('/api/watches/'+encodeURIComponent(id),{method:'DELETE'});if(!r.ok){var d=await r.json();alert(d.error||'Delete failed');return;}
    closeWatchModal();loadWatches(watchTypeFilter);}catch(e){alert('Request failed: '+e.message);}}

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
    .then(function(r){return r.json();}).then(function(d){if(d.status==='accepted'){showToast(t('ops_run_accepted',{site:name}));}else{showToast(d.error||d.status||'Done','error');}}).catch(function(e){showToast(e.message,'error');});
}
