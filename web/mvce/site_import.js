/* MVCE 敷地JSON/CSV読み込み（ブラウザ版）
 *
 * HBU-ANALYZER等の外部ツールが出力するポリゴンデータを想定。
 * Python版 mvce/io/site_json.py, site_csv.py と同じ検証ロジックの移植。
 * DOMに依存しない純粋な解析ロジックだけをここに置く（画面への反映はapp.js側）。
 */
(function (global) {
  'use strict';

  const VALID_KINDS = new Set(['road', 'adjacent', 'none']);

  function parseSiteJson(text) {
    let data;
    try { data = JSON.parse(text); }
    catch (e) { throw new Error('JSONの形式が正しくありません: ' + e.message); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('JSONのトップレベルはオブジェクト（{ "points": [...] } の形）である必要があります');
    }

    const scale = 1 / (data.units_per_meter != null ? data.units_per_meter : 1);
    const rawPoints = data.points;
    if (!Array.isArray(rawPoints) || rawPoints.length < 3) {
      const got = Array.isArray(rawPoints) ? rawPoints.length : 'points キー自体が無い';
      throw new Error(`points には3点以上の座標配列が必要です（現在: ${got}）`);
    }
    const points = rawPoints.map((p, i) => {
      if (!Array.isArray(p) || p.length !== 2 || !p.every(v => typeof v === 'number' && isFinite(v))) {
        throw new Error(`points[${i}] は [x, y] の形式である必要があります: ${JSON.stringify(p)}`);
      }
      return [p[0] * scale, p[1] * scale];
    });

    const n = points.length;
    const notes = [];
    const rawEdges = data.edges;
    if (rawEdges == null) {
      notes.push('JSONにedgesが無いため、辺の種別はすべて「対象外」としました。各辺の欄で指定してください。');
      return { points, edges: null, notes };
    }
    if (!Array.isArray(rawEdges) || rawEdges.length !== n) {
      const got = Array.isArray(rawEdges) ? rawEdges.length : '配列ではない';
      throw new Error(`edges の数(${got})が points の数(${n})と一致しません`);
    }
    const edges = rawEdges.map((e, i) => {
      if (!e || typeof e !== 'object' || Array.isArray(e)) {
        throw new Error(`edges[${i}] はオブジェクトである必要があります`);
      }
      const kind = e.kind != null ? e.kind : 'none';
      if (!VALID_KINDS.has(kind)) {
        throw new Error(`edges[${i}].kind は road/adjacent/none のいずれかにしてください: ${kind}`);
      }
      const roadWidthM = e.road_width_m != null ? +e.road_width_m : null;
      if (kind === 'road' && !(roadWidthM > 0)) {
        throw new Error(`edges[${i}] は道路境界線（kind: road）ですが、road_width_m が指定されていないか0以下です`);
      }
      const relaxation = e.relaxation;
      if (relaxation != null && (typeof relaxation !== 'object' || Array.isArray(relaxation))) {
        throw new Error(`edges[${i}].relaxation はオブジェクトである必要があります`);
      }
      return {
        kind, roadWidthM,
        wallSetbackM: e.wall_setback_m != null ? +e.wall_setback_m : null,
        relaxation: relaxation
          ? { kind: relaxation.kind, widthM: relaxation.width_m != null ? +relaxation.width_m : null }
          : null,
        groundLevelDiffM: e.ground_level_diff_m != null ? +e.ground_level_diff_m : null,
      };
    });
    return { points, edges, notes };
  }

  // 簡易CSVパーサ（ダブルクォート・カンマのエスケープに対応）
  function parseCsvRows(text) {
    const s = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const rows = [];
    let row = [], field = '', inQuotes = false;
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (inQuotes) {
        if (c === '"') { if (s[i + 1] === '"') { field += '"'; i++; } else inQuotes = false; }
        else field += c;
      } else if (c === '"') {
        inQuotes = true;
      } else if (c === ',') {
        row.push(field); field = '';
      } else if (c === '\n') {
        row.push(field); rows.push(row); row = []; field = '';
      } else {
        field += c;
      }
    }
    if (field !== '' || row.length) { row.push(field); rows.push(row); }
    return rows.filter(r => !(r.length === 1 && r[0].trim() === ''));
  }

  function parseSiteCsv(text) {
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1); // BOM除去
    const rows = parseCsvRows(text);
    if (!rows.length) throw new Error('CSVを読み込めませんでした');
    const header = rows[0].map(h => h.trim());
    const body = rows.slice(1);
    const col = name => header.indexOf(name);
    if (col('x') < 0 || col('y') < 0) {
      throw new Error(`必須列: x, y／見つかった列: ${header.join(', ') || '（列が読み取れませんでした）'}`);
    }
    if (body.length < 3) throw new Error(`敷地には3点以上の行が必要です（現在: ${body.length}行）`);

    const floatOrNone = v => {
      if (v == null || v.trim() === '') return null;
      const n = parseFloat(v);
      if (!isFinite(n)) throw new Error(`数値ではありません: ${v}`);
      return n;
    };

    const points = body.map((r, i) => {
      const x = parseFloat(r[col('x')]), y = parseFloat(r[col('y')]);
      if (!isFinite(x) || !isFinite(y)) {
        throw new Error(`${i + 2}行目: x/y が数値ではありません（x=${r[col('x')]}, y=${r[col('y')]}）`);
      }
      return [x, y];
    });

    const n = points.length;
    const notes = [];
    const kindCol = col('kind');
    if (kindCol < 0) {
      notes.push('CSVにkind列が無いため、辺の種別はすべて「対象外」としました。各辺の欄で指定してください。');
      return { points, edges: null, notes };
    }

    const get = (r, name) => (col(name) >= 0 ? r[col(name)] : null);
    const edges = body.map((r, i) => {
      const kind = (r[kindCol] || '').trim() || 'none';
      if (!VALID_KINDS.has(kind)) {
        throw new Error(`${i + 2}行目: kind は road/adjacent/none のいずれかにしてください: ${kind}`);
      }
      let roadWidthM, wallSetbackM, groundLevelDiffM, relaxWidthM;
      try {
        roadWidthM = floatOrNone(get(r, 'road_width_m'));
        wallSetbackM = floatOrNone(get(r, 'wall_setback_m'));
        groundLevelDiffM = floatOrNone(get(r, 'ground_level_diff_m'));
        relaxWidthM = floatOrNone(get(r, 'relaxation_width_m'));
      } catch (e) { throw new Error(`${i + 2}行目: ${e.message}`); }

      if (kind === 'road' && !(roadWidthM > 0)) {
        throw new Error(`${i + 2}行目は道路境界線（kind: road）ですが、road_width_m が指定されていないか0以下です`);
      }
      const relaxKind = (get(r, 'relaxation_kind') || '').trim() || null;
      return {
        kind, roadWidthM, wallSetbackM, groundLevelDiffM,
        relaxation: relaxKind ? { kind: relaxKind, widthM: relaxWidthM != null ? relaxWidthM : 0 } : null,
      };
    });
    return { points, edges, notes };
  }

  global.MvceSiteImport = { VALID_KINDS, parseSiteJson, parseSiteCsv, parseCsvRows };
})(typeof window !== 'undefined' ? window : globalThis);
