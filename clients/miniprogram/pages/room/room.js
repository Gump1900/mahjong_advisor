Page({
  data:{room:null,busy:false,message:'',myReady:false},
  onShow(){const app=getApp();app.visibleTable=true;this.entering=false;this.unsubscribe=app.subscribe(value=>{const room=value.room;this.setData({room,busy:!!value.busy,message:value.message||'',myReady:!!room?.seats[room.seat]?.ready});if(room?.phase==='playing'&&!this.entering){this.entering=true;wx.redirectTo({url:'/pages/table/table'});}});app.game.resume();},
  onHide(){getApp().visibleTable=false;if(this.unsubscribe)this.unsubscribe();getApp().game.stop();},
  onUnload(){if(this.unsubscribe)this.unsubscribe();},
  ready(){getApp().game.ready(!this.data.myReady);},bots(){getApp().game.fillBots();},start(){getApp().game.startRoom();},
  enter(){wx.redirectTo({url:'/pages/table/table'});},reconnect(){getApp().game.resume();},
  home(){wx.navigateBack();},
  async leave(){if(await getApp().game.leaveRoom())wx.navigateBack();}
});
