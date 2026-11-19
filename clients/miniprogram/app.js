const Controller = require('./shared/controller');
const Connection = require('./shared/connection');
const config = require('./shared/config');
const Audio = require('./shared/audio');
App({
  onLaunch() {
    this.current = {};
    this.listeners = [];
    this.visibleTable = false;
    this.connection = Connection.create(wx, config.baseURL);
    this.audioDiagnostics={started:0,ended:0,lastClip:null,lastError:null};
    this.sound = Audio.create({
      load:()=>wx.getStorageSync('mobile-sound')!==false,
      save:value=>wx.setStorageSync('mobile-sound',value),
      onChange:()=>this.publish(this.current),
      createPlayer:(src,ended,failed)=>{
        const player=wx.createInnerAudioContext();
        player.src=src;player.volume=.7;player.obeyMuteSwitch=true;
        player.onPlay(()=>{this.audioDiagnostics.started++;this.audioDiagnostics.lastClip=src;});
        player.onEnded(()=>{this.audioDiagnostics.ended++;ended();});
        player.onError(error=>{this.audioDiagnostics.lastError=error.errCode;failed();});
        return player;
      }
    });
    this.game = Controller.create({
      audio:this.sound,
      load: () => wx.getStorageSync('mobile-session'),
      loadRoom: () => wx.getStorageSync('shared-room-session'),
      saveRoom: value => wx.setStorageSync('shared-room-session',value),
      save: value => wx.setStorageSync('mobile-session', value),
      confirm: (title, content) => new Promise(resolve => wx.showModal({title, content, success:r=>resolve(r.confirm), fail:()=>resolve(false)})),
      request: (path, body, token) => this.connection.request(path, body, token)
    }, value => this.publish(value));
    this.networkListener = result => {
      if (!result.isConnected) this.game.disconnected();
      // On network recovery, require an explicit refresh. Never replay an action.
    };
    wx.onNetworkStatusChange(this.networkListener);
  },
  onHide() { if (this.game) this.game.stop(); },
  onShow() { if (this.game && this.visibleTable) this.game.resume(); },
  publish(value){
    this.current={...value,audioOn:this.sound.enabled,audioError:this.sound.error};
    this.listeners.forEach(fn=>fn(this.current));
  },
  toggleSound(){this.sound.toggle();},
  subscribe(fn) {
    this.listeners.push(fn); fn(this.current);
    return () => { this.listeners=this.listeners.filter(f=>f!==fn); };
  },
  saveConnection(value) {
    if (this.game.busy) throw new Error('当前请求尚未结束，请稍后再切换连接');
    if (this.connection.save(value)) this.game.reset();
  }
});
