/* ブラウザ版DXF書き出し(web/mve/dxf.js)の検証用ランナー。
 * 標準入力でケース定義(JSON)を受け取り、DXF(R12・CP932・CRLF)を
 * argv[2]のパスにバイナリのまま書き出す。tests/mve/test_js_dxf_compat.py から呼ばれる。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const webDir = path.join(__dirname, '..', '..', 'web', 'mve');
const sandbox = { console, Math, JSON, Float64Array, Uint8Array, Infinity, NaN };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const file of ['engine.js', 'optimizer.js', 'isochrone.js', 'cp932_table.js', 'dxf.js']) {
  vm.runInContext(fs.readFileSync(path.join(webDir, file), 'utf8'), sandbox, { filename: file });
}
const O = sandbox.MveOptimizer;
const I = sandbox.MveIsochrone;
const D = sandbox.MveDxf;

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const site = input.site;
const result = O.optimize(site, input.shadowSpec || null, input.meshOptions);

let isochrones = null;
const isochroneLevels = input.isochroneLevels || [];
if (input.shadowSpec && isochroneLevels.length) {
  isochrones = I.siteIsochrones(
    site, result.area, result.floors, input.shadowSpec,
    isochroneLevels, input.isochroneIntervalM || 2.0, input.isochroneMarginM);
}

const text = D.buildSiteDxf(result, input.shadowSpec || null, isochroneLevels, isochrones, input.unitsPerMeter);
const bytes = D.toCp932Bytes(text.replace(/\n/g, '\r\n'));
fs.writeFileSync(process.argv[2], Buffer.from(bytes));
