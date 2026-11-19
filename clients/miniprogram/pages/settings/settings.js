Page({
  data: { baseURL:'', devKey:'', busy:false, message:'', success:false },
  onLoad() { this.setData(getApp().connection.read()); },
  url(e) { this.setData({baseURL:e.detail.value, message:'', success:false}); },
  key(e) { this.setData({devKey:e.detail.value, message:'', success:false}); },
  async probe() {
    if (this.data.busy) return;
    this.setData({busy:true, message:'', success:false});
    try {
      await getApp().connection.probe(this.data);
      this.setData({message:'已连接到太湖麻将服务', success:true});
    } catch (error) { this.setData({message:error.message}); }
    finally { this.setData({busy:false}); }
  },
  async save() {
    if (this.data.busy) return;
    this.setData({busy:true, message:'', success:false});
    try {
      await getApp().connection.probe(this.data);
      getApp().saveConnection(this.data);
      wx.navigateBack();
    } catch (error) { this.setData({message:error.message}); }
    finally { this.setData({busy:false}); }
  },
  back() { if (!this.data.busy) wx.navigateBack(); }
});
