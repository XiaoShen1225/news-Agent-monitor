// Chat: session management + SSE streaming + message rendering
if(typeof marked!=='undefined'){marked.setOptions({breaks:true,gfm:true});}

var chatAbortController=null;

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
      return '<div class="session-item'+a+'" onclick="switchSession(\x27'+s.id+'\x27)" title="'+s.id+'">'+l+'</div>';
    }).join('');}catch(e){}
}

function newChatSession(){
  var ns=crypto.randomUUID?crypto.randomUUID():'s_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
  localStorage.setItem('chat_session_id',ns);
  resetChatWelcome();loadSessions();
}

function switchSession(sid){
  localStorage.setItem('chat_session_id',sid);
  document.getElementById('chat-messages').innerHTML='<div class="chat-welcome"><div class="chat-welcome-icon">&#x1f4ac;</div><div style="font-size:15px;font-weight:500;color:var(--text-secondary);margin-bottom:6px">AI \u76d1\u63a7\u6570\u636e\u52a9\u624b</div><div style="font-size:13px;line-height:1.7">\u52a0\u8f7d\u5386\u53f2\u6d88\u606f\u4e2d...</div></div>';
  loadChatHistory();loadSessions();
}

function resetChatWelcome(){
  var el=document.getElementById('chat-messages');
  el.innerHTML='<div class="chat-welcome"><div class="chat-welcome-icon">&#x1f4ac;</div><div style="font-size:15px;font-weight:500;color:var(--text-secondary);margin-bottom:6px">AI &#x76d1;&#x63a7;&#x6570;&#x636e;&#x52a9;&#x624b;</div><div style="font-size:13px;line-height:1.7">&#x53ef;&#x4ee5;&#x67e5;&#x8be2;&#x65b0;&#x95fb;&#x3001;&#x7edf;&#x8ba1;&#x3001;&#x641c;&#x7d22;&#x6587;&#x7ae0;<br>&#x8bd5;&#x8bd5;&#x95ee;&#xff1a;"&#x6709;&#x54ea;&#x4e9b;&#x76d1;&#x63a7;&#x7ad9;&#x70b9;&#xff1f;" &#x6216;"&#x6700;&#x8fd1;&#x6709;&#x54ea;&#x4e9b;&#x79d1;&#x6280;&#x65b0;&#x95fb;&#xff1f;"</div></div><div class="chat-chips"><button onclick="askExample(\x27&#x4eca;&#x5929;&#x6709;&#x4ec0;&#x4e48;&#x79d1;&#x6280;&#x65b0;&#x95fb;&#xff1f;\x27)" class="chat-chip">&#x4eca;&#x5929;&#x6709;&#x4ec0;&#x4e48;&#x79d1;&#x6280;&#x65b0;&#x95fb;&#xff1f;</button><button onclick="askExample(\x27&#x6700;&#x8fd1;&#x4e00;&#x5468;&#x6709;&#x4ec0;&#x4e48;&#x70ed;&#x70b9;&#x8d8b;&#x52bf;&#xff1f;\x27)" class="chat-chip">&#x6700;&#x8fd1;&#x4e00;&#x5468;&#x6709;&#x4ec0;&#x4e48;&#x70ed;&#x70b9;&#x8d8b;&#x52bf;&#xff1f;</button><button onclick="askExample(\x27&#x767e;&#x5ea6;&#x65b0;&#x95fb;&#x8fd0;&#x884c;&#x6b63;&#x5e38;&#x5417;&#xff1f;\x27)" class="chat-chip">&#x767e;&#x5ea6;&#x65b0;&#x95fb;&#x8fd0;&#x884c;&#x6b63;&#x5e38;&#x5417;&#xff1f;</button><button onclick="askExample(\x27&#x5e2e;&#x6211;&#x8bbe;&#x7f6e;&#x4e00;&#x4e2a;AI&#x76f8;&#x5173;&#x7684;&#x544a;&#x8b66;\x27)" class="chat-chip">&#x5e2e;&#x6211;&#x8bbe;&#x7f6e;&#x4e00;&#x4e2a;AI&#x76f8;&#x5173;&#x544a;&#x8b66;</button></div>';
  document.getElementById('chat-tool-trace').innerHTML='';
  var bar=document.getElementById('chat-context-bar');if(bar)bar.style.display='none';
}

async function loadChatHistory(){
  var sid=getSessionId();
  try{var r=await fetch('/api/chat/history?session_id='+encodeURIComponent(sid));var d=await r.json();
    if(!d.messages||d.messages.length===0)return;
    var c=document.getElementById('chat-messages');if(c.querySelector('.chat-bubble'))return;c.innerHTML='';
    d.messages.forEach(function(m){appendChatMessage(m.role,m.content||'');});c.scrollTop=c.scrollHeight;
  }catch(e){}
}

function askExample(q){document.getElementById('chat-input').value=q;sendChat();}

async function sendChat(){
  var inp=document.getElementById('chat-input');var msg=inp.value.trim();if(!msg)return;
  appendChatMessage('user',msg);inp.value='';
  var sb=document.getElementById('chat-send-btn');sb.disabled=true;
  var aiBubble=appendChatMessage('assistant','');
  var aiContent=aiBubble.querySelector('.chat-bubble-content');
  var traceEl=document.getElementById('chat-tool-trace');traceEl.textContent='';
  if(chatAbortController)chatAbortController.abort();chatAbortController=new AbortController();
  var sid=getSessionId();
  try{
    var res=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg,session_id:sid}),signal:chatAbortController.signal});
    var reader=res.body.getReader();var decoder=new TextDecoder();var buffer='';var tc=null;
    var toolResults=[];var toolResultsRendered=false;
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
                  var tr=toolResults[j];var rText=tr.result||'';if(rText.length>800)rText=rText.slice(0,800)+'...';
                  trBlock+='<details class="tool-result-detail"><summary>\u{1F527} '+tr.name+'</summary><pre>'+rText.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</pre></details>';
                }
                trBlock+='</div>';aiContent.innerHTML=trBlock;
              }
              aiContent.innerHTML+=parsed.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
            else if(event==='done'){if(parsed.session_id)setSessionId(parsed.session_id);traceEl.innerHTML='';if(tc){tc.style.opacity='0.3';tc.style.fontSize='11px';}loadSessions();}
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
  if(!isUser&&typeof marked!=='undefined'&&content){cd.innerHTML=marked.parse(content);}
  else{cd.textContent=content;}
  bubble.appendChild(label);bubble.appendChild(cd);
  c.appendChild(bubble);c.scrollTop=c.scrollHeight;return bubble;
}

async function clearChat(){
  try{var sid=getSessionId();await fetch('/api/chat?session_id='+encodeURIComponent(sid),{method:'DELETE'});}catch(e){}
  resetChatWelcome();document.getElementById('chat-tool-trace').innerHTML='';
  var bar=document.getElementById('chat-context-bar');if(bar)bar.style.display='none';
}
