"use strict";
/* Local synthesized female clips + original procedural sound and music.
   Never look at an engine hand, hidden draw identity, or unknown ankan tile. */
(() => {
  const tileClip = tile => {
    const m=/^([1-9])(万|饼|条)$/.exec(tile||"");
    return m ? ({万:"man",饼:"pin",条:"sou"}[m[2]]+m[1]) : {南风:"south",西风:"west",北风:"north"}[tile];
  };
  function clipForEvent(e) {
    if (!e) return null;
    if(e.kind==="discard")return tileClip(e.tile)||null;
    if(["chi","peng"].includes(e.kind))return e.kind;
    if(["an_gang","ming_gang","add_gang"].includes(e.kind))return "kong";
    if(["flower_kong","flower_batch"].includes(e.kind))return "flower";
    if(e.kind==="win")return "win";
    if(e.kind==="three_calls_lock")return "lock";
    if(e.kind==="end"&&e.result?.method==="draw")return "draw_round";
    return null; // In particular: NEVER speak a drawn tile or hidden ankan name.
  }
  let prefs={master:true,voice:true,effects:true,music:true,volume:0.6,musicVolume:0.12};
  try { Object.assign(prefs,JSON.parse(localStorage.getItem("mahjong-audio")||"{}")); } catch {}
  for(const k of ["master","voice","effects","music"])prefs[k]=prefs[k]!==false;
  for(const k of ["volume","musicVolume"])prefs[k]=Math.max(0,Math.min(1,Number(prefs[k])||0));
  let enabled=false,unlocking=false,paused=false,context=null,musicGain=null,musicSource=null,voice=null,button,panel;
  const save=()=>{try{localStorage.setItem("mahjong-audio",JSON.stringify(prefs));}catch{}};
  const available=()=>enabled&&!paused&&!document.hidden;
  function stopVoice(){if(voice){voice.pause();voice.currentTime=0;voice=null;}duck(false);}
  function duck(active){if(musicGain&&context)musicGain.gain.setTargetAtTime(available()&&prefs.music?prefs.musicVolume*(active?0.28:1):0,context.currentTime,0.12);}
  function effect(kind){
    if(!available()||!prefs.effects||!context)return;
    const now=context.currentTime, gain=context.createGain();gain.connect(context.destination);
    gain.gain.setValueAtTime(0.0001,now);gain.gain.exponentialRampToValueAtTime(0.065*prefs.volume+0.0001,now+0.008);gain.gain.exponentialRampToValueAtTime(0.0001,now+0.15);
    const osc=context.createOscillator();osc.type="triangle";
    osc.frequency.setValueAtTime(kind==="draw"?480:kind==="select"?740:kind==="win"?880:260,now);
    osc.frequency.exponentialRampToValueAtTime(kind==="win"?1320:150,now+0.13);
    osc.connect(gain);osc.start(now);osc.stop(now+0.17);
    osc.onended=()=>{osc.disconnect();gain.disconnect();};
  }
  function makeMusic(){
    if(!context||musicSource)return;
    // Original 32-beat pentatonic plucked motif; no commercial tune or sample.
    const rate=context.sampleRate,beat=60/88,length=beat*32;
    const buffer=context.createBuffer(1,Math.ceil(length*rate),rate),data=buffer.getChannelData(0);
    const notes=[60,64,67,69,67,64,62,64,67,72,69,67,64,62,60,62];
    const add=(midi,start,duration,amplitude)=>{
      const f=440*Math.pow(2,(midi-69)/12),begin=Math.round(start*rate),count=Math.round(duration*rate);
      for(let i=0;i<count&&begin+i<data.length;i++){
        const t=i/rate,envelope=Math.min(1,t/0.012)*Math.exp(-t*3.8);
        data[begin+i]+=amplitude*envelope*(Math.sin(2*Math.PI*f*t)+0.23*Math.sin(4*Math.PI*f*t));
      }
    };
    notes.forEach((n,i)=>add(n,i*2*beat,1.3,0.25));
    [48,43,45,43,48,43,45,43].forEach((n,i)=>add(n,i*4*beat,2.1,0.14));
    musicGain=context.createGain();musicGain.gain.value=0;musicGain.connect(context.destination);
    musicSource=context.createBufferSource();musicSource.buffer=buffer;musicSource.loop=true;
    musicSource.connect(musicGain);musicSource.start();duck(false);
  }
  async function unlock(){
    if(enabled||unlocking||!prefs.master)return;
    unlocking=true;
    try {
      context=context||new (window.AudioContext||window.webkitAudioContext)();
      await context.resume();enabled=true;paused=false;makeMusic();duck(false);
      button.textContent="声音：已开启";button.setAttribute("aria-pressed","true");effect("select");
    } catch {button.textContent="声音不可用";enabled=false;}
    finally {unlocking=false;}
  }
  function speak(clip){
    stopVoice();if(!available()||!prefs.voice||!clip)return;
    const player=new Audio(`/audio/${clip}.m4a`);voice=player;player.volume=prefs.volume;
    duck(true);player.onended=player.onerror=()=>{if(voice===player){voice=null;duck(false);}};
    player.play().catch(()=>{if(voice===player){voice=null;duck(false);}});
  }
  function present(e){
    if(!available()||!e)return;
    stopVoice();
    if(["draw","discard","flower_kong","flower_batch","chi","peng","an_gang","ming_gang","add_gang","win"].includes(e.kind))effect(e.kind);
    speak(clipForEvent(e));
  }
  const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  button=el("button",prefs.master?"声音：已开启":"声音：已关闭");button.id="sound-toggle";button.type="button";button.setAttribute("aria-pressed",String(prefs.master));
  button.title="默认开启；浏览器要求首次点击或按键后才能播放，点击此按钮调整声音";
  panel=el("div");panel.id="sound-settings";panel.hidden=true;panel.setAttribute("aria-label","声音设置");
  panel.append(el("strong","女声 · 牌桌声音"),el("small","默认开启，首次操作后播放；音频不调用LLM"));
  for(const [key,label] of [["voice","女声播报"],["effects","摸打音效"],["music","背景音乐"]]){
    const row=el("label",label),input=el("input");input.type="checkbox";input.checked=prefs[key];
    input.onchange=()=>{prefs[key]=input.checked;save();if(!prefs.voice)stopVoice();duck(false);};row.append(input);panel.append(row);
  }
  for(const [key,label] of [["volume","语音 / 音效音量"],["musicVolume","音乐音量"]]){
    const row=el("label",label),input=el("input");input.type="range";input.min=0;input.max=1;input.step=0.01;input.value=prefs[key];
    input.oninput=()=>{prefs[key]=Number(input.value);if(voice)voice.volume=prefs.volume;save();duck(!!voice);};row.append(input);panel.append(row);
  }
  const off=el("button","关闭全部声音");off.onclick=()=>{prefs.master=false;save();enabled=false;stopVoice();duck(false);panel.hidden=true;button.textContent="声音：已关闭";button.setAttribute("aria-pressed","false");};
  const close=el("button","收起设置");close.onclick=()=>{panel.hidden=true;};panel.append(off,close);
  button.onclick=async()=>{if(!prefs.master){prefs.master=true;save();await unlock();}panel.hidden=!panel.hidden;};
  document.querySelector(".toolbar").append(button);document.body.append(panel);
  const activate=()=>{if(prefs.master&&!enabled)unlock();};
  document.addEventListener("pointerdown",activate,{capture:true,passive:true});
  document.addEventListener("keydown",activate,{capture:true});
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){stopVoice();if(context)context.suspend().catch(()=>{});}
    else if(available()&&context)context.resume().then(()=>duck(false)).catch(()=>{});
  });
  globalThis.TableAudio={clipForEvent,present,select:()=>effect("select"),
    pause(value){if(paused===value)return;paused=value;stopVoice();duck(false);},
    reset(){stopVoice();},isEnabled:()=>enabled,isConfiguredOn:()=>prefs.master};
})();
