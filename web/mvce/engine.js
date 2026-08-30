/* MVE 計算エンジン（JavaScript版）
 *
 * Python版 mve/ の移植。ブラウザ内で完結させるため、外部ライブラリを
 * 一切使わず、素の <script> で読み込める形にしてあります。
 *
 * Python版との対応:
 *   geometry.js 相当        → 幾何ユーティリティ
 *   mvce/zoning.py           → ZONING（用途地域テーブル）
 *   mvce/far.py              → computeFar（法52条2項・9項＋令135条の18）
 *
 * ブラウザ版が持っていないもの（Python 版のみ）:
 *   - 令2条2項の平均地盤面（mvce/ground.py）
 *   - 法52条7項・法53条2項の按分（mvce/zone_split.py）
 *   - 令135条の12第3項第2号の日影の高低差緩和
 *   - 高度地区（法58条。mvce/regulations/height_district.py）
 * これらを含む YAML は app.js が読み込みを拒否します（黙って無視すると
 * 数字が間違うため）。測定面のZは常に spec.measurementHeightM です。
 *   mvce/regulations/*.py    → heightLimitAt ほか（斜線制限と緩和）
 *   mvce/mesh.py             → buildMesh
 *   mvce/index/shadow_index.py     → buildShadowIndex（しきい値高さ）
 *   mvce/solvers/optimizer.py        → optimize（ボクセル貪欲法）
 *
 * 実装が違う点:
 *   多角形の交差に shapely を使えないため、半平面クリップ
 *   （Sutherland–Hodgman）で代用しています。敷地が凸（長方形など通常の
 *   敷地）ならPython版と一致します。凹んだ敷地では、メッシュのマスが
 *   外郭線をはみ出す量の判定がわずかに変わることがあります。
 */
(function (global) {
  'use strict';

  // ===== 幾何 =========================================================
  function polygonSignedArea(pts) {
    let a = 0;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i], q = pts[(i + 1) % pts.length];
      a += p[0] * q[1] - q[0] * p[1];
    }
    return a / 2;
  }
  const polygonArea = pts => Math.abs(polygonSignedArea(pts));
  const ensureCCW = pts => (polygonSignedArea(pts) < 0 ? pts.slice().reverse() : pts.slice());

  function dedupeRing(pts, tol) {
    tol = tol || 1e-9;
    const out = [];
    for (const p of pts) {
      const last = out[out.length - 1];
      if (!last || Math.abs(p[0] - last[0]) > tol || Math.abs(p[1] - last[1]) > tol) out.push([p[0], p[1]]);
    }
    if (out.length > 1) {
      const f = out[0], l = out[out.length - 1];
      if (Math.abs(f[0] - l[0]) <= tol && Math.abs(f[1] - l[1]) <= tol) out.pop();
    }
    return out;
  }

  function edgeDirection(p1, p2) {
    const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
    const len = Math.hypot(dx, dy);
    if (len === 0) throw new Error('長さ0の辺があります');
    return [dx / len, dy / len];
  }
  function interiorNormal(p1, p2) { const [dx, dy] = edgeDirection(p1, p2); return [-dy, dx]; }
  function outwardNormal(p1, p2) { const n = interiorNormal(p1, p2); return [-n[0], -n[1]]; }

  function pointLineDistance(p, p1, p2) {
    const [dx, dy] = edgeDirection(p1, p2);
    return Math.abs((p[0] - p1[0]) * -dy + (p[1] - p1[1]) * dx);
  }

  // 半平面 {x : n・(x - origin) >= 0} で凸クリップ
  function clipByHalfPlane(poly, origin, normal) {
    if (!poly.length) return [];
    const side = p => (p[0] - origin[0]) * normal[0] + (p[1] - origin[1]) * normal[1];
    const out = [];
    for (let i = 0; i < poly.length; i++) {
      const cur = poly[i], prev = poly[(i - 1 + poly.length) % poly.length];
      const dc = side(cur), dp = side(prev);
      if (dc >= 0) {
        if (dp < 0) {
          const t = dp / (dp - dc);
          out.push([prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])]);
        }
        out.push(cur);
      } else if (dp >= 0) {
        const t = dp / (dp - dc);
        out.push([prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])]);
      }
    }
    return out;
  }

  // 各辺を distances[i] だけ内側へ下げた領域（Python版 offset_polygon_by_edge_distances）
  function offsetPolygonByEdgeDistances(points, distances) {
    const pts = ensureCCW(dedupeRing(points));
    let region = pts.slice();
    for (let i = 0; i < pts.length; i++) {
      const d = distances[i];
      if (!d || d <= 0) continue;
      const p1 = pts[i], p2 = pts[(i + 1) % pts.length];
      const n = interiorNormal(p1, p2);
      region = clipByHalfPlane(region, [p1[0] + d * n[0], p1[1] + d * n[1]], n);
      if (region.length < 3) return null;
    }
    return (region.length >= 3 && polygonArea(region) > 1e-9) ? region : null;
  }

  // 角を延長して交点で結ぶ外側オフセット（日影のみなし境界線・測定線用）
  function offsetRingOutward(points, offsets) {
    const pts = ensureCCW(points);
    const n = pts.length;
    const moved = pts.map((p1, i) => {
      const p2 = pts[(i + 1) % n];
      const nm = interiorNormal(p1, p2);
      const d = Array.isArray(offsets) ? offsets[i] : offsets;
      return [[p1[0] - d * nm[0], p1[1] - d * nm[1]], [p2[0] - d * nm[0], p2[1] - d * nm[1]]];
    });
    const corners = [];
    for (let i = 0; i < n; i++) {
      const [a1, a2] = moved[i], [b1, b2] = moved[(i + 1) % n];
      const d1 = [a2[0] - a1[0], a2[1] - a1[1]], d2 = [b2[0] - b1[0], b2[1] - b1[1]];
      const den = d1[0] * d2[1] - d1[1] * d2[0];
      if (Math.abs(den) < 1e-12) { corners.push(a2); continue; }
      const t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / den;
      corners.push([a1[0] + t * d1[0], a1[1] + t * d1[1]]);
    }
    return corners;
  }

  // 閉じた輪を周長で n 等分した点
  function sampleRing(ring, intervalM, minCount) {
    const n = ring.length;
    const segLen = ring.map((p, i) => {
      const q = ring[(i + 1) % n];
      return Math.hypot(q[0] - p[0], q[1] - p[1]);
    });
    const total = segLen.reduce((a, b) => a + b, 0);
    if (total <= 0) return ring.slice();
    const count = Math.max(minCount || 3, Math.ceil(total / intervalM));
    const out = [];
    for (let i = 0; i < count; i++) {
      let target = (total * i) / count, k = 0;
      while (k < segLen.length && target > segLen[k]) { target -= segLen[k]; k++; }
      if (k >= n) k = n - 1;
      const p = ring[k], q = ring[(k + 1) % n];
      const f = segLen[k] > 0 ? target / segLen[k] : 0;
      out.push([p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f]);
    }
    return out;
  }

  // ===== 真北 =========================================================
  function northVector(angleDeg) {
    const a = (angleDeg * Math.PI) / 180;
    return [-Math.sin(a), Math.cos(a)];
  }
  function eastVector(angleDeg) { const n = northVector(angleDeg); return [n[1], -n[0]]; }

  function azimuthOfVector(v, angleDeg) {
    const n = northVector(angleDeg), e = eastVector(angleDeg);
    const az = (Math.atan2(v[0] * e[0] + v[1] * e[1], v[0] * n[0] + v[1] * n[1]) * 180) / Math.PI;
    const norm = ((az % 360) + 360) % 360;
    return norm >= 360 - 1e-9 ? 0 : norm;
  }
  function vectorForAzimuth(azDeg, angleDeg) {
    const a = (azDeg * Math.PI) / 180;
    const n = northVector(angleDeg), e = eastVector(angleDeg);
    return [n[0] * Math.cos(a) + e[0] * Math.sin(a), n[1] * Math.cos(a) + e[1] * Math.sin(a)];
  }
  function facesNorth(outward, angleDeg) {
    const az = azimuthOfVector(outward, angleDeg);
    return Math.min(az, 360 - az) < 90;
  }

  // ===== 用途地域 =====================================================
  const LOW_RISE = new Set(['1low', '2low', 'denen']);
  const RESIDENTIAL = new Set(['1low', '2low', 'denen', '1mid', '2mid', '1res', '2res', 'quasi_res']);
  const OTHER_GROUP = new Set(['neighbor_commercial', 'commercial', 'quasi_industrial',
    'industrial', 'industrial_exclusive', 'unspecified']);
  const ALL_ZONES = new Set([...RESIDENTIAL, ...OTHER_GROUP]);

  function zoneGroup(z) {
    if (RESIDENTIAL.has(z)) return 'residential';
    if (OTHER_GROUP.has(z)) return 'other';
    throw new Error('不明な用途地域: ' + z);
  }

  // 別表第三は5項あり、適用距離の刻みが3通り。住居系／その他の2群に
  // まとめると三の項（準工業・工業・工業専用）と五の項（無指定）に
  // 二の項（近隣商業・商業）の刻みを当ててしまう。Python版と同じ構造。
  const ROAD_SLANT_ROW_BY_ZONE = {
    '1low': 1, '2low': 1, denen: 1, '1mid': 1, '2mid': 1,
    '1res': 1, '2res': 1, quasi_res: 1,
    neighbor_commercial: 2, commercial: 2,
    quasi_industrial: 3, industrial: 3, industrial_exclusive: 3,
    unspecified: 5,
  };
  const ROAD_SLANT_TABLE = {
    1: [[2.0, 20, 1.25], [3.0, 25, 1.25], [4.0, 30, 1.25], [null, 35, 1.25]],
    2: [[4.0, 20, 1.5], [6.0, 25, 1.5], [8.0, 30, 1.5], [10.0, 35, 1.5],
        [11.0, 40, 1.5], [12.0, 45, 1.5], [null, 50, 1.5]],
    3: [[2.0, 20, 1.5], [3.0, 25, 1.5], [4.0, 30, 1.5], [null, 35, 1.5]],
    // 四の項（高層住居誘導地区）は入力できないので到達しないが、表の写し。
    4: [[null, 35, 1.5]],
    // 五の項の勾配は「1.25 又は 1.5 のうち特定行政庁が定めるもの」。
    5: [[2.0, 20, null], [3.0, 25, null], [null, 30, null]],
  };
  const UNSPECIFIED_ROAD_SLANT_SLOPES = [1.25, 1.5];

  function roadSlantRow(zone) {
    const row = ROAD_SLANT_ROW_BY_ZONE[zone];
    if (row === undefined) throw new Error('不明な用途地域: ' + zone);
    return row;
  }
  function roadSlantTier(zone, far, unspecifiedSlope) {
    for (const [upper, dist, slope] of ROAD_SLANT_TABLE[roadSlantRow(zone)]) {
      if (upper !== null && far > upper) continue;
      if (slope !== null) return { dist, slope };
      if (unspecifiedSlope === undefined || unspecifiedSlope === null) {
        throw new Error(
          '用途地域の指定のない区域の道路斜線勾配は、別表第三 五の項により ' +
          '1.25 か 1.5 のうち特定行政庁が定めるものです。どちらか分からないため' +
          '計算できません。zoning.unspecifiedRoadSlantSlope を指定してください');
      }
      if (!UNSPECIFIED_ROAD_SLANT_SLOPES.includes(unspecifiedSlope)) {
        throw new Error('無指定区域の道路斜線勾配は 1.25 か 1.5 です: ' + unspecifiedSlope);
      }
      return { dist, slope: unspecifiedSlope };
    }
    throw new Error('unreachable');
  }

  // 法56条1項2号 イ〜ニ。立上りは用途地域ではなく勾配で決まる
  // （1.25 → 20m、2.5 → 31m）。低層住専・田園住居は列挙が無く適用なし。
  const ADJACENT_SLANT_ITEM_BY_ZONE = {
    '1mid': 'i', '2mid': 'i', '1res': 'i', '2res': 'i', quasi_res: 'i',
    neighbor_commercial: 'ro', quasi_industrial: 'ro',
    commercial: 'ro', industrial: 'ro', industrial_exclusive: 'ro',
    unspecified: 'ni',
  };
  const ADJACENT_SLANT_START_HEIGHT_M = { 1.25: 20.0, 2.5: 31.0 };
  const UNSPECIFIED_ADJACENT_SLANT_SLOPES = [1.25, 2.5];
  const MID_RISE = new Set(['1mid', '2mid']);

  function adjacentSlantItem(zone) {
    if (!ALL_ZONES.has(zone)) throw new Error('不明な用途地域: ' + zone);
    return ADJACENT_SLANT_ITEM_BY_ZONE[zone] || null;
  }
  function adjacentSlantParams(zone, farRatio, unspecifiedSlope, designated25) {
    const item = adjacentSlantItem(zone);
    if (item === null) return null;
    let slope;
    if (item === 'ro') {
      slope = 2.5;
    } else if (item === 'ni') {
      if (unspecifiedSlope === undefined || unspecifiedSlope === null) {
        throw new Error(
          '用途地域の指定のない区域の隣地斜線勾配は、法56条1項2号ニにより ' +
          '1.25 か 2.5 のうち特定行政庁が定めるものです。どちらか分からないため' +
          '計算できません。zoning.unspecifiedAdjacentSlantSlope を指定してください');
      }
      if (!UNSPECIFIED_ADJACENT_SLANT_SLOPES.includes(unspecifiedSlope)) {
        throw new Error('無指定区域の隣地斜線勾配は 1.25 か 2.5 です: ' + unspecifiedSlope);
      }
      slope = unspecifiedSlope;
    } else {
      slope = 1.25;
      if (designated25) {
        if (MID_RISE.has(zone) && farRatio <= 3.0) {
          throw new Error('中高層住専で容積率 30/10 以下は法56条1項2号イのただし書の対象外');
        }
        slope = 2.5;
      }
    }
    return [ADJACENT_SLANT_START_HEIGHT_M[slope], slope];
  }
  const NORTH_SLANT = {
    '1low': [5.0, 1.25], '2low': [5.0, 1.25], denen: [5.0, 1.25],
    '1mid': [10.0, 1.25], '2mid': [10.0, 1.25],
  };
  const northSlantParams = z => NORTH_SLANT[z] || null;

  const FAR_ROAD_COEFFICIENT = { residential: 0.4, other: 0.6 };
  const FAR_ROAD_WIDTH_THRESHOLD_M = 12.0;

  // 緩和対象（斜線ごとに違う。詳細は docs/mvce/legal_basis.md）
  // 4条文がそれぞれ違うものを列挙している。Python版の RelaxationKind の表を参照。
  // 令134条: 公園・広場・水面（線路敷は列挙なし、都市公園の除外も無い）
  const ROAD_RELAX = new Set(['park', 'urban_park', 'water']);
  // 令135条の3: 公園（都市公園を除く）・広場・水面（線路敷は列挙なし）
  const ADJACENT_RELAX = new Set(['park', 'water']);
  // 令135条の4: 水面・線路敷（公園・広場は列挙なし）
  const NORTH_RELAX = new Set(['water', 'railway']);
  // 令135条の12第3項第1号は「道路、水面、線路敷その他これらに類するもの」。
  // 公園・広場は列挙されていないので既定では外す。含める運用の行政庁に
  // 合わせるときは spec.parkIsDeemedBoundary = true。
  const SHADOW_RELAX = new Set(['water', 'railway']);

  // ===== 法52条2項・9項 ================================================
  // maxRoadWidth は**実幅員**。令132条・令134条（斜線）はこちらを使う。
  // 法52条9項の読み替えは「第二項から第七項まで」に限られるので、容積率
  // 側の幅員は farRoadWidthM() を使うこと。
  function maxRoadWidth(site) {
    return site.edges.reduce((m, e) => (e.kind === 'road' ? Math.max(m, e.roadWidthM) : m), 0);
  }

  // 法52条9項の特定道路
  const SPECIFIED_ROAD_MIN_WIDTH_M = 15.0;
  const SPECIFIED_ROAD_FRONT_MIN_M = 6.0;
  const SPECIFIED_ROAD_FRONT_MAX_M = 12.0;
  const SPECIFIED_ROAD_MAX_DISTANCE_M = 70.0;

  // 令135条の18: Wa =（12 − Wr）（70 − L）/ 70
  function article13518Addition(frontWidthM, distanceM) {
    return (SPECIFIED_ROAD_FRONT_MAX_M - frontWidthM)
      * (SPECIFIED_ROAD_MAX_DISTANCE_M - distanceM) / SPECIFIED_ROAD_MAX_DISTANCE_M;
  }

  // 1本の前面道路について、法52条2項に使う幅員（9項の読み替え後）
  function roadFarWidth(edge) {
    const wr = edge.roadWidthM;
    const spec = edge.specifiedRoad;
    const declared = spec && spec.widthM > 0;
    if (!declared) return { actualWidthM: wr, additionM: 0, widthM: wr, reason: '' };
    const no = reason => ({ actualWidthM: wr, additionM: 0, widthM: wr, reason });
    if (spec.widthM < SPECIFIED_ROAD_MIN_WIDTH_M) {
      return no(`特定道路の幅員が${spec.widthM.toFixed(1)}mで15m未満のため、法52条9項の特定道路にあたりません。`);
    }
    if (wr < SPECIFIED_ROAD_FRONT_MIN_M) {
      return no(`前面道路の幅員が${wr.toFixed(1)}mで6m未満のため、法52条9項の対象外です。`);
    }
    if (wr >= SPECIFIED_ROAD_FRONT_MAX_M) {
      return no(`前面道路の幅員が${wr.toFixed(1)}mで12m以上のため、そもそも法52条2項の低減を受けません。`);
    }
    const l = spec.distanceM || 0;
    if (l > SPECIFIED_ROAD_MAX_DISTANCE_M) {
      return no(`特定道路からの延長が${l.toFixed(1)}mで70mを超えるため、法52条9項の対象外です。`);
    }
    const add = article13518Addition(wr, l);
    return { actualWidthM: wr, additionM: add, widthM: wr + add, reason: '' };
  }

  function farRoadWidthM(site) {
    return site.edges.reduce(
      (m, e) => (e.kind === 'road' ? Math.max(m, roadFarWidth(e).widthM) : m), 0);
  }

  function computeFar(site) {
    const designated = site.zoning.farRatio;
    const notes = [];
    const additions = {};
    site.edges.forEach((e, i) => {
      if (e.kind !== 'road' || !e.specifiedRoad || !(e.specifiedRoad.widthM > 0)) return;
      const w = roadFarWidth(e);
      const l = e.specifiedRoad.distanceM || 0;
      if (w.additionM > 0) {
        additions[i] = w;
        notes.push(`法52条9項・令135条の18: 辺${i}（幅員${w.actualWidthM.toFixed(1)}m）は幅員${e.specifiedRoad.widthM.toFixed(1)}mの特定道路から${l.toFixed(1)}mの位置にあるため、Wa=(12−${w.actualWidthM.toFixed(1)})×(70−${l.toFixed(1)})/70=${w.additionM.toFixed(2)}m を加算して${w.widthM.toFixed(2)}mとみなします。`);
      } else if (w.reason) {
        notes.push(`法52条9項: 辺${i}は加算しません。${w.reason}`);
      }
    });
    const hasAdditions = Object.keys(additions).length > 0;
    if (hasAdditions) {
      notes.push('この加算は法52条2項〜7項（容積率）だけに効きます。道路斜線（令132条・令134条）の幅員は実幅員のままです。');
    }
    const width = farRoadWidthM(site);
    if (width <= 0) {
      notes.push('前面道路が設定されていません。法52条2項の判定ができないため指定容積率をそのまま使っています。');
      return { designated, roadFar: null, effective: designated, maxRoadWidthM: 0, notes, specifiedRoadAdditions: additions };
    }
    if (width >= FAR_ROAD_WIDTH_THRESHOLD_M) {
      notes.push(`前面道路の最大幅員が${width.toFixed(1)}mで12m以上のため、法52条2項による低減はありません。`);
      return { designated, roadFar: null, effective: designated, maxRoadWidthM: width, notes, specifiedRoadAdditions: additions };
    }
    const coefficient = FAR_ROAD_COEFFICIENT[zoneGroup(site.zoning.zoneType)];
    const roadFar = width * coefficient;
    const effective = Math.min(designated, roadFar);
    notes.push(`法52条2項: 前面道路の最大幅員${width.toFixed(1)}m × ${coefficient.toFixed(1)} = ${(roadFar * 100).toFixed(0)}%（指定容積率 ${(designated * 100).toFixed(0)}%）`);
    if (roadFar < designated) notes.push(`→ 前面道路幅員により容積率が ${(effective * 100).toFixed(0)}% に制限されます。`);
    const roadCount = site.edges.filter(e => e.kind === 'road').length;
    if (roadCount > 1) notes.push(`前面道路が${roadCount}本あるため、最大幅員${width.toFixed(1)}mで判定しています。`);
    if (!hasAdditions) {
      notes.push('特定道路による緩和（法52条9項）は、特定道路を指定した辺がないため見ていません。幅員15m以上の道路に接続する前面道路（6m以上12m未満）に接している敷地では、その辺に特定道路の幅員と延長を入れてください。');
    }
    notes.push('特定行政庁が定める割増（法52条2項各号の指定区域）や、法52条8項・10項〜14項は未対応です。該当する可能性がある場合は別途確認してください。');
    return { designated, roadFar, effective, maxRoadWidthM: width, notes, specifiedRoadAdditions: additions };
  }

  const siteArea = site => polygonArea(site.points);
  const maxBuildingArea = site => siteArea(site) * site.zoning.coverageRatio;
  const maxFloorArea = site => siteArea(site) * computeFar(site).effective;

  // ===== 斜線制限 =====================================================
  // groundLevelDiffM は「辺の外側（路面／隣地の地盤面）が敷地の地盤面より
  // 何m高いか」の符号つき。緩和が効く向きは斜線の種類で違う。
  //   令135条の2（道路）      … 敷地が道路より1m以上【高い】とき
  //   令135条の3第1項2号（隣地）… 敷地が隣地より1m以上【低い】とき
  //   令135条の4第1項2号（北側）… 敷地が北側隣地より1m以上【低い】とき
  const levelRelax = e => (e.groundLevelDiffM >= 1.0 ? (e.groundLevelDiffM - 1.0) / 2 : 0);
  const roadLevelRelax = e => (-e.groundLevelDiffM >= 1.0 ? (-e.groundLevelDiffM - 1.0) / 2 : 0);
  function adjacentRelaxKinds(site) {
    if (!site.railwayIsAdjacentRelaxation) return ADJACENT_RELAX;
    return new Set([...ADJACENT_RELAX, 'railway']);
  }
  function relaxWidth(edge, kinds, halve) {
    const r = edge.relaxation;
    if (!r || !r.kind || r.kind === 'none' || !(r.widthM > 0) || !kinds.has(r.kind)) return 0;
    return halve ? r.widthM / 2 : r.widthM;
  }

  // 令134条2項: 公園等がある前面道路を基準にする選択規定（Site.applyArticle1342）
  function article1342Span(site, point) {
    if (!site.applyArticle1342) return null;
    const roads = site.edges.filter(e => e.kind === 'road');
    if (roads.length < 2) return null;
    const withPark = roads.filter(r => r.relaxation && ROAD_RELAX.has(r.relaxation.kind)
                                       && r.relaxation.widthM > 0);
    let best = null;
    for (const base of withPark) {
      const span = base.roadWidthM + base.relaxation.widthM;
      const dBase = pointLineDistance(point, base.p1, base.p2);
      const inA = dBase <= 2 * span + 1e-9 && dBase <= 35 + 1e-9;
      const others = roads.filter(r => r !== base);
      const inB = others.every(r =>
        pointLineDistance(point, r.p1, r.p2) + r.roadWidthM / 2 > 10 + 1e-9);
      if (!(inA || inB)) continue;
      if (best === null || span > best[0] + best[1]) best = [base.roadWidthM, base.relaxation.widthM];
    }
    return best;
  }

  // 令132条: 2以上の前面道路がある場合の幅員の読み替え。
  // 3本以上は 2項の運用が分かれるので計算しない（Python版と同じ）。
  function appliedRoadWidth(site, point, edge) {
    const roads = site.edges.filter(e => e.kind === 'road');
    if (roads.length >= 3) {
      throw new Error(
        '前面道路が' + roads.length + '本あります。令132条2項の「これらの前面道路のみを' +
        '前面道路とする」の扱いは行政庁の運用が分かれるため、2本用の式では計算しません');
    }
    const widest = maxRoadWidth(site);
    if (roads.length < 2 || edge.roadWidthM >= widest) return edge.roadWidthM;
    const wideEdge = roads.reduce((a, b) => (b.roadWidthM > a.roadWidthM ? b : a));
    const dWide = pointLineDistance(point, wideEdge.p1, wideEdge.p2);
    const inA = dWide <= 2 * widest + 1e-9 && dWide <= 35 + 1e-9;
    const dCentre = pointLineDistance(point, edge.p1, edge.p2) + edge.roadWidthM / 2;
    const inB = dCentre > 10 + 1e-9;
    return (inA || inB) ? widest : edge.roadWidthM;
  }

  function roadHeightLimit(site, point) {
    const roads = site.edges.filter(e => e.kind === 'road');
    if (!roads.length) return Infinity;
    const tier = roadSlantTier(site.zoning.zoneType, site.zoning.farRatio,
      site.zoning.unspecifiedRoadSlantSlope);
    let limit = Infinity;
    for (const edge of roads) {
      const span = article1342Span(site, point);
      const width = span ? span[0] : appliedRoadWidth(site, point, edge);
      const L = pointLineDistance(point, edge.p1, edge.p2) + width + edge.wallSetbackM
              + (span ? span[1] : relaxWidth(edge, ROAD_RELAX, false));
      const h = L > tier.dist + 1e-9 ? Infinity : tier.slope * L + roadLevelRelax(edge);
      if (h < limit) limit = h;
    }
    return limit;
  }

  // 道路境界線の「反対側」とみなす基準線（3D表示用。Python版 road_slant.opposite_boundary_line 相当）。
  // 令130条の12（後退緩和）・令134条（公園等緩和）を反映。令132条は点ごとに変わるため対象外。
  function oppositeBoundaryLine(site, edgeIndex) {
    const edge = site.edges[edgeIndex];
    if (edge.kind !== 'road') throw new Error('道路境界線ではありません');
    const offset = edge.roadWidthM + edge.wallSetbackM + relaxWidth(edge, ROAD_RELAX, false);
    const [nx, ny] = outwardNormal(edge.p1, edge.p2);
    return [
      [edge.p1[0] + offset * nx, edge.p1[1] + offset * ny],
      [edge.p2[0] + offset * nx, edge.p2[1] + offset * ny],
    ];
  }

  function oppositeBoundaryLines(site) {
    const out = [];
    site.edges.forEach((e, i) => { if (e.kind === 'road') out.push([i, oppositeBoundaryLine(site, i)]); });
    return out;
  }

  function adjacentHeightLimit(site, point) {
    const params = adjacentSlantParams(site.zoning.zoneType, site.zoning.farRatio,
      site.zoning.unspecifiedAdjacentSlantSlope, site.zoning.adjacentSlant25Designated);
    if (!params) return Infinity;
    const [start, slope] = params;
    let limit = Infinity;
    for (const edge of site.edges) {
      if (edge.kind !== 'adjacent') continue;
      const L = pointLineDistance(point, edge.p1, edge.p2) + edge.wallSetbackM
              + relaxWidth(edge, adjacentRelaxKinds(site), true);
      const h = start + slope * L + levelRelax(edge);
      if (h < limit) limit = h;
    }
    return limit;
  }

  function northEdgeIndices(site) {
    const out = [];
    site.edges.forEach((edge, i) => {
      if (edge.kind === 'none') return;
      try {
        if (facesNorth(outwardNormal(edge.p1, edge.p2), site.northAngleDeg)) out.push(i);
      } catch (e) { /* 長さ0の辺は無視 */ }
    });
    return out;
  }

  function northHeightLimit(site, point) {
    const params = northSlantParams(site.zoning.zoneType);
    if (!params) return Infinity;
    const [start, slope] = params;
    const nv = northVector(site.northAngleDeg);
    let limit = Infinity;
    for (const i of northEdgeIndices(site)) {
      const edge = site.edges[i];
      // 北側斜線は真北方向に距離を測る。後退緩和は無い。
      const along = (point[0] - edge.p1[0]) * nv[0] + (point[1] - edge.p1[1]) * nv[1];
      const L = Math.max(0, -along) + relaxWidth(edge, NORTH_RELAX, true)
              + (edge.kind === 'road' ? edge.roadWidthM : 0);
      const h = start + slope * L + levelRelax(edge);
      if (h < limit) limit = h;
    }
    return limit;
  }

  function heightLimitAt(site, point, useSkyRatio) {
    const abs = site.zoning.absoluteHeightLimitM != null ? site.zoning.absoluteHeightLimitM : Infinity;
    if (useSkyRatio) return abs;
    return Math.min(roadHeightLimit(site, point), adjacentHeightLimit(site, point),
                    northHeightLimit(site, point), abs);
  }

  // ===== 高さ制限の逆関数（天空率の適合建築物用。Python版 height_field.py 相当） ==

  // 道路斜線: 高さ height_m を確保するために必要な、道路境界線からの後退距離
  function roadRequiredSetback(site, edgeIndex, heightM) {
    const edge = site.edges[edgeIndex];
    if (edge.kind !== 'road' || heightM <= 0) return 0;
    const tier = roadSlantTier(site.zoning.zoneType, site.zoning.farRatio,
      site.zoning.unspecifiedRoadSlantSlope);
    const base = edge.roadWidthM + edge.wallSetbackM + relaxWidth(edge, ROAD_RELAX, false);
    const level = roadLevelRelax(edge);
    const h0 = tier.slope * base + level;
    if (heightM <= h0) return 0;
    const neededTotal = (heightM - level) / tier.slope;
    const sNeeded = neededTotal - base;
    const sMax = Math.max(0, tier.dist - base);
    return Math.min(sNeeded, sMax);
  }

  // 道路斜線: 適用距離で頭打ちにしない素の必要距離。
  // 天空率の道路高さ制限適合建築物は「適用距離までの帯の中で斜線どおりの形」
  // なので、頭打ちにすると帯の中に何も残らなくなる（令135条の6第1項1号）。
  function roadSlantDistanceForHeight(site, edgeIndex, heightM) {
    const edge = site.edges[edgeIndex];
    if (edge.kind !== 'road' || heightM <= 0) return 0;
    const tier = roadSlantTier(site.zoning.zoneType, site.zoning.farRatio,
      site.zoning.unspecifiedRoadSlantSlope);
    const base = edge.roadWidthM + edge.wallSetbackM + relaxWidth(edge, ROAD_RELAX, false);
    const level = roadLevelRelax(edge);
    if (heightM <= tier.slope * base + level) return 0;
    return (heightM - level) / tier.slope - base;
  }

  // 隣地斜線: 高さ height_m を確保するために必要な、隣地境界線からの後退距離
  function adjacentRequiredSetback(site, edgeIndex, heightM) {
    const edge = site.edges[edgeIndex];
    const params = adjacentSlantParams(site.zoning.zoneType, site.zoning.farRatio,
      site.zoning.unspecifiedAdjacentSlantSlope, site.zoning.adjacentSlant25Designated);
    if (!params || edge.kind !== 'adjacent' || heightM <= 0) return 0;
    const [start, slope] = params;
    const base = edge.wallSetbackM + relaxWidth(edge, adjacentRelaxKinds(site), true);
    const level = levelRelax(edge);
    const h0 = start + slope * base + level;
    if (heightM <= h0) return 0;
    return (heightM - level - start) / slope - base;
  }

  // 北側斜線: 高さ height_m を確保するために必要な、真北方向の距離（後退緩和は無い）
  function northRequiredSetback(site, edgeIndex, heightM) {
    const params = northSlantParams(site.zoning.zoneType);
    if (!params || heightM <= 0) return 0;
    const edge = site.edges[edgeIndex];
    const [start, slope] = params;
    const base = relaxWidth(edge, NORTH_RELAX, true) + (edge.kind === 'road' ? edge.roadWidthM : 0);
    const level = levelRelax(edge);
    const h0 = start + slope * base + level;
    if (heightM <= h0) return 0;
    return (heightM - level - start) / slope - base;
  }

  // 辺 edgeIndex について、高さ height_m に必要な後退距離（斜線種別を判定して振り分け）
  function requiredSetbackForHeight(site, edgeIndex, heightM) {
    const edge = site.edges[edgeIndex];
    if (edge.kind === 'road') return roadRequiredSetback(site, edgeIndex, heightM);
    if (edge.kind === 'adjacent') {
      let needed = adjacentRequiredSetback(site, edgeIndex, heightM);
      if (northEdgeIndices(site).includes(edgeIndex)) {
        needed = Math.max(needed, northRequiredSetback(site, edgeIndex, heightM));
      }
      return needed;
    }
    return 0;
  }

  // 高さ height_m において斜線制限を満たす平面領域（各辺の必要後退距離の共通部分）
  function buildableRingAtHeight(site, heightM) {
    const distances = site.edges.map((_e, i) => requiredSetbackForHeight(site, i, heightM));
    return offsetPolygonByEdgeDistances(site.points, distances);
  }

  // 検討する高さの上限。絶対高さ制限があればそれ、無ければ頂点・重心での
  // 斜線制限の最大値に余裕を見た値（Python版 height_field.max_relevant_height 相当）
  function maxRelevantHeight(site) {
    if (site.zoning.absoluteHeightLimitM != null) return site.zoning.absoluteHeightLimitM;
    const cx = site.points.reduce((s, p) => s + p[0], 0) / site.points.length;
    const cy = site.points.reduce((s, p) => s + p[1], 0) / site.points.length;
    const probes = site.points.concat([[cx, cy]]);
    const values = probes.map(p => heightLimitAt(site, p, false)).filter(v => isFinite(v));
    return values.length ? Math.max(...values) * 1.5 : 120.0;
  }

  /* 適合建築物（令135条の6・7・8）
   *
   * **規制ごとに別の適合建築物。** 令135条の6は道路高さ制限だけ、
   * 令135条の7は隣地高さ制限だけ、令135条の8は北側高さ制限だけに適合する形。
   * 3つを合成した1つの形ではない。
   *
   * 各層は「層の**上端**」の断面で作る。斜線は上へ行くほど狭くなるので、
   * 上端の断面で作った階段状の立体は真の包絡形に含まれ、Pr が大きめに
   * 出る（＝厳しい側）。下端で作ると立体が大きくなって Pr が小さく出て、
   * 本来通らない計画が通ってしまう。
   */
  const SKY_REFERENCE_KINDS = ['road', 'adjacent', 'north'];
  const SKY_SEARCH_CEILING_M = 400.0;

  function skyRequiredSetback(site, edgeIndex, heightM, kind) {
    const edge = site.edges[edgeIndex];
    if (kind === 'road') {
      return edge.kind === 'road' ? roadSlantDistanceForHeight(site, edgeIndex, heightM) : 0;
    }
    if (kind === 'adjacent') {
      return edge.kind === 'adjacent' ? adjacentRequiredSetback(site, edgeIndex, heightM) : 0;
    }
    if (kind === 'north') {
      return northEdgeIndices(site).includes(edgeIndex)
        ? northRequiredSetback(site, edgeIndex, heightM) : 0;
    }
    throw new Error('kind は road / adjacent / north のいずれか: ' + kind);
  }

  // 道路高さ制限が適用される範囲の深さ（別表第三（は）欄の適用距離まで）。
  // 前面道路が2以上なら令135条の6第3項の区域ごとの比較が必要で未対応 → throw。
  function skyRoadBand(site) {
    const roads = site.edges
      .map((e, i) => (e.kind === 'road' ? i : -1)).filter(i => i >= 0);
    if (roads.length >= 2) {
      throw new Error(
        `前面道路が${roads.length}本あります。令135条の6第3項・令135条の9第3項は、`
        + '前面道路が2以上ある場合に令132条・令134条2項の区域ごとに比較することを'
        + '求めています。MVCE は区域分割に対応していないため、天空率による'
        + '道路高さ制限の適用除外（法56条7項1号）は判定できません。'
        + '斜線制限のまま（天空率を使わない設定）で計算してください。');
    }
    if (!roads.length) return null;
    const i = roads[0];
    const edge = site.edges[i];
    const tier = roadSlantTier(site.zoning.zoneType, site.zoning.farRatio,
      site.zoning.unspecifiedRoadSlantSlope);
    const base = edge.roadWidthM + edge.wallSetbackM + relaxWidth(edge, ROAD_RELAX, false);
    const depth = tier.dist - base;
    return depth > 0 ? { edgeIndex: i, depth } : null;
  }

  // その規制が適用される範囲に、点が入っているか
  function skyPointInApplicableRange(site, point, kind) {
    if (kind === 'road') {
      const band = skyRoadBand(site);
      if (!band) return false;
      const edge = site.edges[band.edgeIndex];
      const n = interiorNormal(edge.p1, edge.p2);
      const s = (point[0] - edge.p1[0]) * n[0] + (point[1] - edge.p1[1]) * n[1];
      return s <= band.depth + 1e-9;
    }
    if (kind === 'adjacent') {
      return !!adjacentSlantParams(site.zoning.zoneType, site.zoning.farRatio,
        site.zoning.unspecifiedAdjacentSlantSlope, site.zoning.adjacentSlant25Designated);
    }
    return !!northSlantParams(site.zoning.zoneType);
  }

  function skyReferenceRing(site, heightM, kind) {
    const distances = site.edges.map((_e, i) => skyRequiredSetback(site, i, heightM, kind));
    let ring = offsetPolygonByEdgeDistances(site.points, distances);
    if (!ring) return null;
    if (kind === 'road') {
      const band = skyRoadBand(site);
      if (!band) return null;
      const edge = site.edges[band.edgeIndex];
      const n = interiorNormal(edge.p1, edge.p2);
      // s <= depth の側を残す（内向き法線の逆）
      const origin = [edge.p1[0] + band.depth * n[0], edge.p1[1] + band.depth * n[1]];
      ring = clipByHalfPlane(ring, origin, [-n[0], -n[1]]);
    } else if (!skyPointInApplicableRange(site, site.points[0], kind)) {
      return null;
    }
    return (ring && ring.length >= 3 && polygonArea(ring) > 1e-9) ? ring : null;
  }

  function skyReferenceTop(site, kind) {
    if (!skyReferenceRing(site, 0, kind)) return 0;
    let lo = 0, hi = 1;
    while (hi < SKY_SEARCH_CEILING_M && skyReferenceRing(site, hi, kind)) { lo = hi; hi *= 2; }
    if (hi >= SKY_SEARCH_CEILING_M) return SKY_SEARCH_CEILING_M;
    for (let k = 0; k < 40; k++) {
      const mid = (lo + hi) / 2;
      if (skyReferenceRing(site, mid, kind)) lo = mid; else hi = mid;
    }
    return lo;
  }

  function referenceBuilding(site, kind, nLayers) {
    nLayers = nLayers || 20;
    const top = skyReferenceTop(site, kind);
    if (top <= 0) return [];
    const blocks = [];
    let previous = 0;
    for (let k = 0; k < nLayers; k++) {
      const zTop = (top * (k + 1)) / nLayers;
      const ring = skyReferenceRing(site, zTop, kind);
      if (ring && ring.length >= 3 && polygonArea(ring) > 1e-6) {
        blocks.push({ ring, zBottom: previous, zTop });
      }
      previous = zTop;
    }
    return blocks;
  }

  function referenceBuildings(site, nLayers) {
    const out = {};
    for (const kind of SKY_REFERENCE_KINDS) out[kind] = referenceBuilding(site, kind, nLayers);
    return out;
  }

  // ===== 天空率（法56条7項、令135条の5〜11。Python版 sky_ratio.py 相当） =========
  //
  // 天空図の投影方法と測定点の配置は内部で一貫した近似（正射影・境界線上の
  // 等間隔配置）です。告示が定める厳密な測定点設置規則には準拠していません。

  const SKY_MEASUREMENT_EPSILON_M = 1.0e-3;

  // 方位 azimuthDeg の半直線が凸多角形 ring（CCW）に入るまでの距離。
  // 半平面（各辺の内側法線）の交差区間を求める、AABBスラブ法の多角形版。
  function rayPolygonEntryDistance(origin, azimuthDeg, ring) {
    const rad = (azimuthDeg * Math.PI) / 180;
    const dx = Math.sin(rad), dy = Math.cos(rad);
    let tEnter = -Infinity, tExit = Infinity;
    const n = ring.length;
    for (let i = 0; i < n; i++) {
      const p1 = ring[i], p2 = ring[(i + 1) % n];
      const nrm = interiorNormal(p1, p2);
      const a = (origin[0] - p1[0]) * nrm[0] + (origin[1] - p1[1]) * nrm[1];
      const b = dx * nrm[0] + dy * nrm[1];
      if (Math.abs(b) < 1e-12) {
        if (a < 0) return null;
        continue;
      }
      const t = -a / b;
      if (b > 0) { if (t > tEnter) tEnter = t; } else if (t < tExit) tExit = t;
    }
    if (tEnter > tExit) return null;
    const entry = Math.max(tEnter, 0);
    return entry > 1e-9 ? entry : null;
  }

  // 点 point3=[x,y,z0] から見た、方位 azimuthDeg・ブロック群 blocks（{ring,zBottom,zTop}）の仰角
  function silhouetteElevationRad(point3, azimuthDeg, blocks) {
    const [x, y, z0] = point3;
    let highest = 0;
    for (const block of blocks) {
      if (block.zTop <= z0) continue;
      const r = rayPolygonEntryDistance([x, y], azimuthDeg, block.ring);
      if (r === null) continue;
      const elevation = Math.atan2(block.zTop - z0, r);
      if (elevation > highest) highest = elevation;
    }
    return highest;
  }

  // サンプリングする方位の一覧。offsetRatio=0.5 で軸に平行な光線の縮退を避ける
  function azimuthsDeg(nAzimuth, offsetRatio) {
    offsetRatio = offsetRatio || 0;
    const step = 360 / nAzimuth;
    const out = [];
    for (let i = 0; i < nAzimuth; i++) out.push((i + offsetRatio) * step);
    return out;
  }

  // 天空率(%)。正射影（ρ = cos仰角）でサンプリングする
  function skyRatioPercent(point3, blocks, nAzimuth, azimuthOffsetRatio) {
    nAzimuth = nAzimuth || 180;
    azimuthOffsetRatio = azimuthOffsetRatio || 0;
    const dphi = (2 * Math.PI) / nAzimuth;
    let total = 0;
    for (const az of azimuthsDeg(nAzimuth, azimuthOffsetRatio)) {
      const elevation = silhouetteElevationRad(point3, az, blocks);
      const rho = Math.cos(elevation);
      total += 0.5 * rho * rho * dphi;
    }
    return (total / Math.PI) * 100;
  }

  /* 天空率の算定位置（令135条の9・10・11）。Python版 sky_positions.py 相当。
   *
   * 規制ごとに基準線も間隔も高さも違う。
   *   道路（令135条の9） … 前面道路の反対側の境界線上 / 路面の中心 / 幅員の1/2
   *   隣地（令135条の10）… 境界線から16m(1.25) or 12.4m(2.5) 外側 / 地盤面 / 8m or 6.2m
   *   北側（令135条の11）… 真北方向に4m(低層) or 8m(中高層) 外側 / 地盤面 / 1m or 2m
   * 基準線までの距離は法56条7項各号。
   *
   * 以前はすべて境界線上・2m間隔だったが、条文と違っていた。
   */
  const ADJACENT_BASELINE_M = { 1.25: 16.0, 2.5: 12.4 };
  const ADJACENT_POINT_INTERVAL_M = { 1.25: 8.0, 2.5: 6.2 };
  const NORTH_BASELINE_M = { '1low': 4.0, '2low': 4.0, denen: 4.0, '1mid': 8.0, '2mid': 8.0 };
  const NORTH_POINT_INTERVAL_M = { '1low': 1.0, '2low': 1.0, denen: 1.0, '1mid': 2.0, '2mid': 2.0 };

  // 条文の間隔と利用者の指定の厳しい方。粗くする方向は受け付けない。
  function capInterval(statutoryM, userM) {
    return (userM == null || userM <= 0) ? statutoryM : Math.min(statutoryM, userM);
  }

  // 両端 a・b を含み、間隔が maxInterval 以下になるよう均等配置
  function evenlySpaced(a, b, maxIntervalM) {
    const span = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (span <= 1e-9) return [a];
    if (span <= maxIntervalM + 1e-9) return [a, b];
    const n = Math.ceil(span / maxIntervalM - 1e-9);
    const out = [];
    for (let k = 0; k <= n; k++) {
      out.push([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n]);
    }
    return out;
  }

  function offsetOutward(edge, distanceM) {
    const [nx, ny] = interiorNormal(edge.p1, edge.p2);
    return [
      [edge.p1[0] - distanceM * nx, edge.p1[1] - distanceM * ny],
      [edge.p2[0] - distanceM * nx, edge.p2[1] - distanceM * ny],
    ];
  }

  function offsetNorth(site, edge, distanceM) {
    const [nx, ny] = northVector(site.northAngleDeg);
    return [
      [edge.p1[0] + distanceM * nx, edge.p1[1] + distanceM * ny],
      [edge.p2[0] + distanceM * nx, edge.p2[1] + distanceM * ny],
    ];
  }

  // {point, z, kind, edgeIndex} の配列
  function skyMeasurementPoints(site, maxIntervalM) {
    const result = [];
    const z = site.zoning;

    // 道路（令135条の9）
    site.edges.forEach((edge, idx) => {
      if (edge.kind !== 'road') return;
      const [a, b] = offsetOutward(edge, edge.roadWidthM);
      // 令135条の9第1項: 路面の中心の高さ。第4項の高低差みなしを含む
      const zc = edge.groundLevelDiffM + roadLevelRelax(edge);
      const interval = capInterval(edge.roadWidthM / 2, maxIntervalM);
      for (const point of evenlySpaced(a, b, interval)) {
        result.push({ point, z: zc, kind: 'road', edgeIndex: idx });
      }
    });

    // 隣地（令135条の10）
    const adjParams = adjacentSlantParams(z.zoneType, z.farRatio,
      z.unspecifiedAdjacentSlantSlope, z.adjacentSlant25Designated);
    if (adjParams) {
      const slope = adjParams[1];
      const baseline = ADJACENT_BASELINE_M[slope];
      const interval = capInterval(ADJACENT_POINT_INTERVAL_M[slope], maxIntervalM);
      site.edges.forEach((edge, idx) => {
        if (edge.kind !== 'adjacent') return;
        const [a, b] = offsetOutward(edge, baseline);
        const zc = levelRelax(edge);   // 令135条の10第4項
        for (const point of evenlySpaced(a, b, interval)) {
          result.push({ point, z: zc, kind: 'adjacent', edgeIndex: idx });
        }
      });
    }

    // 北側（令135条の11）
    const northBase = NORTH_BASELINE_M[z.zoneType];
    if (northBase != null) {
      const interval = capInterval(NORTH_POINT_INTERVAL_M[z.zoneType], maxIntervalM);
      for (const idx of northEdgeIndices(site)) {
        const edge = site.edges[idx];
        // 北側が前面道路のときは反対側の境界線が起点（法56条1項3号）
        const distance = northBase + (edge.kind === 'road' ? edge.roadWidthM : 0);
        const [a, b] = offsetNorth(site, edge, distance);
        const zc = levelRelax(edge);   // 令135条の11第4項
        for (const point of evenlySpaced(a, b, interval)) {
          result.push({ point, z: zc, kind: 'north', edgeIndex: idx });
        }
      }
    }
    return result;
  }

  /* 天空率の「入射距離」インデックス（最適化用。Python版 sky_index.py 相当）
   *
   * (測定点, 方位, マス) ごとに、その方位の半直線がそのマスの外接矩形に
   * 入るまでの距離を先に計算しておく。マスの高さと組み合わせれば仰角が
   * 求まるので、以後は高さ配列との比較だけで天空率が求まる。
   * 適合建築物（Pr）は形が変わらないので、実際の多角形で1回だけ計算する。
   */
  // 測定点の間隔は条文が定めるので既定値を持たない（令135条の9〜11）
  const DEFAULT_SKY_N_AZIMUTH = 72;
  const SKY_AZIMUTH_OFFSET_RATIO = 0.5;
  const SKY_TOLERANCE_PERCENT = 1e-9;

  function buildSkyIndex(site, area, maxIntervalM, nAzimuth, reference, azimuthOffsetRatio) {
    // reference は規制ごとの適合建築物 {road, adjacent, north}（令135条の6・7・8）
    nAzimuth = nAzimuth || DEFAULT_SKY_N_AZIMUTH;
    azimuthOffsetRatio = azimuthOffsetRatio != null ? azimuthOffsetRatio : SKY_AZIMUTH_OFFSET_RATIO;
    if (!reference) reference = referenceBuildings(site);

    const nCells = area.cells.length;
    const boxes = area.cells.map(c => c.bounds);
    const samples = skyMeasurementPoints(site, maxIntervalM);
    const points = samples.map(s => s.point);
    const kinds = samples.map(s => s.kind);
    const edgeIndices = samples.map(s => s.edgeIndex);
    // 想定半球の中心の高さは位置ごとに違う（令135条の9〜11）
    const zM = samples.map(s => s.z);

    const directions = azimuthsDeg(nAzimuth, azimuthOffsetRatio).map(a => {
      const rad = (a * Math.PI) / 180;
      return [Math.sin(rad), Math.cos(rad)];
    });

    // 規制ごとの適用範囲の外にあるマスは、その規制の測定点からは見ない
    // （令135条の6第1項1号の「…が適用される範囲内の部分に限る」）。距離を
    // Infinity にすれば仰角0になり、そのマスは天空を塞がない扱いになる。
    // マスの隅がひとつでも範囲に入っていれば含める（多め＝厳しい側）。
    const outside = {};
    for (const kind of new Set(kinds)) {
      outside[kind] = area.cells.map(c => {
        const [x0, y0, x1, y1] = c.bounds;
        const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
        return !corners.some(p => skyPointInApplicableRange(site, p, kind));
      });
    }

    const distances = [];
    const pr = new Float64Array(points.length);
    points.forEach((point, i) => {
      const table = new Float64Array(nAzimuth * nCells).fill(Infinity);
      const skip = outside[kinds[i]];
      if (nCells) {
        directions.forEach((dir, ai) => {
          const base = ai * nCells;
          for (let ci = 0; ci < nCells; ci++) {
            table[base + ci] = skip[ci]
              ? Infinity
              : rayBoxEntry(point[0], point[1], dir[0], dir[1], boxes[ci]);
          }
        });
      }
      distances.push(table);
      // 測定点の種別ごとに違う適合建築物と比べる（令135条の6・7・8）
      pr[i] = skyRatioPercent([point[0], point[1], zM[i]], reference[kinds[i]] || [],
        nAzimuth, azimuthOffsetRatio);
    });

    return {
      points, kinds, edgeIndices, distances, pr, zM,
      nAzimuth, nCells, azimuthOffsetRatio,
      dPhi: (2 * Math.PI) / nAzimuth,
    };
  }

  // 現在の高さ配列における、その測定点の計画建築物の天空率(%)
  function skyPsAt(index, pointIndex, heights) {
    const table = index.distances[pointIndex];
    const n = index.nCells;
    if (n === 0) return 100.0;
    let total = 0;
    for (let ai = 0; ai < index.nAzimuth; ai++) {
      const base = ai * n;
      let maxElevation = 0;
      for (let ci = 0; ci < n; ci++) {
        const above = Math.max(heights[ci] - index.zM[pointIndex], 0);
        const elevation = Math.atan2(above, table[base + ci]);
        if (elevation > maxElevation) maxElevation = elevation;
      }
      const rho = Math.cos(maxElevation);
      total += 0.5 * rho * rho * index.dPhi;
    }
    return (total / Math.PI) * 100;
  }

  // 最も不足している測定点。戻り値は {pointIndex, ps, deficit} か null（すべて適合）
  function skyWorst(index, heights) {
    let worst = null;
    for (let i = 0; i < index.points.length; i++) {
      const ps = skyPsAt(index, i, heights);
      const deficit = index.pr[i] - ps;
      if (deficit > SKY_TOLERANCE_PERCENT && (!worst || deficit > worst.deficit)) {
        worst = { pointIndex: i, ps, deficit };
      }
    }
    return worst;
  }

  const skyIsCompliant = (index, heights) => skyWorst(index, heights) === null;

  // その測定点で稜線（各方位の最大仰角）を作っているマス
  function skyRidgeCells(index, pointIndex, heights) {
    const table = index.distances[pointIndex];
    const n = index.nCells;
    if (n === 0) return [];
    const cells = new Set();
    for (let ai = 0; ai < index.nAzimuth; ai++) {
      const base = ai * n;
      let bestCell = -1, bestElevation = -Infinity;
      for (let ci = 0; ci < n; ci++) {
        const above = Math.max(heights[ci] - index.zM[pointIndex], 0);
        const elevation = Math.atan2(above, table[base + ci]);
        if (elevation > bestElevation) { bestElevation = elevation; bestCell = ci; }
      }
      if (bestElevation > 1e-12) cells.add(bestCell);
    }
    return Array.from(cells).sort((a, b) => a - b);
  }

  // 最終形状の天空率の判定結果（サマリー・図面用）
  function skySummary(index, heights) {
    if (!index.points.length) {
      return { nPoints: 0, worstMargin: 0, worstPoint: null, worstKind: '', worstPs: 0, worstPr: 0, ok: true };
    }
    let worst = null;
    for (let i = 0; i < index.points.length; i++) {
      const ps = skyPsAt(index, i, heights);
      const margin = ps - index.pr[i];
      if (!worst || margin < worst.margin) worst = { margin, i, ps, pr: index.pr[i] };
    }
    return {
      nPoints: index.points.length, worstMargin: worst.margin, worstPoint: index.points[worst.i],
      worstKind: index.kinds[worst.i], worstPs: worst.ps, worstPr: worst.pr,
      ok: worst.margin >= -SKY_TOLERANCE_PERCENT,
    };
  }

  // ===== 壁面後退線・建物外郭線・メッシュ =============================
  function buildingOutline(site) {
    const distances = site.edges.map(e => e.wallSetbackM);
    if (distances.every(d => d <= 0)) return ensureCCW(site.points);
    return offsetPolygonByEdgeDistances(site.points, distances);
  }

  // 凸多角形で矩形を切った形（メッシュのマスのうち外郭線に入っている部分）
  function clipToOutline(rect, outline) {
    let poly = rect;
    const ring = ensureCCW(outline);
    for (let i = 0; i < ring.length; i++) {
      const p1 = ring[i], p2 = ring[(i + 1) % ring.length];
      poly = clipByHalfPlane(poly, p1, interiorNormal(p1, p2));
      if (poly.length < 3) return [];
    }
    return poly;
  }

  function centroidOf(poly) {
    const a2 = polygonSignedArea(poly) * 2;
    if (Math.abs(a2) < 1e-12) {
      let sx = 0, sy = 0;
      for (const p of poly) { sx += p[0]; sy += p[1]; }
      return [sx / poly.length, sy / poly.length];
    }
    let cx = 0, cy = 0;
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      const cross = p[0] * q[1] - q[0] * p[1];
      cx += (p[0] + q[0]) * cross;
      cy += (p[1] + q[1]) * cross;
    }
    return [cx / (3 * a2), cy / (3 * a2)];
  }

  function buildMesh(site, opt) {
    const outline = buildingOutline(site);
    if (!outline) return null;
    const sx = opt.cellSizeXM, sy = opt.cellSizeYM;
    if (sx < 0.5 || sy < 0.5) throw new Error('メッシュの幅は0.5m以上にしてください');

    const xs = outline.map(p => p[0]), ys = outline.map(p => p[1]);
    const minx = Math.min(...xs), miny = Math.min(...ys);
    const maxx = Math.max(...xs), maxy = Math.max(...ys);
    const cells = [];
    const nCols = Math.max(1, Math.ceil((maxx - minx) / sx));
    const nRows = Math.max(1, Math.ceil((maxy - miny) / sy));
    const threshold = opt.coverageThreshold != null ? opt.coverageThreshold : 0.5;

    for (let row = 0; row < nRows; row++) {
      for (let col = 0; col < nCols; col++) {
        const x0 = minx + col * sx, y0 = miny + row * sy;
        const box = [[x0, y0], [x0 + sx, y0], [x0 + sx, y0 + sy], [x0, y0 + sy]];
        // 外郭線からはみ出した部分は落とす。建物は建てられる範囲に収まる。
        const rect = clipToOutline(box, outline);
        if (rect.length < 3) continue;
        const inside = polygonArea(rect);
        if (inside < sx * sy * threshold) continue;
        const bx = rect.map(p => p[0]), by = rect.map(p => p[1]);
        cells.push({
          index: cells.length, rect,
          bounds: [Math.min(...bx), Math.min(...by), Math.max(...bx), Math.max(...by)],
          center: centroidOf(rect),
          areaM2: inside,
        });
      }
    }
    return { outline, cells, cellSizeXM: sx, cellSizeYM: sy, outlineArea: polygonArea(outline) };
  }

  function assignHeightLimits(site, area, useSkyRatio) {
    const fh = site.floorHeightM;
    for (const cell of area.cells) {
      const probes = cell.rect.concat([cell.center]);
      let limit = Infinity;
      for (const p of probes) limit = Math.min(limit, heightLimitAt(site, p, useSkyRatio));
      cell.heightLimitM = limit;
      cell.maxFloors = limit <= 0 ? 0
        : (!isFinite(limit) ? 10000 : Math.floor(limit / fh + 1e-9));
    }
  }

  // ===== 太陽位置 =====================================================
  function dayOfYear(month, day) {
    const cum = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    return cum[month - 1] + day;
  }
  const solarDeclinationDeg = doy => 23.45 * Math.sin(((360 / 365) * (284 + doy) * Math.PI) / 180);
  const WINTER_SOLSTICE_DOY = dayOfYear(12, 22);

  function solarPositionDeg(latDeg, decDeg, hour) {
    const phi = (latDeg * Math.PI) / 180, dec = (decDeg * Math.PI) / 180;
    const H = ((15 * (hour - 12)) * Math.PI) / 180;
    let sinAlt = Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H);
    sinAlt = Math.max(-1, Math.min(1, sinAlt));
    const alt = Math.asin(sinAlt);
    const cosAlt = Math.cos(alt);
    if (cosAlt < 1e-9) return [(alt * 180) / Math.PI, 180];
    let cosG = (Math.sin(alt) * Math.sin(phi) - Math.sin(dec)) / (cosAlt * Math.cos(phi));
    cosG = Math.max(-1, Math.min(1, cosG));
    let g = Math.acos(cosG);
    if (H < 0) g = -g;
    return [(alt * 180) / Math.PI, (180 + (g * 180) / Math.PI + 360) % 360];
  }

  // ===== 日影 =========================================================
  // 令135条の12第3項: みなし境界線の外側への移動量
  function deemedBoundaryOffsets(site, spec) {
    const kinds = new Set(SHADOW_RELAX);
    if (spec && spec.parkIsDeemedBoundary) kinds.add('park');
    return site.edges.map(edge => {
      let width = 0;
      if (edge.kind === 'road') width = edge.roadWidthM;
      else if (edge.relaxation && kinds.has(edge.relaxation.kind) && edge.relaxation.widthM > 0) {
        width = edge.relaxation.widthM;
      }
      if (width <= 0) return 0;
      return width <= 10 ? width / 2 : Math.max(0, width - 5);
    });
  }

  function regulationBoundary(site, spec) {
    if (spec.applyDeemedBoundary === false) return ensureCCW(site.points);
    return offsetRingOutward(site.points, deemedBoundaryOffsets(site, spec));
  }

  function shadowMeasurementPoints(site, spec, distanceM) {
    const base = regulationBoundary(site, spec);
    return sampleRing(offsetRingOutward(base, distanceM), spec.sampleIntervalM || 2.0, 3);
  }

  function trueSolarHours(spec) {
    const [start, end] = spec.hokkaido ? [9, 15] : [8, 16];
    const step = spec.timeStepMinutes / 60;
    const hours = [];
    for (let h = start; h < end - 1e-9; h += step) hours.push(h);
    return hours;
  }

  // 半直線が矩形に入るまでの距離（スラブ法）。入らなければ Infinity。
  function rayBoxEntry(ox, oy, dx, dy, box) {
    function slab(o, d, lo, hi) {
      if (Math.abs(d) < 1e-12) return (lo <= o && o <= hi) ? [-Infinity, Infinity] : [Infinity, -Infinity];
      const t1 = (lo - o) / d, t2 = (hi - o) / d;
      return [Math.min(t1, t2), Math.max(t1, t2)];
    }
    const [xl, xh] = slab(ox, dx, box[0], box[2]);
    const [yl, yh] = slab(oy, dy, box[1], box[3]);
    const enter = Math.max(xl, yl), exit = Math.min(xh, yh);
    if (enter > exit || exit <= 0) return Infinity;
    return enter > 0 ? enter : 0;
  }

  /* しきい値高さのインデックス
   *
   * (測定点, 時刻, マス) ごとに「そのマスが何m以上ならその測定点をその
   * 時刻に日影にするか」を先に計算しておく。以後は高さとの比較だけで
   * 日影判定ができ、超過の原因になっているマスも特定できる。
   */
  function buildShadowIndex(site, area, spec) {
    const hours = trueSolarHours(spec);
    const step = spec.timeStepMinutes / 60;
    const dec = solarDeclinationDeg(WINTER_SOLSTICE_DOY);
    const nCells = area.cells.length;
    const boxes = area.cells.map(c => c.bounds);

    const sun = hours.map(h => {
      const [alt, az] = solarPositionDeg(spec.latitudeDeg, dec, h);
      if (alt <= 0) return null;
      const dir = vectorForAzimuth(az, site.northAngleDeg);
      return { dir, tan: Math.tan((alt * Math.PI) / 180) };
    });

    const lines = [5.0, 10.0].map(distance => {
      const points = shadowMeasurementPoints(site, spec, distance);
      const tables = points.map(pt => {
        const table = new Float64Array(hours.length * nCells).fill(Infinity);
        for (let ti = 0; ti < hours.length; ti++) {
          const s = sun[ti];
          if (!s) continue;
          const base = ti * nCells;
          for (let ci = 0; ci < nCells; ci++) {
            const r = rayBoxEntry(pt[0], pt[1], s.dir[0], s.dir[1], boxes[ci]);
            table[base + ci] = spec.measurementHeightM + r * s.tan;
          }
        }
        return table;
      });
      return {
        distanceM: distance, points, tables,
        maxHours: distance === 5.0 ? spec.line5mMaxHours : spec.line10mMaxHours,
      };
    });

    return { spec, hours, stepHours: step, nCells, lines };
  }

  function hoursAt(index, line, pointIndex, heights) {
    const table = line.tables[pointIndex];
    const n = index.nCells;
    let count = 0;
    for (let ti = 0; ti < index.hours.length; ti++) {
      const base = ti * n;
      for (let ci = 0; ci < n; ci++) {
        if (heights[ci] >= table[base + ci]) { count++; break; }
      }
    }
    return count * index.stepHours;
  }

  function worstViolation(index, heights) {
    let worst = null;
    for (const line of index.lines) {
      for (let i = 0; i < line.points.length; i++) {
        const h = hoursAt(index, line, i, heights);
        const excess = h - line.maxHours;
        if (excess > 1e-9 && (!worst || excess > worst.excess)) {
          worst = { line, pointIndex: i, hours: h, excess };
        }
      }
    }
    return worst;
  }

  const isShadowCompliant = (index, heights) => worstViolation(index, heights) === null;

  function shadowSummary(index, heights) {
    return index.lines.map(line => {
      let worst = 0;
      for (let i = 0; i < line.points.length; i++) worst = Math.max(worst, hoursAt(index, line, i, heights));
      return { distanceM: line.distanceM, maxHours: line.maxHours, worstHours: worst,
               ok: worst <= line.maxHours + 1e-9 };
    });
  }

  global.MvceEngine = {
    polygonArea, polygonSignedArea, ensureCCW, dedupeRing, pointLineDistance,
    interiorNormal, outwardNormal, offsetPolygonByEdgeDistances, offsetRingOutward, sampleRing,
    northVector, azimuthOfVector, vectorForAzimuth, facesNorth,
    zoneGroup, roadSlantRow, roadSlantTier, adjacentSlantItem, adjacentSlantParams,
    northSlantParams,
    computeFar, siteArea, maxBuildingArea, maxFloorArea, maxRoadWidth,
    farRoadWidthM, roadFarWidth, article13518Addition,
    appliedRoadWidth, roadHeightLimit, oppositeBoundaryLine, oppositeBoundaryLines,
    adjacentHeightLimit, northHeightLimit,
    northEdgeIndices, heightLimitAt,
    buildingOutline, buildMesh, assignHeightLimits,
    dayOfYear, solarDeclinationDeg, solarPositionDeg,
    deemedBoundaryOffsets, regulationBoundary, shadowMeasurementPoints, trueSolarHours,
    rayBoxEntry, buildShadowIndex, hoursAt, worstViolation, isShadowCompliant, shadowSummary,
    roadRequiredSetback, adjacentRequiredSetback, northRequiredSetback,
    requiredSetbackForHeight, buildableRingAtHeight, maxRelevantHeight,
    referenceBuilding, referenceBuildings, skyReferenceRing, skyReferenceTop,
    roadSlantDistanceForHeight, skyPointInApplicableRange,
    rayPolygonEntryDistance, silhouetteElevationRad, azimuthsDeg, skyRatioPercent,
    skyMeasurementPoints, buildSkyIndex, skyPsAt, skyWorst, skyIsCompliant, skyRidgeCells,
    skySummary, DEFAULT_SKY_N_AZIMUTH, SKY_AZIMUTH_OFFSET_RATIO,
  };
})(typeof window !== 'undefined' ? window : globalThis);
