/* Only consume redacted public events. Never derive speech from concealed hands. */
(function(root){
  function tileClip(tile){const m=/^([1-9])(万|饼|条)$/.exec(tile||'');return m?{万:'man',饼:'pin',条:'sou'}[m[2]]+m[1]:{南风:'south',西风:'west',北风:'north'}[tile]||null;}
  function numberClips(value){
    if(!Number.isInteger(value)||value<0||value>9999)return [];
    if(value===0)return ['num0'];
    const out=[];let zero=false;
    for(const unit of [1000,100,10,1]){const digit=Math.floor(value/unit);value%=unit;
      if(digit){if(zero)out.push('num0');zero=false;if(!(unit===10&&digit===1&&!out.length))out.push('num'+digit);if(unit>1)out.push('num'+unit);}
      else if(out.length&&value)zero=true;
    }
    return out;
  }
  function settlementClips(result,seat){
    const net=result?.net?.[seat];
    if(!Number.isInteger(net)||Math.abs(net)>9999)return ['settlement'];
    if(net===0)return ['settle_zero'];
    return [net>0?'settle_win':'settle_loss',...numberClips(Math.abs(net)),'points'];
  }
  function eventClips(event,seat){
    if(!event)return [];
    if(event.kind==='draw')return ['tile_draw']; // No drawn tile identity, even for oneself.
    if(event.kind==='discard')return ['tile_discard',tileClip(event.tile)].filter(Boolean);
    if(['chi','peng'].includes(event.kind))return [event.kind];
    if(['an_gang','ming_gang','add_gang'].includes(event.kind))return ['kong'];
    if(['flower_kong','flower_batch'].includes(event.kind))return ['flower'];
    if(event.kind==='three_calls_lock')return ['lock'];
    if(event.kind==='win')return ['win'];
    if(event.kind==='end')return [event.result?.method==='draw'?'draw_round':'win',...settlementClips(event.result,seat)];
    return [];
  }
  function create(platform){
    let enabled=platform.load()!==false,active=true,gameId=null,cursor=0,baseline=true;
    let queue=[],current=null,generation=0,error='';
    const status=()=>platform.onChange?.({enabled,error});
    function stop(){generation++;queue=[];if(current){const player=current;current=null;try{player.stop();player.destroy?.();}catch(_){}}}
    function pump(){
      if(current||!active||!enabled)return;
      while(queue.length&&queue[0].deadline<Date.now())queue.shift();
      const item=queue.shift();if(!item)return;
      const ticket=++generation;
      const finish=failed=>{if(ticket!==generation)return;const old=current;current=null;try{old?.destroy?.();}catch(_){}if(failed){error='声音播放失败，请重新开启或检查系统音量';stop();status();}else pump();};
      try{
        current=platform.createPlayer('/assets/audio/'+item.clip+'.m4a',()=>finish(false),()=>finish(true));
        const promise=current.play();if(promise?.catch)promise.catch(()=>finish(true));
      }catch(_){finish(true);}
    }
    function observe(state){
      if(!state)return;
      const id=(state.version||state.observation_id||'').split(':')[0];
      const events=state.events||[];
      if(baseline||id!==gameId||events.length<cursor){stop();gameId=id;cursor=events.length;baseline=false;return;}
      const added=events.slice(cursor);cursor=events.length;
      if(!active||!enabled||!added.length)return;
      let previousFlowerSeat=null;
      for(const event of added.slice(-12)){
        if(event.kind==='flower_kong'){
          if(previousFlowerSeat===event.seat)continue;
          previousFlowerSeat=event.seat;
        }else if(!(event.kind==='draw'&&event.replacement&&previousFlowerSeat===event.seat))previousFlowerSeat=null;
        if(event.kind==='draw'&&event.replacement&&previousFlowerSeat===event.seat)continue;
        const deadline=Date.now()+(event.kind==='end'?12000:3000);
        for(const clip of eventClips(event,state.seat))queue.push({clip,deadline});
      }
      if(queue.length>32)queue=queue.slice(-32);
      pump();
    }
    return {observe,
      suspend(){active=false;baseline=true;stop();},resume(){active=true;baseline=true;},
      toggle(){enabled=!enabled;error='';platform.save(enabled);if(!enabled)stop();status();return enabled;},
      get enabled(){return enabled;},get error(){return error;},
      dispose(){active=false;stop();}
    };
  }
  const api={create,tileClip,numberClips,settlementClips,eventClips};
  if(typeof module!=='undefined')module.exports=api;else root.MobileAudio=api;
})(typeof globalThis!=='undefined'?globalThis:this);
