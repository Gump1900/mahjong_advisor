const Layout=require('../../shared/layout');
Page({
  data:{vm:null,busy:false,paused:false,choices:[],message:'',scale:1,left:0,top:0},
  onShow(){const app=getApp();app.visibleTable=true;this.unsubscribe=app.subscribe(value=>this.setData(value));this.fit();wx.nextTick(()=>this.measure());app.game.resume();},
  onHide(){getApp().visibleTable=false;if(this.unsubscribe)this.unsubscribe();getApp().game.stop();},
  onUnload(){getApp().visibleTable=false;if(this.unsubscribe)this.unsubscribe();getApp().game.stop();},
  onReady(){this.measure();},
  onResize(event){this.fit(event.size);wx.nextTick(()=>this.measure());},
  measure(){const query=this.createSelectorQuery?this.createSelectorQuery():wx.createSelectorQuery();query.select('.table-viewport').boundingClientRect(rect=>{if(rect&&rect.width&&rect.height)this.fit({windowWidth:rect.width,windowHeight:rect.height});}).exec();},
  fit(size){const info=wx.getWindowInfo?wx.getWindowInfo():wx.getSystemInfoSync();this.setData(Layout.fit(info,size));},
  sound(){getApp().toggleSound();},
  tile(e){getApp().game.tile(Number(e.currentTarget.dataset.index));},
  action(e){getApp().game.action(e.currentTarget.dataset.label);},
  choose(e){getApp().game.choose(e.currentTarget.dataset.id);},
  flowerToggle(e){getApp().game.toggleFlower(e.currentTarget.dataset.index);},flowerAll(){getApp().game.allFlowers();},flowerConfirm(){getApp().game.confirmFlowers();},
  cancel(){getApp().game.cancel();},flowers(){getApp().game.flowers();},keepFlowers(){getApp().game.keepFlowers();},
  pause(){getApp().game.pause();},step(){getApp().game.step();},retry(){getApp().game.retry();},next(){if(getApp().game.shared)wx.redirectTo({url:'/pages/room/room'});else getApp().game.next();},
  back(){wx.navigateBack();},
  reconnect(){getApp().game.resume();},
  async leave(){if(await getApp().game.close())wx.navigateBack();}
});
