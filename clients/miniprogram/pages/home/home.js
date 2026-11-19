const Model=require('../../shared/model');
Page({
  data:{busy:false,connected:false,message:'',scenarios:Model.scenarios,scenarioIndex:0,nickname:'玩家',code:'',shared:false},
  onShow(){const app=getApp();this.unsubscribe=app.subscribe(value=>this.setData({busy:!!value.busy,connected:!!app.game.token,message:value.message||'',shared:app.game.shared}));},
  onHide(){if(this.unsubscribe)this.unsubscribe();},
  async start(){const app=getApp();if(app.game.shared){wx.navigateTo({url:'/pages/room/room'});return;}if(app.game.token){wx.navigateTo({url:'/pages/table/table'});return;}await app.game.start(undefined,Model.scenarios[this.data.scenarioIndex].id);if(app.game.state)wx.navigateTo({url:'/pages/table/table'});},
  scenario(e){this.setData({scenarioIndex:Number(e.detail.value)});},
  nickname(e){this.setData({nickname:e.detail.value});},code(e){this.setData({code:e.detail.value.replace(/\D/g,'').slice(0,6)});},
  async createRoom(){await getApp().game.createRoom(this.data.nickname);if(getApp().game.room)wx.navigateTo({url:'/pages/room/room'});},
  async joinRoom(){await getApp().game.joinRoom(this.data.code,this.data.nickname);if(getApp().game.room)wx.navigateTo({url:'/pages/room/room'});},
  settings(){wx.navigateTo({url:'/pages/settings/settings'});},
  onUnload(){if(this.unsubscribe)this.unsubscribe();},
  resume(){wx.navigateTo({url:getApp().game.shared?'/pages/room/room':'/pages/table/table'});}
});
