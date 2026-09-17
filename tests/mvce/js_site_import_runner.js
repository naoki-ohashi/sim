/* 敷地JSON/CSV読み込み(web/mvce/site_import.js)の検証用ランナー。
 * 標準入力で {kind: "json"|"csv", text: "..."} を受け取り、結果か
 * エラーメッセージをJSONで返す。tests/mvce/test_js_site_import_parity.py から呼ばれる。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const webDir = path.join(__dirname, '..', '..', 'web', 'mvce');
const sandbox = { console, JSON };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(webDir, 'site_import.js'), 'utf8'), sandbox, { filename: 'site_import.js' });
const SI = sandbox.MvceSiteImport;

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
try {
  out.result = input.kind === 'json' ? SI.parseSiteJson(input.text) : SI.parseSiteCsv(input.text);
  out.ok = true;
} catch (e) {
  out.ok = false;
  out.error = e.message;
}
process.stdout.write(JSON.stringify(out));
