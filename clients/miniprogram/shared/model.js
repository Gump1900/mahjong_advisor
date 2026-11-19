/* Shared by WXML client and browser device simulator. No hidden referee state. */
(function (root) {
  const specials = {东风:'Ton',南风:'Nan',西风:'Shaa',北风:'Pei',中:'Chun',发:'Hatsu',白:'HakuLocal',春:'Flower1',夏:'Flower2',秋:'Flower3',冬:'Flower4',梅:'Flower5',兰:'Flower6',竹:'Flower7',菊:'Flower8'};
  const labels = {pass:'过',chi:'吃',peng:'碰',ming_gang:'杠',an_gang:'杠',add_gang:'杠',win:'胡',ron:'胡'};
  function tile(value, index=0) {
    const m = /^([1-9])(万|饼|条)$/.exec(value || '');
    const file = m ? {万:'Man',饼:'Pin',条:'Sou'}[m[2]] + m[1] : specials[value] || 'Back';
    return {value:value || '牌背', index, src:'/assets/tiles/'+file+'.png'};
  }
  function name(s, self=0) { return ['我','下家','对家','上家'][(s-self+4)%4]; }
  function project(s, selected=-1) {
    const actions = s.awaiting_human ? s.legal_actions : [];
    const self = s.players[s.seat];
    const positions = ['bottom','right','top','left'];
    const players = s.players.map(p => {
      const delta = (p.seat-s.seat+4)%4;
      const calls = s.events.filter(e => e.seat===p.seat && ['chi','peng','ming_gang'].includes(e.kind));
      let ci=0;
      return {...p, position:positions[delta], name:name(p.seat,s.seat)+(p.nickname?'·'+p.nickname:''), dealer:p.seat===s.dealer,
        hand:Array.from({length:p.hand_count}, (_,i) => tile(s.revealed_hands?.[p.seat]?.[i],i)),
        river:p.river.map(tile), flowers:p.flowers.map(tile),
        melds:p.melds.map((m,i) => {
          const call = m.type==='an_gang' ? null : calls[ci++];
          const source = m.source ?? call?.source;
          let ts = m.tiles || Array(m.size).fill(null);
          // Claimed tile is the source's last discard before this resolved call.
          const at = call ? s.events.indexOf(call) : -1;
          const discard = at>=0 ? s.events.slice(0,at).reverse().find(e => e.kind==='discard' && e.seat===source) : null;
          if (m.type==='chi' && discard && ts.includes(discard.tile)) {
            const k=ts.indexOf(discard.tile); ts=[ts[k],...ts.filter((_,j)=>j!==k)];
          }
          const sideways = m.type==='chi' ? 0 : source===((p.seat+1)%4) ? ts.length-1 : source===((p.seat+2)%4) ? 1 : 0;
          return {key:i, caption:m.type==='an_gang'?'暗杠':({chi:'吃',peng:'碰',ming_gang:'明杠',add_gang:'明杠'}[m.type]||m.type)+'·'+name(source,p.seat),
            tiles:ts.map((t,j)=>({...tile(m.type==='an_gang'?null:t,j),sideways:m.type!=='an_gang' && j===sideways}))};
        })};
    });
    const responses = Object.entries(labels).filter(([k])=>actions.some(a=>a.kind===k));
    const buttons = ['过','吃','碰','杠','胡'].filter(label=>responses.some(([,v])=>v===label));
    if (!buttons.some(x=>x!=='过')) buttons.length=0;
    const waits = s.self.waiting_tiles || [];
    return {
      version:s.version, wall:s.wall_count, players, opponents:players.filter(p=>p.seat!==s.seat), me:players[s.seat],
      hand:s.self.hand.map((t,i)=>({...tile(t,i),selected:i===selected,flower:!!specials[t] && !['南风','西风','北风'].includes(t)})),
      actions:buttons.map(label=>({label,kinds:responses.filter(([,v])=>v===label).map(([k])=>k)})),
      flowerActions:actions.filter(a=>a.kind==='flower_kong').map(a=>({...a,label:a.tiles.join('')})),
      waits:waits.map((w,i)=>({...w,...tile(w.tile,i)})),
      waitNote:waits.length?(waits.every(w=>!w.can_ron)?'仅自摸':'可接炮'):'',
      locked:self.locked_with.length?self.locked_with.map(p=>name(p,s.seat)).join('、')+'互锁 · 只能自摸 · 彼此付3倍':'',
      status:s.bot_error?'机器人已暂停':s.bot_thinking?'机器人思考中':s.stage==='ended'?'本局结束':s.awaiting_human?(s.stage==='turn'?'点选手牌，再点打出':'请选择响应'):(name(s.actor,s.seat)+'回合'),
      pending:s.pending?{...tile(s.pending.tile),name:name(s.pending.source,s.seat)}:null,
      result:s.result?{title:s.result.method==='draw'?'本局流局':({dianpao:'接炮',zimo:'自摸',gangkai:'杠开'}[s.result.method]||'胡牌'),
        rows:s.result.net.map((net,i)=>({seat:i,name:name(i,s.seat),net,positive:net>0})),
        winners:s.result.winners.map(p=>name(p,s.seat)).join('、'),tile:s.result.tile?tile(s.result.tile):null}:null
    };
  }
  const scenarios=[{id:'random',label:'随机试打'},{id:'flowers',label:'留花与换花'},{id:'chi',label:'吃牌选择'},{id:'peng',label:'碰牌'},{id:'ming',label:'明杠补牌'},{id:'an',label:'暗杠补牌'},{id:'tenpai',label:'打牌后听牌'},{id:'win',label:'自摸与结算'}];
  const api = {project,tile,labels,name,scenarios};
  if(typeof module!=='undefined') module.exports=api;
  else root.MobileModel=api;
})(typeof globalThis!=='undefined'?globalThis:this);
