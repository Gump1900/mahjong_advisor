/* Native transport: configurable development endpoint, no automatic mutation retry. */
const DEFAULT_URL = 'http://127.0.0.1:8770';
function normalizeURL(value) {
  const raw = String(value || '').trim().replace(/\/+$/, '');
  const match = /^(https?):\/\/([a-zA-Z0-9.-]+)(?::(\d{1,5}))?$/.exec(raw);
  if (!match || match[3] && (+match[3] < 1 || +match[3] > 65535)) {
    throw new Error('请输入服务地址，例如 http://192.168.1.8:8771；不要包含路径或账号');
  }
  return raw;
}
function create(wx, fallback = DEFAULT_URL) {
  function read() {
    const stored = wx.getStorageSync('mobile-connection') || {};
    return { baseURL: stored.baseURL || fallback, devKey: stored.devKey || '' };
  }
  function save(value) {
    const next = { baseURL: normalizeURL(value.baseURL), devKey: String(value.devKey || '').trim() };
    const old = read();
    wx.setStorageSync('mobile-connection', next);
    return old.baseURL !== next.baseURL || old.devKey !== next.devKey;
  }
  function request(path, body, token = '', override) {
    const connection = override || read();
    return new Promise((resolve, reject) => wx.request({
      url: normalizeURL(connection.baseURL) + path,
      method: body === undefined ? 'GET' : 'POST', data: body, timeout: 15000,
      header: { 'Content-Type': 'application/json', 'X-Session': token, 'X-Dev-Key': connection.devKey || '' },
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) return resolve(response.data);
        const error = response.data && response.data.error;
        reject(Object.assign(new Error(error || '服务请求失败，请重新连接'), { status: response.statusCode }));
      },
      fail(error) {
        const timedOut = /timeout/i.test(error.errMsg || '');
        reject(new Error(timedOut ? '连接超时，已暂停；请检查服务与网络后重连' : '连接失败，请检查服务地址、同一Wi-Fi与开发域名配置'));
      }
    }));
  }
  async function probe(value) {
    const connection = { baseURL: normalizeURL(value.baseURL), devKey: String(value.devKey || '').trim() };
    const health = await request('/api/health', undefined, '', connection);
    if (!health || health.protocol !== 'taihu-mobile-1') throw new Error('此地址不是太湖麻将手机服务');
    return health;
  }
  return { read, save, request, probe };
}
module.exports = { create, normalizeURL, DEFAULT_URL };
