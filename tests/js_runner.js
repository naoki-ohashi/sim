/* Python版との一致検証用のランナー。
 * 標準入力でケース定義(JSON)を受け取り、JS版の計算結果をJSONで返す。
 * tests/test_js_parity.py から呼ばれる。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const webDir = path.join(__dirname, '..', 'web');
const sandbox = { console, Math, JSON };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const file of ['engine.js', 'envelope.js']) {
  vm.runInContext(fs.readFileSync(path.join(webDir, file), 'utf8'), sandbox, { filename: file });
}
const E = sandbox.JwcadVolumeEngine;
const V = sandbox.JwcadVolumeEnvelope;

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const site = input.site;
const out = {};

if (input.want.includes('skyRatio')) {
  out.skyRatio = input.skyRatioPoints.map(p =>
    E.skyRatioPercent(p, input.blocks, input.nAzimuth));
}
if (input.want.includes('baseline')) {
  const base = E.referenceBuildingBlocks(site, input.nLayers, null);
  out.baseline = base.map(b => ({
    zBottom: b.zBottom, zTop: b.zTop, area: E.polygonArea(b.footprint),
  }));
}
if (input.want.includes('solar')) {
  out.solar = input.solarCases.map(c =>
    E.solarPositionDeg(c.lat, E.solarDeclinationDeg(E.dayOfYear(c.month, c.day)), c.hour));
}
if (input.want.includes('setback')) {
  out.setback = input.setbackCases.map(c =>
    E.requiredSetbackForHeight(site.edges[c.edgeIndex], c.height, site, c.slopeMultiplier || 1.0));
}
if (input.want.includes('shadow')) {
  const blocks = input.blocks;
  out.shadow = E.computeShadowHours(site, blocks, input.shadowParams)
    .map(c => ({ lineName: c.lineName, worstHours: c.worstHours, ok: c.ok }));
}
if (input.want.includes('envelope')) {
  const r = V.computeMaxEnvelope(site, input.envelopeOptions);
  out.envelope = {
    maxHeight: V.maxHeight(r.blocks),
    volume: V.totalVolume(r.blocks),
    floorArea: V.totalFloorArea(r.blocks, site.floorHeightM),
    footprintArea: r.blocks.length ? E.polygonArea(r.blocks[0].footprint) : 0,
    stageCount: r.tower.stages.length,
    extraHeight: r.tower.stages.reduce((s, x) => s + x.heightM, 0),
    coverageCapApplied: r.coverageCapApplied,
    farCapApplied: r.farCapApplied,
    shadowScale: r.shadowHeightScale,
    allSkyRatioOk: r.skyRatioChecks.every(c => c.ok),
    summary: V.summaryLinesJa(r),
  };
}

process.stdout.write(JSON.stringify(out));
