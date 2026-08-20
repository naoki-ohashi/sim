/* SiteInfo Electronホスト（メインプロセス）
 *
 * ブラウザ単体では次の2つが動かない。ここで取得を代行し、preload.js経由で
 * 画面に渡す。
 *   1. 不動産情報ライブラリ（reinfolib）— CORS制限。APIキーも要る
 *   2. 地理院リバースジオコーダ／PLATEAUデータカタログ — file://のOrigin: null
 *      やCORSヘッダ未設定で、画面から直接fetchすると失敗することがある
 *
 *   REINFOLIB_API_KEY=xxxx npm start
 *
 * 別の場所にあるindex.htmlを開くこともできる（旧版の検証などに使う）。
 *   SITEINFO_HTML="D:\\GD\\[Claude]\\siteinfo\\index.html" npm start
 *   npm start -- "D:\\GD\\[Claude]\\siteinfo\\index.html"
 */
'use strict';

const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const https = require('https');

/* reinfolibの代行はこのホストだけ。任意のURLの中継はしない。 */
const GIS_HOST = 'www.reinfolib.mlit.go.jp';

/* 地図・3D関連のうち、CORSで弾かれうるJSON APIだけを代行する */
const NET_ALLOWED_SUFFIXES = ['.gsi.go.jp', '.mlit.go.jp', '.reearth.io'];

function httpsGet(url, headers, redirectsLeft) {
  return new Promise((resolve, reject) => {
    const req = https.request(url, { method: 'GET', headers: headers || {} }, res => {
      const status = res.statusCode;
      const location = res.headers.location;
      if (status >= 300 && status < 400 && location) {
        res.resume();
        if (redirectsLeft <= 0) { reject(new Error('リダイレクトが多すぎます')); return; }
        resolve(httpsGet(new URL(location, url), headers, redirectsLeft - 1));
        return;
      }
      let body = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        if (status !== 200) { reject(new Error(`HTTP ${status}`)); return; }
        resolve(body);
      });
    });
    req.on('error', err => reject(new Error(err.message)));
    req.setTimeout(20000, () => { req.destroy(new Error('タイムアウト')); });
    req.end();
  });
}

function parseHttpsUrl(url) {
  let target;
  try { target = new URL(url); }
  catch (e) { throw new Error('URLが不正です'); }
  if (target.protocol !== 'https:') throw new Error('httpsのみ許可しています');
  return target;
}

ipcMain.handle('gis:fetch', async (_ev, url, apiKey) => {
  const target = parseHttpsUrl(url);
  if (target.hostname !== GIS_HOST) {
    throw new Error(`許可されていない接続先です: ${target.hostname}`);
  }
  const key = apiKey || process.env.REINFOLIB_API_KEY || '';
  if (!key) throw new Error('reinfolib APIキーがありません（REINFOLIB_API_KEY か入力欄で指定してください）');
  try {
    return await httpsGet(target, { 'Ocp-Apim-Subscription-Key': key }, 3);
  } catch (e) {
    throw new Error(`${e.message}（APIキーとレイヤーIDを確認してください）`);
  }
});

ipcMain.handle('net:fetch', async (_ev, url) => {
  const target = parseHttpsUrl(url);
  const ok = NET_ALLOWED_SUFFIXES.some(sfx => target.hostname.endsWith(sfx));
  if (!ok) throw new Error(`許可されていない接続先です: ${target.hostname}`);
  return httpsGet(target, { 'User-Agent': 'SiteInfo/0.1' }, 3);
});

ipcMain.handle('env:get', (_ev, name) => {
  /* 画面に渡してよい環境変数だけを通す */
  const ALLOWED = new Set(['REINFOLIB_API_KEY']);
  return ALLOWED.has(name) ? (process.env[name] || '') : '';
});

function targetHtml() {
  const fromArgv = process.argv.slice(app.isPackaged ? 1 : 2)
    .find(a => /\.html?$/i.test(a));
  return process.env.SITEINFO_HTML || fromArgv ||
         path.join(__dirname, '..', 'index.html');
}

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
  const html = targetHtml();
  console.log('[SiteInfo] loading', html);
  win.loadFile(html);
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
