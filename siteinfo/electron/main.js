/* SiteInfo Electronホスト（メインプロセス）
 *
 * ブラウザ単体では、CORS制限のため不動産情報ライブラリ（reinfolib）を
 * 直接取得できない。ここで取得を代行し、preload.js経由で
 * window.gisAPI.fetch として画面に渡す。
 *
 *   REINFOLIB_API_KEY=xxxx npm start
 */
'use strict';

const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const https = require('https');

/* 代行するのはreinfolibのみ。任意のURLの中継はしない。 */
const ALLOWED_HOST = 'www.reinfolib.mlit.go.jp';

function fetchGis(url, apiKey) {
  return new Promise((resolve, reject) => {
    let target;
    try { target = new URL(url); }
    catch (e) { reject(new Error('URLが不正です')); return; }
    if (target.protocol !== 'https:' || target.hostname !== ALLOWED_HOST) {
      reject(new Error(`許可されていない接続先です: ${target.hostname}`));
      return;
    }
    const req = https.request(target, {
      method: 'GET',
      headers: { 'Ocp-Apim-Subscription-Key': apiKey || '' },
    }, res => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}（APIキーとレイヤーIDを確認してください）`));
          return;
        }
        resolve(body);
      });
    });
    req.on('error', err => reject(new Error(err.message)));
    req.setTimeout(20000, () => { req.destroy(new Error('タイムアウト')); });
    req.end();
  });
}

ipcMain.handle('gis:fetch', async (_ev, url, apiKey) => {
  return fetchGis(url, apiKey || process.env.REINFOLIB_API_KEY || '');
});

ipcMain.handle('env:get', (_ev, name) => {
  /* 画面に渡してよい環境変数だけを通す */
  const ALLOWED = new Set(['REINFOLIB_API_KEY']);
  return ALLOWED.has(name) ? (process.env[name] || '') : '';
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 940,
    title: 'SiteInfo — 敷地情報取得エンジン',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.loadFile(path.join(__dirname, '..', 'index.html'));
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
