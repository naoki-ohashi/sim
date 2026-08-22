/* SiteInfo Electronホスト（preload）
 *
 * 画面（index.html）が期待するAPIを2つだけ公開する。
 *   window.envAPI.get(name)      … 環境変数の読み出し
 *   window.gisAPI.fetch(url,key) … reinfolibの取得代行
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('envAPI', {
  get: name => ipcRenderer.invoke('env:get', name),
});

contextBridge.exposeInMainWorld('gisAPI', {
  fetch: (url, key) => ipcRenderer.invoke('gis:fetch', url, key),
});
