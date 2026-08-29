/* Python版との一致検証用ランナー。
 * 標準入力でケース定義(JSON)を受け取り、JS版の結果をJSONで返す。
 * tests/mvce/test_js_parity.py から呼ばれる。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const webDir = path.join(__dirname, '..', '..', 'web', 'mvce');
const sandbox = { console, Math, JSON, Float64Array, Uint8Array, Infinity, NaN };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const file of ['engine.js', 'optimizer.js', 'isochrone.js']) {
  vm.runInContext(fs.readFileSync(path.join(webDir, file), 'utf8'), sandbox, { filename: file });
}
const E = sandbox.MvceEngine;
const O = sandbox.MvceOptimizer;
const I = sandbox.MvceIsochrone;

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const site = input.site;
const out = {};

if (input.want.includes('far')) {
  const f = E.computeFar(site);
  out.far = { designated: f.designated, roadFar: f.roadFar, effective: f.effective,
              maxRoadWidthM: f.maxRoadWidthM };
}
if (input.want.includes('heightLimits')) {
  out.heightLimits = input.points.map(p => {
    const v = E.heightLimitAt(site, p, false);
    return isFinite(v) ? v : null;   // Infinity は JSON にできないので null
  });
}
if (input.want.includes('roadWidths')) {
  out.roadWidths = input.roadWidthCases.map(c =>
    E.appliedRoadWidth(site, c.point, site.edges[c.edgeIndex]));
}
if (input.want.includes('deemed')) {
  out.deemed = E.deemedBoundaryOffsets(site);
}
if (input.want.includes('solar')) {
  out.solar = input.solarCases.map(c =>
    E.solarPositionDeg(c.lat, E.solarDeclinationDeg(E.dayOfYear(c.month, c.day)), c.hour));
}
if (input.want.includes('mesh')) {
  const area = E.buildMesh(site, input.meshOptions);
  E.assignHeightLimits(site, area, false);
  out.mesh = {
    cellCount: area.cells.length,
    outlineArea: area.outlineArea,
    maxFloors: area.cells.map(c => c.maxFloors),
    cellAreas: area.cells.map(c => c.areaM2),
    cellCenters: area.cells.map(c => c.center),
  };
}
if (input.want.includes('optimize')) {
  const r = O.optimize(site, input.shadowSpec || null, input.meshOptions);
  out.optimize = {
    cellCount: r.area ? r.area.cells.length : 0,
    floors: r.floors,
    usedCells: r.floors.filter(f => f > 0).length,
    maxFloors: r.floors.length ? Math.max(...r.floors) : 0,
    volume: O.totalVolume(r),
    floorArea: O.totalFloorArea(r),
    buildingArea: O.buildingArea(r),
    maxHeight: O.maxHeight(r),
    coverageLimited: r.coverageLimited,
    farLimited: r.farLimited,
    shadowLimited: r.shadowLimited,
    shadowLines: r.shadowLines,
    skyLimited: r.skyLimited,
    removedBySky: r.removedBySky,
    skySummary: r.skySummary,
    summary: O.summaryLinesJa(r),
  };
}
if (input.want.includes('sky')) {
  const nAzimuth = input.skyNAzimuth || 72;
  const azimuthOffsetRatio = input.skyAzimuthOffsetRatio != null ? input.skyAzimuthOffsetRatio : 0.5;
  out.sky = {
    azimuths: E.azimuthsDeg(nAzimuth, azimuthOffsetRatio),
    measurementPoints: E.skyMeasurementPoints(site, input.skyIntervalM || 2.0)
      .map(s => ({ point: s.point, kind: s.kind, edgeIndex: s.edgeIndex })),
    referenceLayerCount: E.referenceBuilding(site, input.skyNLayers || 20).length,
    requiredSetbacks: (input.skySetbackCases || []).map(c =>
      E.requiredSetbackForHeight(site, c.edgeIndex, c.heightM)),
    skyRatios: (input.skyRatioCases || []).map(c => {
      const reference = E.referenceBuilding(site, input.skyNLayers || 20);
      return E.skyRatioPercent(c.point3, reference, nAzimuth, azimuthOffsetRatio);
    }),
  };
}

if (input.want.includes('isochroneMargin')) {
  out.isochroneMargin = input.marginCases.map(c => I.defaultGridMarginM(c.spec, c.maxHeightM));
}
if (input.want.includes('gridShadowHours')) {
  const r = O.optimize(site, input.shadowSpec, input.meshOptions);
  out.gridShadowHours = Array.from(
    I.gridShadowHours(site, r.area, r.floors, input.shadowSpec, input.gridPoints));
}
if (input.want.includes('isochrone')) {
  const r = O.optimize(site, input.shadowSpec, input.meshOptions);
  const iso = I.siteIsochrones(
    site, r.area, r.floors, input.shadowSpec, input.isochroneLevels,
    input.isochroneIntervalM, input.isochroneMarginM);
  out.isochrone = {};
  for (const level of input.isochroneLevels) {
    out.isochrone[level] = (iso[level] || []).map(([points, closed]) => ({ points, closed }));
  }
}

process.stdout.write(JSON.stringify(out));
