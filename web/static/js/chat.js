// Chat: session management + SSE streaming + message rendering
// Built-in markdown renderer — no CDN dependency

var chatAbortController=null;

// ── Built-in markdown → HTML renderer ─────────────────────────────
function renderMarkdown(text){
  if(!text)return '';
  // Escape HTML entities first, then convert markdown to HTML
  var h=text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // Headings
  h=h.replace(/^### (.+)$/gm,'<h4>$1</h4>');
  h=h.replace(/^## (.+)$/gm,'<h3>$1</h3>');
  h=h.replace(/^# (.+)$/gm,'<h2>$1</h2>');
  // Bold & italic
  h=h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  h=h.replace(/\*(.+?)\*/g,'<em>$1</em>');
  // Inline code
  h=h.replace(/`([^`]+)`/g,'<code>$1</code>');
  // Links
  h=h.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank">$1</a>');
  // Unordered list items — wrap consecutive <li> in <ul>
  h=h.replace(/^[\-*] (.+)$/gm,'<li>$1</li>');
  h=h.replace(/((?:<li>.*<\/li>\n?)+)/g,'<ul>$1</ul>');
  // Double newline → paragraph break
  h=h.replace(/\n\n/g,'<br><br>');
  // Single newline → <br>
  h=h.replace(/\n/g,'<br>');
  return h;
}

function getSessionId(){
  var s=localStorage.getItem('chat_session_id');
  if(!s){s=crypto.randomUUID?crypto.randomUUID():'s_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
    localStorage.setItem('chat_session_id',s);}
  return s;
}
function setSessionId(s){if(s)localStorage.setItem('chat_session_id',s);}

async function loadSessions(){
  try{var r=await fetch('/api/chat/sessions');var d=await r.json();
    var ss=d.sessions||[];var list=document.getElementById('session-list');
    var cs=getSessionId();list.innerHTML=ss.map(function(s){
      var l=(s.title||s.id||'').slice(0,20)||'No title';
      var a=s.id===cs?' active':'';
      return '<div class="session-item'+a+'" onclick="switchSession(\x27'+s.id+'\x27)" title="'+s.id+'">'+l+
        '<span class="session-del" onclick="event.stopPropagation();deleteSession(\x27'+s.id+'\x27)" title=\u5220\u9664\u4f1a\u8bdd>&times;</span></div>';
    }).join('');}catch(e){}
}

async function deleteSession(sid){
  if(!confirm('\u786e\u5b9a\u5220\u9664\u8be5\u4f1a\u8bdd\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53ef\u64a4\u9500\u3002'))return;
  try{await fetch('/api/chat/sessions/'+encodeURIComponent(sid),{method:'DELETE'});
    if(getSessionId()===sid){localStorage.removeItem('chat_session_id');resetChatWelcome();}
    loadSessions();}catch(e){}
}

function newChatSession(){
  var ns=crypto.randomUUID?crypto.randomUUID():'s_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
  localStorage.setItem('chat_session_id',ns);
  resetChatWelcome();loadSessions();
}

function switchSession(sid){
  localStorage.setItem('chat_session_id',sid);
  document.getElementById('chat-messages').innerHTML='<div class="chat-welcome"><div class="chat-welcome-icon">&#x1f4ac;</div><div style="font-size:15px;font-weight:500;color:var(--text-secondary);margin-bottom:6px">AI \u76d1\u63a7\u6570\u636e\u52a9\u624b</div><div style="font-size:13px;line-height:1.7">\u52a0\u8f7d\u5386\u53f2\u6d88\u606f\u4e2d...</div></div>';
  loadChatHistory().then(function(){
    var c=document.getElementById('chat-messages');
    if(!c.querySelector('.chat-bubble')){resetChatWelcome();}
  });
  loadSessions();
}

function resetChatWelcome(){
  var el=document.getElementById('chat-messages');
  el.innerHTML='<div class="chat-welcome"><div class="chat-welcome-icon">&#x1f4ac;</div><div style="font-size:15px;font-weight:500;color:var(--text-secondary);margin-bottom:6px">AI \u76d1\u63a7\u6570\u636e\u52a9\u624b</div><div style="font-size:13px;line-height:1.7">\u53ef\u4ee5\u67e5\u8be2\u65b0\u95fb\u3001\u7edf\u8ba1\u3001\u641c\u7d22\u6587\u7ae0<br>\u8bd5\u8bd5\u95ee\uff1a"\u6709\u54ea\u4e9b\u76d1\u63a7\u7ad9\u70b9\uff1f" \u6216"\u6700\u8fd1\u6709\u54ea\u4e9b\u79d1\u6280\u65b0\u95fb\uff1f"</div></div><div class="chat-chips"><button onclick="askExample(\x27\u4eca\u5929\u6709\u4ec0\u4e48\u79d1\u6280\u65b0\u95fb\uff1f\x27)" class="chat-chip">\u4eca\u5929\u6709\u4ec0\u4e48\u79d1\u6280\u65b0\u95fb\uff1f</button><button onclick="askExample(\x27\u6700\u8fd1\u4e00\u5468\u6709\u4ec0\u4e48\u70ed\u70b9\u8d8b\u52bf\uff1f\x27)" class="chat-chip">\u6700\u8fd1\u4e00\u5468\u6709\u4ec0\u4e48\u70ed\u70b9\u8d8b\u52bf\uff1f</button><button onclick="askExample(\x27\u767e\u5ea6\u65b0\u95fb\u8fd0\u884c\u6b63\u5e38\u5417\uff1f\x27)" class="chat-chip">\u767e\u5ea6\u65b0\u95fb\u8fd0\u884c\u6b63\u5e38\u5417\uff1f</button><button onclick="askExample(\x27\u5e2e\u6211\u8bbe\u7f6e\u4e00\u4e2aAI\u76f8\u5173\u7684\u544a\u8b66\x27)" class="chat-chip">\u5e2e\u6211\u8bbe\u7f6e\u4e00\u4e2aAI\u76f8\u5173\u544a\u8b66</button></div>';
  document.getElementById('chat-tool-trace').innerHTML='';
  var bar=document.getElementById('chat-context-bar');if(bar)bar.style.display='none';
}

async function loadChatHistory(){
  var sid=getSessionId();
  try{var r=await fetch('/api/chat/history?session_id='+encodeURIComponent(sid));var d=await r.json();
    if(d.not_found){localStorage.removeItem('chat_session_id');resetChatWelcome();loadSessions();return;}
    if(!d.messages||d.messages.length===0)return;
    var c=document.getElementById('chat-messages');if(c.querySelector('.chat-bubble'))return;c.innerHTML='';
    var prevRole='';var pendingChips=[];
    d.messages.forEach(function(m){
      if(m.role==='tool')return;
      if(m.role==='assistant'&&(!m.content||!m.content.trim())&&m.tool_calls){
        // Stub: collect tool names for next assistant bubble
        pendingChips=pendingChips.concat(m.tool_calls);
        return;
      }
      if(m.role==='assistant'&&m.tool_calls&&m.tool_calls.length>0){
        pendingChips=pendingChips.concat(m.tool_calls);
      }
      // Flush pending tool chips into the trace before rendering bubble
      if(pendingChips.length>0){
        renderToolCallChips({tool_calls:pendingChips});
        pendingChips=[];
      }
      if(m.role==='assistant'&&prevRole==='assistant'){
        var bubbles=c.querySelectorAll('.chat-bubble.assistant');
        var last=bubbles[bubbles.length-1];
        if(last){var cd=last.querySelector('.chat-bubble-content');
          cd.innerHTML+=renderMarkdown('\n\n'+m.content);
        }
      }else{
        appendChatMessage(m.role,m.content||'');
      }
      prevRole=m.role;
    });c.scrollTop=c.scrollHeight;
  }catch(e){}
}

function renderToolCallChips(m){
  var trace=document.getElementById('chat-tool-trace');
  if(!trace)return;
  (m.tool_calls||[]).forEach(function(tc){
    var name=tc.function?tc.function.name:(tc.name||'');
    if(!name)return;
    var chip=document.createElement('span');
    chip.textContent='\u{1F527} '+name;
    chip.style.cssText='font-size:11px;padding:2px 8px;margin:0 3px;border-radius:12px;background:var(--bg-tertiary);color:var(--muted);display:inline-block;';
    trace.appendChild(chip);
  });
}

function askExample(q){document.getElementById('chat-input').value=q;sendChat();}

async function sendChat(){
  var inp=document.getElementById('chat-input');var msg=inp.value.trim();if(!msg)return;
  appendChatMessage('user',msg);inp.value='';
  var sb=document.getElementById('chat-send-btn');sb.disabled=true;
  var aiBubble=appendChatMessage('assistant','');
  var aiContent=aiBubble.querySelector('.chat-bubble-content');
  var traceEl=document.getElementById('chat-tool-trace');traceEl.innerHTML='';
  var oldCards=document.querySelectorAll('.thinking-card');for(var oi=0;oi<oldCards.length;oi++)oldCards[oi].remove();
  if(chatAbortController)chatAbortController.abort();chatAbortController=new AbortController();
  var sid=getSessionId();
  try{
    var res=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg,session_id:sid}),signal:chatAbortController.signal});
    var reader=res.body.getReader();var decoder=new TextDecoder();var buffer='';var tc=null;
    var toolResults=[];var toolResultsRendered=false;
    var streamRaw=''; // accumulate raw text for real-time markdown rendering
    var container=document.getElementById('chat-messages');
    var cb=document.getElementById('chat-context-bar');var cf=document.getElementById('chat-context-fill');
    var ct=document.getElementById('chat-context-text');
    while(true){
      var rr=await reader.read();if(rr.done)break;
      buffer+=decoder.decode(rr.value,{stream:true});
      var lines=buffer.split('\n');buffer=lines.pop()||'';
      var event='',data='';
      for(var i=0;i<lines.length;i++){var line=lines[i];
        if(line.startsWith('event: '))event=line.slice(7);
        else if(line.startsWith('data: ')){data=line.slice(6);
          if(event&&data){try{var parsed=JSON.parse(data);
            if(event==='token'){
              if(!toolResultsRendered&&toolResults.length>0){toolResultsRendered=true;
                var trBlock='<div class="tool-results-block">';
                for(var j=0;j<toolResults.length;j++){
                  var tr=toolResults[j];var rText=tr.result||'';
                  var imgHTML='';
                  rText=rText.replace(/[\r\n]*\[配图\]\s*(https?:\/\/\S+)[\r\n]*/g,function(m,imgUrl){
                    imgHTML='<a href="'+imgUrl+'" target="_blank"><img src="'+imgUrl+'" class="tool-result-img" loading="lazy" onerror="this.style.display=\'none\'" alt="\u914d\u56fe"></a>';
                    return '';
                  });
                  if(rText.length>800)rText=rText.slice(0,800)+'...';
                  trBlock+='<details class="tool-result-detail"><summary>\u{1F527} '+tr.name+'</summary><pre>'+rText.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</pre>'+imgHTML+'</details>';
                }
                trBlock+='</div>';aiContent.innerHTML=trBlock;
              }
              streamRaw+=parsed;
              aiContent.innerHTML=renderMarkdown(streamRaw);
              container.scrollTop=container.scrollHeight;
            }
            else if(event==='thinking'){if(!tc){tc=document.createElement('div');tc.className='thinking-card';container.appendChild(tc);}tc.textContent=parsed.text;container.scrollTop=container.scrollHeight;}
            else if(event==='tool_call'){var chip=document.createElement('span');chip.className='tool-call-chip';chip.textContent=parsed.tool;traceEl.appendChild(chip);}
            else if(event==='tool_result'){
              var chips=traceEl.querySelectorAll('span');if(chips.length>0){var last=chips[chips.length-1];last.textContent+=' \u2713';last.style.color='var(--green)';}
              toolResults.push({name:parsed.tool,result:parsed.result});
            }
            else if(event==='status'){traceEl.innerHTML='<span style="font-size:11px;color:var(--muted)">'+parsed+'</span>';}
            else if(event==='context'){cb.style.display='flex';var mx=parsed.max_history_tokens||4000;var pct=Math.min(100,(parsed.history_tokens/mx)*100);cf.style.width=pct+'%';ct.textContent=parsed.history_tokens+'/'+mx+' tokens ('+(parsed.exchanges||0)+'\u8f6e)';if(pct>80)cf.style.background='#f59e0b';}
            else if(event==='done'){if(parsed.session_id)setSessionId(parsed.session_id);traceEl.innerHTML='';if(tc){tc.remove();tc=null;}loadSessions();}
          }catch(e){}event='';data='';}}
      }
    }
  }catch(e){if(e.name!=='AbortError'){aiContent.textContent=aiContent.textContent||'\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002';}}
  if(!aiContent.textContent.trim()){aiContent.textContent='(\u7a7a\u56de\u590d)';}
  chatAbortController=null;sb.disabled=false;inp.focus();
}

function appendChatMessage(role,content){
  var c=document.getElementById('chat-messages');var ph=c.querySelector('.chat-welcome');if(ph)ph.remove();
  var isUser=role==='user';var bubble=document.createElement('div');
  bubble.className='chat-bubble '+(isUser?'user':'assistant');
  var label=document.createElement('div');label.className='chat-bubble-label';
  label.textContent=isUser?'You':'AI \u52a9\u624b';
  var cd=document.createElement('div');cd.className='chat-bubble-content';
  if(!isUser&&content){cd.innerHTML=renderMarkdown(content);}
  else{cd.textContent=content;}
  bubble.appendChild(label);bubble.appendChild(cd);
  c.appendChild(bubble);c.scrollTop=c.scrollHeight;return bubble;
}

async function clearChat(){
  try{var sid=getSessionId();await fetch('/api/chat?session_id='+encodeURIComponent(sid),{method:'DELETE'});}catch(e){}
  resetChatWelcome();document.getElementById('chat-tool-trace').innerHTML='';
  var bar=document.getElementById('chat-context-bar');if(bar)bar.style.display='none';
}
