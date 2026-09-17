/* SiteInfo Electronホスト（preload）
 *
 * 画面（index.html）が期待するAPIを公開する。
 *   window.envAPI.get(name)      … 環境変数の読み出し
 *   window.gisAPI.fetch(url,key) … reinfolibの取得代行（要APIキー）
 *   window.netAPI.fetch(url)     … 地理院・PLATEAUのJSON取得代行（CORS回避）
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('envAPI', {
  get: name => ipcRenderer.invoke('env:get', name),
});

contextBridge.exposeInMainWorld('gisAPI', {
  fetch: (url, key) => ipcRenderer.invoke('gis:fetch', url, key),
});

contextBridge.exposeInMainWorld('netAPI', {
  fetch: url => ipcRenderer.invoke('net:fetch', url),
});
