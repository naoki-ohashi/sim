/* MVE 敷地図のDXF書き出し（ブラウザ版）
 *
 * Python版 mvce/io/dxf_r12.py + mvce/io/drawing.py の移植。
 * JW-CADが読める最小構成のDXF R12（LINE/TEXTのみ・大文字レイヤ名・
 * ハンドル省略）を組み立て、Shift_JIS(CP932)のバイト列として書き出す。
 * ブラウザのTextEncoderはUTF-8専用でCP932を書けないため、変換には
 * cp932_table.js の変換テーブルを使う。
 *
 * engine.js / optimizer.js / cp932_table.js を先に読み込んでください。
 */
(function (global) {
  'use strict';

  const E = global.MvceEngine;
  const O = global.MvceOptimizer;
  if (!E || !O) throw new Error('engine.js / optimizer.js を先に読み込んでください');

  const JWW_UNITS_PER_METER = 1000.0;

  // -- Shift_JIS(CP932) へのバイト変換 -----------------------------------
  function toCp932Bytes(text) {
    const table = global.CP932_ENCODE_TABLE || {};
    const bytes = [];
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (cp < 0x80) { bytes.push(cp); continue; }
      const v = table[cp];
      if (v == null) { bytes.push(0x3f); continue; } // 未対応文字は "?"（Pythonのerrors="replace"相当）
      if (v > 255) bytes.push((v >> 8) & 0xff, v & 0xff);
      else bytes.push(v);
    }
    return new Uint8Array(bytes);
  }

  // -- 最小構成 DXF R12 ライター ------------------------------------------
  function pair(code, value) { return `${String(code).padStart(3, ' ')}\n${value}\n`; }

  function num(value) {
    let s = value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
    return s === '' || s === '-' ? '0.0' : s;
  }

  function layerName(name) {
    let cleaned = '';
    for (const c of String(name).toUpperCase()) cleaned += /[A-Z0-9$\-_]/.test(c) ? c : '_';
    return cleaned.slice(0, 31) || '0';
  }

  class R12Drawing {
    constructor(unitsPerMeter) {
      if (!(unitsPerMeter > 0)) throw new Error('unitsPerMeter は正の数にしてください');
      this.unitsPerMeter = unitsPerMeter;
      this.layers = new Map();
      this.entities = [];
      this.min = [Infinity, Infinity];
      this.max = [-Infinity, -Infinity];
    }
    addLayer(name, color) {
      const n = layerName(name);
      if (!this.layers.has(n)) this.layers.set(n, color != null ? color : 7);
    }
    xy_(p) {
      const x = p[0] * this.unitsPerMeter, y = p[1] * this.unitsPerMeter;
      this.min[0] = Math.min(this.min[0], x); this.min[1] = Math.min(this.min[1], y);
      this.max[0] = Math.max(this.max[0], x); this.max[1] = Math.max(this.max[1], y);
      return [x, y];
    }
    line(p1, p2, layer, color) {
      color = color != null ? color : 7;
      const name = layerName(layer);
      this.addLayer(name, color);
      const [x1, y1] = this.xy_(p1), [x2, y2] = this.xy_(p2);
      this.entities.push(
        pair(0, 'LINE') + pair(8, name) + pair(62, color)
        + pair(10, num(x1)) + pair(20, num(y1)) + pair(30, '0.0')
        + pair(11, num(x2)) + pair(21, num(y2)) + pair(31, '0.0'));
    }
    // 折れ線を1本ずつのLINEとして書く（LWPOLYLINEはJW-CADが読めない）
    polyline(points, layer, color, close) {
      if (close == null) close = true;
      if (points.length < 2) return;
      for (let i = 0; i < points.length - 1; i++) this.line(points[i], points[i + 1], layer, color);
      const first = points[0], last = points[points.length - 1];
      if (close && (first[0] !== last[0] || first[1] !== last[1])) this.line(last, first, layer, color);
    }
    text(value, at, heightM, layer, color) {
      color = color != null ? color : 7;
      const name = layerName(layer);
      this.addLayer(name, color);
      const [x, y] = this.xy_(at);
      const safe = String(value).replace(/\n/g, ' ').replace(/\r/g, ' ');
      this.entities.push(
        pair(0, 'TEXT') + pair(8, name) + pair(62, color)
        + pair(10, num(x)) + pair(20, num(y)) + pair(30, '0.0')
        + pair(40, num(Math.max(heightM, 1e-6) * this.unitsPerMeter))
        + pair(1, safe) + pair(7, 'STANDARD'));
    }
    header_() {
      const lo = this.min[0] !== Infinity ? this.min : [0, 0];
      const hi = this.max[0] !== -Infinity ? this.max : [0, 0];
      return pair(0, 'SECTION') + pair(2, 'HEADER')
        + pair(9, '$ACADVER') + pair(1, 'AC1009')
        + pair(9, '$DWGCODEPAGE') + pair(3, 'ANSI_932')
        + pair(9, '$INSBASE') + pair(10, '0.0') + pair(20, '0.0') + pair(30, '0.0')
        + pair(9, '$EXTMIN') + pair(10, num(lo[0])) + pair(20, num(lo[1])) + pair(30, '0.0')
        + pair(9, '$EXTMAX') + pair(10, num(hi[0])) + pair(20, num(hi[1])) + pair(30, '0.0')
        + pair(0, 'ENDSEC');
    }
    tables_() {
      let out = pair(0, 'SECTION') + pair(2, 'TABLES');
      out += pair(0, 'TABLE') + pair(2, 'LTYPE') + pair(70, 1)
        + pair(0, 'LTYPE') + pair(2, 'CONTINUOUS') + pair(70, 64)
        + pair(3, 'Solid line') + pair(72, 65) + pair(73, 0) + pair(40, '0.0')
        + pair(0, 'ENDTAB');
      const names = new Map(this.layers);
      if (!names.has('0')) names.set('0', 7);
      out += pair(0, 'TABLE') + pair(2, 'LAYER') + pair(70, names.size);
      for (const [name, color] of names) {
        out += pair(0, 'LAYER') + pair(2, name) + pair(70, 0) + pair(62, color) + pair(6, 'CONTINUOUS');
      }
      out += pair(0, 'ENDTAB');
      out += pair(0, 'TABLE') + pair(2, 'STYLE') + pair(70, 1)
        + pair(0, 'STYLE') + pair(2, 'STANDARD') + pair(70, 0)
        + pair(40, '0.0') + pair(41, '1.0') + pair(50, '0.0')
        + pair(71, 0) + pair(42, '2.5') + pair(3, 'txt') + pair(4, '')
        + pair(0, 'ENDTAB');
      return out + pair(0, 'ENDSEC');
    }
    toText() {
      return this.header_() + this.tables_()
        + pair(0, 'SECTION') + pair(2, 'ENTITIES')
        + this.entities.join('') + pair(0, 'ENDSEC')
        + pair(0, 'EOF');
    }
  }

  // -- 作図 ---------------------------------------------------------------
  const LAYERS = {
    'MVCE-SITE': 7, 'MVCE-ROAD': 8, 'MVCE-SETBACK': 3, 'MVCE-OUTLINE': 5,
    'MVCE-MESH': 254, 'MVCE-FLOORS': 2, 'MVCE-SHADOW-5M': 1, 'MVCE-SHADOW-10M': 30,
    'MVCE-NORTH': 1, 'MVCE-SUMMARY': 7,
  };

  function roadPolygon(edge) {
    const n = E.interiorNormal(edge.p1, edge.p2);
    const w = edge.roadWidthM;
    return [edge.p1, edge.p2,
            [edge.p2[0] - w * n[0], edge.p2[1] - w * n[1]],
            [edge.p1[0] - w * n[0], edge.p1[1] - w * n[1]]];
  }

  function addNorthSymbol(pen, site, origin, size) {
    const [nx, ny] = E.northVector(site.northAngleDeg);
    const tip = [origin[0] + nx * size, origin[1] + ny * size];
    pen.line(origin, tip, 'MVCE-NORTH', 1);
    for (const sign of [1, -1]) {
      const angle = (150 * sign * Math.PI) / 180;
      const ax = nx * Math.cos(angle) - ny * Math.sin(angle);
      const ay = nx * Math.sin(angle) + ny * Math.cos(angle);
      pen.line(tip, [tip[0] + ax * size * 0.25, tip[1] + ay * size * 0.25], 'MVCE-NORTH', 1);
    }
    pen.text('N', [tip[0] + nx * size * 0.15, tip[1] + ny * size * 0.15], size * 0.2, 'MVCE-NORTH', 1);
  }

  /* 計算結果をDXF(R12)のテキストに組み立てる。
   *   result           … optimizer.js の optimize() の戻り値
   *   shadowSpec       … app.js の buildShadowSpec() の戻り値（無ければ null）
   *   isochroneLevels  … 等時間日影図の時間のリスト（無ければ空配列）
   *   isochrones       … isochrone.js の siteIsochrones() の戻り値（levels未指定なら不要）
   */
  function buildSiteDxf(result, shadowSpec, isochroneLevels, isochrones, unitsPerMeter) {
    const site = result.site;
    const pen = new R12Drawing(unitsPerMeter || JWW_UNITS_PER_METER);
    for (const [name, color] of Object.entries(LAYERS)) pen.addLayer(name, color);

    const xs = site.points.map(p => p[0]), ys = site.points.map(p => p[1]);
    const width = Math.max(...xs) - Math.min(...xs), height = Math.max(...ys) - Math.min(...ys);
    const span = Math.max(width, height, 1e-6);

    pen.polyline(site.points, 'MVCE-SITE', LAYERS['MVCE-SITE']);

    for (const edge of site.edges) {
      if (edge.kind !== 'road') continue;
      pen.polyline(roadPolygon(edge), 'MVCE-ROAD', LAYERS['MVCE-ROAD']);
      const mid = [(edge.p1[0] + edge.p2[0]) / 2, (edge.p1[1] + edge.p2[1]) / 2];
      const n = E.interiorNormal(edge.p1, edge.p2);
      pen.text(`W=${edge.roadWidthM.toFixed(1)}m`,
        [mid[0] - n[0] * edge.roadWidthM * 0.5, mid[1] - n[1] * edge.roadWidthM * 0.5],
        span * 0.02, 'MVCE-ROAD', LAYERS['MVCE-ROAD']);
    }

    if (result.area) {
      const outline = E.buildingOutline(site);
      if (outline && site.edges.some(e => e.wallSetbackM > 0)) {
        pen.polyline(outline, 'MVCE-SETBACK', LAYERS['MVCE-SETBACK']);
      }
      pen.polyline(result.area.outline, 'MVCE-OUTLINE', LAYERS['MVCE-OUTLINE']);
      for (const cell of result.area.cells) pen.polyline(cell.rect, 'MVCE-MESH', LAYERS['MVCE-MESH']);
      const cellSize = Math.min(result.area.cellSizeXM, result.area.cellSizeYM);
      result.area.cells.forEach((cell, i) => {
        const f = result.floors[i];
        if (f > 0) pen.text(String(f), cell.center, cellSize * 0.3, 'MVCE-FLOORS', LAYERS['MVCE-FLOORS']);
      });
    }

    // 各階の平面輪郭（マスごと。Python版は結合した1本の輪郭線だが、ここでは
    // マス単位のまま出す＝MVCE-MESHと同様、CAD上では見た目は変わらない）
    const byLevel = new Map();
    for (const block of result.blocks) {
      const level = Math.round(block.zBottom / site.floorHeightM);
      if (!byLevel.has(level)) byLevel.set(level, []);
      byLevel.get(level).push(block);
    }
    for (const level of [...byLevel.keys()].sort((a, b) => a - b)) {
      const layer = `MVCE-PLAN-${level + 1}`;
      const color = (level % 7) + 1;
      pen.addLayer(layer, color);
      for (const block of byLevel.get(level)) for (const rect of block.rects) pen.polyline(rect, layer, color);
    }

    if (shadowSpec) {
      pen.polyline(E.regulationBoundary(site, shadowSpec), 'MVCE-SITE', 253);
      for (const [distance, layer] of [[5.0, 'MVCE-SHADOW-5M'], [10.0, 'MVCE-SHADOW-10M']]) {
        pen.polyline(E.shadowMeasurementPoints(site, shadowSpec, distance), layer, LAYERS[layer]);
      }
      if (isochroneLevels && isochroneLevels.length && result.area && isochrones) {
        const isoColors = [1, 2, 3, 4, 5, 6];
        isochroneLevels.forEach((level, idx) => {
          const layer = `MVCE-ISOCHRONE-${level}H`.replace(/\./g, '_');
          const color = isoColors[idx % isoColors.length];
          const label = `${level}時間`;
          for (const [points, closed] of isochrones[level] || []) {
            pen.polyline(points, layer, color, closed);
            if (points.length) pen.text(label, points[0], span * 0.02, layer, color);
          }
        });
      }
    }

    addNorthSymbol(pen, site, [Math.max(...xs) + span * 0.15, Math.max(...ys)], span * 0.18);

    const textHeight = span * 0.022;
    O.summaryLinesJa(result).forEach((line, i) => {
      pen.text(line, [Math.min(...xs), Math.min(...ys) - span * 0.12 - i * textHeight * 1.6],
        textHeight, 'MVCE-SUMMARY', LAYERS['MVCE-SUMMARY']);
    });

    return pen.toText();
  }

  // CRLF・Shift_JISでBlobを組み立ててダウンロードさせる（JW-CADの前提に合わせる）
  function saveDxf(text, filename) {
    const bytes = toCp932Bytes(text.replace(/\n/g, '\r\n'));
    const blob = new Blob([bytes], { type: 'application/octet-stream' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  global.MvceDxf = { R12Drawing, toCp932Bytes, buildSiteDxf, saveDxf, JWW_UNITS_PER_METER };
})(typeof window !== 'undefined' ? window : globalThis);
