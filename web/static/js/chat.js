// Chat: session management + SSE streaming + message rendering
// Built-in markdown renderer — no CDN dependency

let chatAbortController=null;

// ── Built-in markdown → HTML renderer ─────────────────────────────
function renderMarkdown(text){
  if(!text)return '';
  let h=text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  h=h.replace(/^### (.+)$/gm,'<h4>$1</h4>');
  h=h.replace(/^## (.+)$/gm,'<h3>$1</h3>');
  h=h.replace(/^# (.+)$/gm,'<h2>$1</h2>');
  h=h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  h=h.replace(/\*(.+?)\*/g,'<em>$1</em>');
  h=h.replace(/`([^`]+)`/g,'<code>$1</code>');
  h=h.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank">$1</a>');
  h=h.replace(/^[\-*] (.+)$/gm,'<li>$1</li>');
  h=h.replace(/((?:<li>.*<\/li>\n?)+)/g,'<ul>$1</ul>');
  h=h.replace(/\n\n/g,'<br><br>');
  h=h.replace(/\n/g,'<br>');
  return h;
}

function getSessionId(){
  let s=localStorage.getItem('chat_session_id');
  if(!s){s=crypto.randomUUID?crypto.randomUUID():'s_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
    localStorage.setItem('chat_session_id',s);}
  return s;
}
function setSessionId(s){if(s)localStorage.setItem('chat_session_id',s);}

async function loadSessions(){
  try{let r=await fetch('/api/chat/sessions');let d=await r.json();
    let ss=d.sessions||[];let list=document.getElementById('session-list');
    let cs=getSessionId();list.innerHTML=ss.map(function(s){
      let l=(s.title||s.id||'').slice(0,20)||t('chat_no_title');
      let a=s.id===cs?' active':'';
      return '<div class="session-item'+a+'" onclick="switchSession(\x27'+s.id+'\x27)" title="'+s.id+'">'+l+
        '<span class="session-del" onclick="event.stopPropagation();deleteSession(\x27'+s.id+'\x27)" title="'+t('ops_watch_delete_btn')+'">&times;</span></div>';
    }).join('');}catch(e){}
}

async function deleteSession(sid){
  if(!confirm(t('chat_session_delete_confirm')))return;
  try{await fetch('/api/chat/sessions/'+encodeURIComponent(sid),{method:'DELETE'});
    if(getSessionId()===sid){localStorage.removeItem('chat_session_id');resetChatWelcome();}
    loadSessions();}catch(e){}
}

function newChatSession(){
  let ns=crypto.randomUUID?crypto.randomUUID():'s_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
  localStorage.setItem('chat_session_id',ns);
  resetChatWelcome();loadSessions();
}

function buildWelcomeHTML(){
  return '<div class="chat-welcome"><div class="chat-welcome-icon">💬</div><div style="font-size:15px;font-weight:500;color:var(--text-secondary);margin-bottom:6px">'+t('chat_welcome_title')+'</div><div style="font-size:13px;line-height:1.7">'+t('chat_welcome_desc')+'</div></div><div class="chat-chips"><button onclick="askExample(t(\x27chip_tech_news\x27))" class="chat-chip">'+t('chip_tech_news')+'</button><button onclick="askExample(t(\x27chip_hot_trends\x27))" class="chat-chip">'+t('chip_hot_trends')+'</button><button onclick="askExample(t(\x27chip_baidu_health\x27))" class="chat-chip">'+t('chip_baidu_health')+'</button><button onclick="askExample(t(\x27chip_set_alert\x27))" class="chat-chip">'+t('chip_set_alert')+'</button></div>';
}

function switchSession(sid){
  localStorage.setItem('chat_session_id',sid);
  document.getElementById('chat-messages').innerHTML='<div class="chat-welcome"><div class="chat-welcome-icon">💬</div><div style="font-size:15px;font-weight:500;color:var(--text-secondary);margin-bottom:6px">'+t('chat_welcome_title')+'</div><div style="font-size:13px;line-height:1.7">'+t('chat_loading_history')+'</div></div>';
  let trace=document.getElementById('chat-tool-trace');if(trace)trace.innerHTML='';
  loadChatHistory().then(function(){
    let c=document.getElementById('chat-messages');
    if(!c.querySelector('.chat-bubble')){resetChatWelcome();}
  });
  loadSessions();
}

function resetChatWelcome(){
  let el=document.getElementById('chat-messages');
  el.innerHTML=buildWelcomeHTML();
  document.getElementById('chat-tool-trace').innerHTML='';
  let bar=document.getElementById('chat-context-bar');if(bar)bar.style.display='none';
}

async function loadChatHistory(){
  let sid=getSessionId();
  try{let r=await fetch('/api/chat/history?session_id='+encodeURIComponent(sid));let d=await r.json();
    if(d.not_found){localStorage.removeItem('chat_session_id');resetChatWelcome();loadSessions();return;}
    if(!d.messages||d.messages.length===0)return;
    let c=document.getElementById('chat-messages');if(c.querySelector('.chat-bubble'))return;c.innerHTML='';
    c.style.display='none';
    let trace=document.getElementById('chat-tool-trace');if(trace)trace.innerHTML='';
    let prevRole='';let pendingChips=[];
    d.messages.forEach(function(m){
      if(m.role==='tool')return;
      if(m.role==='assistant'&&(!m.content||!m.content.trim())&&m.tool_calls){
        pendingChips=pendingChips.concat(m.tool_calls);
        return;
      }
      if(m.role==='assistant'&&m.tool_calls&&m.tool_calls.length>0){
        pendingChips=pendingChips.concat(m.tool_calls);
      }
      if(pendingChips.length>0){
        renderToolCallChips({tool_calls:pendingChips});
        pendingChips=[];
      }
      if(m.role==='assistant'&&prevRole==='assistant'){
        let bubbles=c.querySelectorAll('.chat-bubble.assistant');
        let last=bubbles[bubbles.length-1];
        if(last){let cd=last.querySelector('.chat-bubble-content');
          cd.innerHTML+=renderMarkdown('\n\n'+m.content);
        }
      }else{
        appendChatMessage(m.role,m.content||'');
      }
      prevRole=m.role;
    });c.style.display='';c.scrollTop=c.scrollHeight;
  }catch(e){}
}

function renderToolCallChips(m){
  let trace=document.getElementById('chat-tool-trace');
  if(!trace)return;
  (m.tool_calls||[]).forEach(function(tc){
    let name=tc.function?tc.function.name:(tc.name||'');
    if(!name)return;
    let chip=document.createElement('span');
    chip.textContent=t('chat_tool_prefix')+name;
    chip.style.cssText='font-size:11px;padding:2px 8px;margin:0 3px;border-radius:12px;background:var(--bg-tertiary);color:var(--muted);display:inline-block;';
    trace.appendChild(chip);
  });
}

function askExample(q){document.getElementById('chat-input').value=q;sendChat();}

async function sendChat(){
  let inp=document.getElementById('chat-input');let msg=inp.value.trim();if(!msg)return;
  appendChatMessage('user',msg);inp.value='';
  let sb=document.getElementById('chat-send-btn');sb.disabled=true;
  let aiBubble=appendChatMessage('assistant','');
  let aiContent=aiBubble.querySelector('.chat-bubble-content');
  let traceEl=document.getElementById('chat-tool-trace');traceEl.innerHTML='';
  let oldCards=document.querySelectorAll('.thinking-card');for(let oi=0;oi<oldCards.length;oi++)oldCards[oi].remove();
  if(chatAbortController)chatAbortController.abort();chatAbortController=new AbortController();
  let sid=getSessionId();
  try{
    let res=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg,session_id:sid}),signal:chatAbortController.signal});
    let reader=res.body.getReader();let decoder=new TextDecoder();let buffer='';let tc=null;
    let toolResults=[];let toolResultsRendered=false;
    let streamRaw='';let lastRenderedLen=0;
    let container=document.getElementById('chat-messages');
    let cb=document.getElementById('chat-context-bar');let cf=document.getElementById('chat-context-fill');
    let ct=document.getElementById('chat-context-text');
    // Helper: flush accumulated markdown text, rendering only new portions
    function flushStream(force){
      if(lastRenderedLen>=streamRaw.length)return;
      let delta=streamRaw.slice(lastRenderedLen);
      if(!force){
        let lastNL=delta.lastIndexOf('\n');
        if(lastNL===-1)return;  // wait for a newline boundary for correct markdown
        delta=delta.slice(0,lastNL+1);
      }
      if(!delta)return;
      // First render: replace placeholder, subsequent: append
      if(lastRenderedLen===0){aiContent.innerHTML=renderMarkdown(delta);}
      else{aiContent.insertAdjacentHTML('beforeend',renderMarkdown(delta));}
      lastRenderedLen+=delta.length;
      // Only auto-scroll if user is near the bottom
      if(container.scrollHeight-container.scrollTop-container.clientHeight<80){
        container.scrollTop=container.scrollHeight;
      }
    }
    while(true){
      let rr=await reader.read();if(rr.done)break;
      buffer+=decoder.decode(rr.value,{stream:true});
      let lines=buffer.split('\n');buffer=lines.pop()||'';
      let event='',data='';
      for(let i=0;i<lines.length;i++){let line=lines[i];
        if(line.startsWith('event: '))event=line.slice(7);
        else if(line.startsWith('data: ')){data=line.slice(6);
          if(event&&data){try{let parsed=JSON.parse(data);
            if(event==='token'){
              if(!toolResultsRendered&&toolResults.length>0){toolResultsRendered=true;
                let trBlock='<div class="tool-results-block">';
                for(let j=0;j<toolResults.length;j++){
                  let tr=toolResults[j];let rText=tr.result||'';
                  if(rText.length>800)rText=rText.slice(0,800)+'...';
                  trBlock+='<details class="tool-result-detail"><summary>'+t('chat_tool_prefix')+tr.name+'</summary><pre>'+rText.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</pre></details>';
                }
                trBlock+='</div>';aiContent.innerHTML=trBlock;
              }
              streamRaw+=parsed;
              flushStream(false);
            }
            else if(event==='thinking'){if(!tc){tc=document.createElement('div');tc.className='thinking-card';container.appendChild(tc);}tc.textContent=parsed.text;container.scrollTop=container.scrollHeight;}
            else if(event==='tool_call'){let chip=document.createElement('span');chip.className='tool-call-chip';chip.textContent=parsed.tool;traceEl.appendChild(chip);}
            else if(event==='tool_result'){
              let chips=traceEl.querySelectorAll('span');if(chips.length>0){let last=chips[chips.length-1];last.textContent+=' ✓';last.style.color='var(--green)';}
              toolResults.push({name:parsed.tool,result:parsed.result});
            }
            else if(event==='status'){traceEl.innerHTML='<span style="font-size:11px;color:var(--muted)">'+parsed+'</span>';}
            else if(event==='context'){cb.style.display='flex';let mx=parsed.max_history_tokens||4000;let pct=Math.min(100,(parsed.history_tokens/mx)*100);cf.style.width=pct+'%';ct.textContent=t('chat_token_bar',{used:parsed.history_tokens,max:mx,exchanges:parsed.exchanges||0});if(pct>80)cf.style.background='#f59e0b';}
            else if(event==='done'){flushStream(true);if(parsed.session_id)setSessionId(parsed.session_id);traceEl.innerHTML='';if(tc){tc.remove();tc=null;}loadSessions();}
          }catch(e){}event='';data='';}}
      }
    }
  }catch(e){if(e.name!=='AbortError'){aiContent.textContent=aiContent.textContent||t('chat_request_failed');showToast(t('chat_send_failed_toast'), 'error');};traceEl.innerHTML='';if(tc){tc.remove();tc=null;}}
  flushStream(true); // flush any remaining unrendered text
  if(!aiContent.textContent.trim()&&!aiContent.querySelector('*')){aiContent.textContent=t('chat_empty_reply');}
  chatAbortController=null;sb.disabled=false;inp.focus();
}

function appendChatMessage(role,content){
  let c=document.getElementById('chat-messages');let ph=c.querySelector('.chat-welcome');if(ph)ph.remove();
  let isUser=role==='user';let bubble=document.createElement('div');
  bubble.className='chat-bubble '+(isUser?'user':'assistant');
  let label=document.createElement('div');label.className='chat-bubble-label';
  label.textContent=isUser?t('chat_you'):t('chat_ai_label');
  let cd=document.createElement('div');cd.className='chat-bubble-content';
  if(!isUser&&content){cd.innerHTML=renderMarkdown(content);}
  else{cd.textContent=content;}
  bubble.appendChild(label);bubble.appendChild(cd);
  c.appendChild(bubble);c.scrollTop=c.scrollHeight;return bubble;
}

async function clearChat(){
  try{let sid=getSessionId();await fetch('/api/chat?session_id='+encodeURIComponent(sid),{method:'DELETE'});}catch(e){}
  resetChatWelcome();document.getElementById('chat-tool-trace').innerHTML='';
  let bar=document.getElementById('chat-context-bar');if(bar)bar.style.display='none';
}
