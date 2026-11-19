/* Cross-platform interaction controller. Platform supplies request/storage/timer/UI. */
(function(root) {
  const Model=typeof module!=='undefined'?require('./model'):root.MobileModel;
  function create(platform,changed) {
    let state=null, selected=-1, busy=false, timer=null, active=false, paused=false, choices=[], choosing=false, message='', retainingFlowers=false, flowerMode=false, flowerChoices=[];
    const savedRoom=platform.loadRoom?platform.loadRoom():null;
    let roomToken=savedRoom?.token||'', shared=!!savedRoom?.active, room=null;
    let token=shared?roomToken:platform.load()||'';
    const rememberRoom=active=>{if(platform.saveRoom)platform.saveRoom({token:roomToken,active});};
    const requestId=()=>Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);

    const emit=()=>changed({vm:state?Model.project(state,selected):null,busy,paused,choices,choosing,message,retainingFlowers,flowerMode,flowerChoices,flowerCount:flowerChoices.filter(t=>t.selected).length,flowersAllSelected:flowerChoices.length>0&&flowerChoices.every(t=>t.selected),flowerLimit:state?.wall_count||0,room,shared,connected:!!token});
    function stop(){platform.audio?.suspend();active=false;clearTimeout(timer);timer=null;}
    function schedule(){clearTimeout(timer);if(shared){if(active&&!busy&&!paused)timer=setTimeout(refresh,700);return;}if(active&&!busy&&!paused&&state&&!state.bot_error&&state.stage!=='ended')timer=setTimeout(()=>{if(state.can_advance)mutate('/api/step');else if(state.bot_thinking)refresh();},state.can_advance?900:450);}
    function accept(payload){
      const s=shared?payload.game:payload;
      if(shared)room=payload.room;
      const changed=state?.version!==s?.version||state?.awaiting_human!==s?.awaiting_human;
      if(changed){retainingFlowers=false;selected=-1;choices=[];choosing=false;flowerMode=false;flowerChoices=[];}
      state=s;platform.audio?.observe(s);message='';emit();schedule();
    }
    async function request(path,body){
      if(shared){path=path.replace('/api/','/api/rooms/');if(body)body={...body,request_id:requestId()};}
      return platform.request(path,body,token);
    }
    async function refresh(){if(busy)return;busy=true;emit();try{accept(await request('/api/state'));}catch(e){message=e.message;paused=true;if(e.status===404||e.status===401){if(shared){rememberRoom(false);shared=false;room=null;}token='';state=null;platform.save('');stop();}}finally{busy=false;emit();schedule();}}
    async function mutate(path,extra={}){if(busy||!state)return;busy=true;choices=[];choosing=false;flowerMode=false;flowerChoices=[];emit();try{accept(await request(path,{version:state.version,...extra}));}catch(e){message=e.message;paused=true;try{const fresh=await request('/api/state');state=shared?fresh.game:fresh;if(shared)room=fresh.room;selected=-1;}catch(_){} }finally{busy=false;emit();schedule();}}
    async function start(seed,scenario="random"){if(busy)return;shared=false;room=null;token=platform.load()||'';rememberRoom(false);platform.audio?.resume();active=true;paused=false;busy=true;emit();try{const r=await request('/api/session',seed===undefined?{scenario}:{seed,scenario});token=r.session;platform.save(token);accept(r.state);}catch(e){message=e.message;}finally{busy=false;emit();schedule();}}
    function tile(index){if(busy||!state?.awaiting_human)return;if(selected!==index){selected=index;emit();return;}const t=state.self.hand[index];const action=state.legal_actions.find(a=>a.kind==='discard'&&a.tiles[0]===t);if(action)mutate('/api/action',{action_id:action.id});else {message='这张牌不能直接打出，可选择换花或开杠';emit();}}
    async function choose(id){const action=state?.legal_actions.find(a=>a.id===id);if(!action||busy)return;const version=state.version;if(action.kind==='pass'&&state.legal_actions.some(a=>a.kind==='ron')){if(!await platform.confirm('放过这一张？','仍可自摸，轮到自己时恢复接炮资格。'))return;}if(state.version!==version)return;return mutate('/api/action',{action_id:id});}
    function action(label){if(busy||!state?.awaiting_human)return;flowerMode=false;flowerChoices=[];const kinds=Object.keys(Model.labels).filter(k=>Model.labels[k]===label);choices=state.legal_actions.filter(a=>kinds.includes(a.kind)).map(a=>({...a,label:({an_gang:'暗杠',add_gang:'加杠',ming_gang:'明杠'}[a.kind]||label)+' '+a.tiles.join(' ')}));if(choices.length===1)return choose(choices[0].id);choosing=true;emit();}
    async function enterRoom(kind,nickname,code){
      if(busy)return;busy=true;platform.audio?.resume();active=true;paused=false;message='';emit();
      try{
        if(roomToken){try{await platform.request('/api/rooms/profile',undefined,roomToken);}catch(e){if(e.status===401)roomToken='';else throw e;}}
        if(!roomToken){const identity=await platform.request('/api/rooms/identity',{nickname:nickname||'玩家'},'');roomToken=identity.token;rememberRoom(false);}
        const payload=await platform.request('/api/rooms/'+kind,kind==='join'?{code}: {},roomToken);
        shared=true;token=roomToken;rememberRoom(true);accept(payload);
      }catch(e){message=e.message;}
      finally{busy=false;emit();schedule();}
    }
    async function roomCommand(kind,extra={}){
      if(busy||!shared)return;busy=true;message='';emit();
      try{accept(await platform.request('/api/rooms/'+kind,{...extra,request_id:requestId()},roomToken));}
      catch(e){message=e.message;}
      finally{busy=false;emit();schedule();}
    }
    async function leaveRoom(){
      if(busy||!shared)return false;
      if(!await platform.confirm('离开房间？',room?.phase==='playing'?'主动离桌会中止本局；短暂离开可直接切后台，之后继续。':'离开后可凭房间号重新加入。'))return false;
      busy=true;emit();
      try{await platform.request('/api/rooms/leave',{},roomToken);stop();rememberRoom(false);shared=false;room=null;state=null;token=platform.load()||'';message='';return true;}
      catch(e){message=e.message;return false;}
      finally{busy=false;emit();}
    }
    return {start,refresh,tile,action,choose,
      createRoom(nickname){return enterRoom('create',nickname);},
      joinRoom(code,nickname){return enterRoom('join',nickname,code);},
      fillBots(){return roomCommand('bots');},ready(flag){return roomCommand('ready',{ready:flag});},
      startRoom(){return roomCommand('start');},leaveRoom,

      resume(){platform.audio?.resume();active=true;paused=false;refresh();},stop,
      disconnected(){stop();paused=true;message='网络已断开，重连后继续当前牌局';emit();},
      reset(){if(busy)return false;stop();rememberRoom(false);shared=false;room=null;state=null;token='';selected=-1;choices=[];choosing=false;flowerMode=false;flowerChoices=[];retainingFlowers=false;message='';paused=false;platform.save('');emit();return true;},

      cancel(){choices=[];choosing=false;flowerMode=false;flowerChoices=[];emit();},
      keepFlowers(){if(busy||!state?.awaiting_human||!state.legal_actions.some(a=>a.kind==='flower_kong'))return;retainingFlowers=true;selected=-1;choices=[];choosing=false;flowerMode=false;flowerChoices=[];emit();},
      flowers(){
        if(!state?.awaiting_human||busy)return;
        const available=new Set(state.legal_actions.filter(a=>a.kind==='flower_kong').map(a=>a.tiles[0]));
        flowerChoices=state.self.hand.map((t,index)=>({...Model.tile(t,index),selected:false})).filter(t=>available.has(t.value));
        if(!flowerChoices.length)return;
        retainingFlowers=false;flowerMode=true;choices=[];choosing=true;emit();
      },
      toggleFlower(index){if(busy||!flowerMode)return;flowerChoices=flowerChoices.map(t=>t.index===Number(index)?{...t,selected:!t.selected}:t);emit();},
      allFlowers(){if(busy||!flowerMode)return;const next=!flowerChoices.every(t=>t.selected);flowerChoices=flowerChoices.map(t=>({...t,selected:next}));emit();},
      confirmFlowers(){if(busy||!flowerMode)return;const tiles=flowerChoices.filter(t=>t.selected).map(t=>t.value);if(!tiles.length||tiles.length>state.wall_count)return;return mutate('/api/flowers',{tiles});},
      pause(){paused=!paused;if(paused)platform.audio?.suspend();else platform.audio?.resume();emit();schedule();},step(){if(state?.can_advance)mutate('/api/step');},retry(){mutate('/api/retry');},
      async next(){if(busy||shared)return;if(!state)return start();if(state.stage!=='ended'&&!await platform.confirm('重新发牌？','当前对局将保存到本地牌谱后结束。'))return;active=true;paused=false;return mutate('/api/new');},
      async close(){if(shared)return leaveRoom();if(busy||!state)return false;if(!await platform.confirm('结束测试桌？','当前对局会保存牌谱。下次进入将重新开桌。'))return false;busy=true;stop();emit();try{await request('/api/close',{version:state.version});token='';state=null;message='';platform.save('');return true;}catch(e){message=e.message;return false;}finally{busy=false;emit();}},
      get shared(){return shared;},get room(){return room;},get busy(){return busy;},get state(){return state;},get token(){return token;}
    };
  }
  if(typeof module!=='undefined')module.exports={create};else root.MobileController={create};
})(typeof globalThis!=='undefined'?globalThis:this);
