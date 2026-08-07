/* jwcad-volume 計算エンジン（JavaScript版）
 *
 * Python版(jwcad_volume/)と同じ計算をブラウザ内で行うための移植です。
 * 外部ライブラリを使わず、file:// で開いても動くよう素の <script> として
 * 読み込める形にしてあります。
 *
 * Python版との違いは1点だけです。日影計算で、Python版は shapely の
 * 多角形和集合で影の領域を作ってから測定点を判定していますが、こちらは
 * 和集合を作らずに判定します。点Pが「平面形状F」と「影のずれベクトルd」
 * が作るミンコフスキー和 F⊕[0,d] に入る条件は、
 *
 *     線分 [P-d, P] が F と交わること
 *
 * と数学的に同値なので、線分交差判定だけで厳密に同じ答えが出ます。
 * 多角形ブーリアンのライブラリを持ち込まずに済むのが利点です。
 *
 * 敷地が凸でない場合のセットバック（内側への縮小）は、Python版が使う
 * shapely の buffer(-d) と厳密には一致しないことがあります。敷地が凸
 * （長方形など通常の敷地）なら一致します。詳細は docs/web_app.md 参照。
 */
(function (global) {
  'use strict';

  // ===== 幾何 =========================================================
  const BIG = 1e6;

  function polygonSignedArea(pts) {
    let a = 0;
    for (let i = 0; i < pts.length; i++) {
      const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
      a += x1 * y2 - x2 * y1;
    }
    return a / 2;
  }

  const polygonArea = pts => Math.abs(polygonSignedArea(pts));

  function ensureCCW(pts) {
    return polygonSignedArea(pts) < 0 ? pts.slice().reverse() : pts.slice();
  }

  function edgeDirection(p1, p2) {
    const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
    const len = Math.hypot(dx, dy);
    if (len === 0) throw new Error('長さ0の辺があります');
    return [dx / len, dy / len];
  }

  // CCW多角形で、辺 p1->p2 の内側を向く単位法線
  function interiorNormal(p1, p2) {
    const [dx, dy] = edgeDirection(p1, p2);
    return [-dy, dx];
  }

  function pointLineDistance(p, p1, p2) {
    const [dx, dy] = edgeDirection(p1, p2);
    return Math.abs((p[0] - p1[0]) * -dy + (p[1] - p1[1]) * dx);
  }

  function pointInPolygon(p, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p[1]) !== (yj > p[1]) &&
          p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  // 半平面 {x : normal・(x - origin) >= 0} で多角形を切る(Sutherland–Hodgman)
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

  // 各辺をそれぞれ distances[i] だけ内側へ下げた領域（Python版の
  // offset_polygon_by_edge_distances と同じく、辺の直線からの距離で切る）
  function offsetPolygonByEdgeDistances(points, distances) {
    const pts = ensureCCW(points);
    let region = pts.slice();
    for (let i = 0; i < pts.length; i++) {
      const d = distances[i];
      if (!d || d <= 0) continue;
      const p1 = pts[i], p2 = pts[(i + 1) % pts.length];
      const n = interiorNormal(p1, p2);
      region = clipByHalfPlane(region, [p1[0] + d * n[0], p1[1] + d * n[1]], n);
      if (region.length < 3) return null;
    }
    if (region.length < 3 || polygonArea(region) < 1e-9) return null;
    return region;
  }

  // 全辺を一律 d だけ内側へ縮める（凸多角形では buffer(-d) と一致）
  function erodePolygon(poly, d) {
    if (d <= 0) return poly.slice();
    return offsetPolygonByEdgeDistances(poly, new Array(poly.length).fill(d));
  }

  // 線分の交差判定（端点接触も交差とみなす）
  function segmentsIntersect(a1, a2, b1, b2) {
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const onSeg = (p, q, r) =>
      Math.min(p[0], r[0]) - 1e-12 <= q[0] && q[0] <= Math.max(p[0], r[0]) + 1e-12 &&
      Math.min(p[1], r[1]) - 1e-12 <= q[1] && q[1] <= Math.max(p[1], r[1]) + 1e-12;
    const d1 = cross(a1, a2, b1), d2 = cross(a1, a2, b2);
    const d3 = cross(b1, b2, a1), d4 = cross(b1, b2, a2);
    if (((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0))) return true;
    if (Math.abs(d1) < 1e-12 && onSeg(a1, b1, a2)) return true;
    if (Math.abs(d2) < 1e-12 && onSeg(a1, b2, a2)) return true;
    if (Math.abs(d3) < 1e-12 && onSeg(b1, a1, b2)) return true;
    if (Math.abs(d4) < 1e-12 && onSeg(b1, a2, b2)) return true;
    return false;
  }

  function segmentIntersectsPolygon(s1, s2, poly) {
    if (pointInPolygon(s1, poly) || pointInPolygon(s2, poly)) return true;
    for (let i = 0; i < poly.length; i++) {
      if (segmentsIntersect(s1, s2, poly[i], poly[(i + 1) % poly.length])) return true;
    }
    return false;
  }

  const azimuthDeg = (from, to) =>
    ((Math.atan2(to[0] - from[0], to[1] - from[1]) * 180) / Math.PI + 360) % 360;

  // ===== 用途地域 =====================================================
  const RESIDENTIAL_ZONES = new Set(
    ['1low', '2low', 'denen', '1mid', '2mid', '1res', '2res', 'quasi_res']);
  const COMMERCIAL_ZONES = new Set(['neighbor_commercial', 'commercial']);
  const INDUSTRIAL_ZONES = new Set(['quasi_industrial', 'industrial', 'industrial_exclusive']);

  const NORTH_SLANT_ZONES = {
    '1low': [5.0, 1.25], '2low': [5.0, 1.25], 'denen': [5.0, 1.25],
    '1mid': [10.0, 1.25], '2mid': [10.0, 1.25],
  };
  const ADJACENT_SLANT_BY_GROUP = { residential: [20.0, 1.25], other: [31.0, 2.5] };

  function zoneGroup(zone) {
    if (RESIDENTIAL_ZONES.has(zone)) return 'residential';
    if (COMMERCIAL_ZONES.has(zone) || INDUSTRIAL_ZONES.has(zone) || zone === 'unspecified') return 'other';
    throw new Error('不明な用途地域: ' + zone);
  }

  // 建築基準法 別表第三（Python版 zoning.ROAD_SLANT_TABLE と同じ）
  const ROAD_SLANT_TABLE = {
    residential: [
      { farUpper: 2.0, dist: 20.0, slope: 1.25 }, { farUpper: 3.0, dist: 25.0, slope: 1.25 },
      { farUpper: 4.0, dist: 30.0, slope: 1.25 }, { farUpper: null, dist: 35.0, slope: 1.25 },
    ],
    other: [
      { farUpper: 4.0, dist: 20.0, slope: 1.5 }, { farUpper: 6.0, dist: 25.0, slope: 1.5 },
      { farUpper: 8.0, dist: 30.0, slope: 1.5 }, { farUpper: 10.0, dist: 35.0, slope: 1.5 },
      { farUpper: 11.0, dist: 40.0, slope: 1.5 }, { farUpper: null, dist: 45.0, slope: 1.5 },
    ],
  };

  function roadSlantParams(zone, far) {
    for (const tier of ROAD_SLANT_TABLE[zoneGroup(zone)]) {
      if (tier.farUpper === null || far <= tier.farUpper) return tier;
    }
    throw new Error('unreachable');
  }

  // ===== 斜線制限 =====================================================
  function requiredSetbackForHeight(edge, h, site, slopeMultiplier) {
    slopeMultiplier = slopeMultiplier === undefined ? 1.0 : slopeMultiplier;
    if (h <= 0) return 0;
    const z = site.zoning;
    if (edge.kind === 'road') {
      const tier = roadSlantParams(z.zoneType, z.farRatio);
      const L0 = edge.roadWidthM + edge.setbackM;
      const H0 = tier.slope * L0;
      const sMax = Math.max(0, tier.dist - L0);
      if (h <= H0) return 0;
      return Math.min((h - H0) / (tier.slope * slopeMultiplier), sMax);
    }
    if (edge.kind === 'adjacent') {
      const [start, slope] = ADJACENT_SLANT_BY_GROUP[zoneGroup(z.zoneType)];
      const H0 = start + slope * edge.setbackM;
      return h <= H0 ? 0 : (h - H0) / (slope * slopeMultiplier);
    }
    if (edge.kind === 'north') {
      const p = NORTH_SLANT_ZONES[z.zoneType];
      if (!p) return 0;
      const [start, slope] = p;
      const H0 = start + slope * edge.setbackM;
      return h <= H0 ? 0 : (h - H0) / (slope * slopeMultiplier);
    }
    return 0;
  }

  function heightLimitAtPoint(site, p) {
    let h = Infinity;
    const z = site.zoning;
    for (const e of site.edges) {
      if (e.kind === 'road') {
        const tier = roadSlantParams(z.zoneType, z.farRatio);
        const L = pointLineDistance(p, e.p1, e.p2) + e.roadWidthM + e.setbackM;
        h = Math.min(h, L > tier.dist ? Infinity : tier.slope * L);
      } else if (e.kind === 'adjacent') {
        const [start, slope] = ADJACENT_SLANT_BY_GROUP[zoneGroup(z.zoneType)];
        h = Math.min(h, start + slope * (pointLineDistance(p, e.p1, e.p2) + e.setbackM));
      } else if (e.kind === 'north' && NORTH_SLANT_ZONES[z.zoneType]) {
        const [start, slope] = NORTH_SLANT_ZONES[z.zoneType];
        h = Math.min(h, start + slope * (pointLineDistance(p, e.p1, e.p2) + e.setbackM));
      }
    }
    if (z.absoluteHeightLimitM != null) h = Math.min(h, z.absoluteHeightLimitM);
    return h;
  }

  function estimateMaxRelevantHeight(site) {
    const z = site.zoning;
    if (z.absoluteHeightLimitM != null) return z.absoluteHeightLimitM;
    const cx = site.points.reduce((s, p) => s + p[0], 0) / site.points.length;
    const cy = site.points.reduce((s, p) => s + p[1], 0) / site.points.length;
    const vals = site.points.concat([[cx, cy]])
      .map(p => heightLimitAtPoint(site, p)).filter(v => Number.isFinite(v));
    return vals.length ? Math.max(...vals) * 1.3 : 100.0;
  }

  // ===== 適合建築物（斜線制限のみのベースライン） =====================
  function blocksAtThresholds(site, layerTops, slopeMultiplier) {
    const blocks = [];
    let prev = 0;
    for (const top of layerTops) {
      const dists = site.edges.map(e => requiredSetbackForHeight(e, prev, site, slopeMultiplier));
      const poly = offsetPolygonByEdgeDistances(site.points, dists);
      if (poly && polygonArea(poly) > 1e-6) {
        blocks.push({ footprint: poly, zBottom: prev, zTop: top });
      }
      prev = top;
    }
    return blocks;
  }

  function referenceBuildingBlocks(site, nLayers, maxHeight) {
    if (maxHeight == null) maxHeight = estimateMaxRelevantHeight(site);
    if (maxHeight <= 0) return [];
    const tops = [];
    for (let k = 0; k < nLayers; k++) tops.push((maxHeight * (k + 1)) / nLayers);
    return blocksAtThresholds(site, tops, 1.0);
  }

  // ===== 天空率 =======================================================
  // 方位azの半直線が footprint に入るまでの距離（入らない/内部ならnull）
  function rayEntryDistance(origin, azDeg, poly) {
    if (pointInPolygon(origin, poly)) return null;  // Python版と同じ扱い
    const a = (azDeg * Math.PI) / 180;
    const dx = Math.sin(a), dy = Math.cos(a);
    let best = Infinity;
    for (let i = 0; i < poly.length; i++) {
      const q1 = poly[i], q2 = poly[(i + 1) % poly.length];
      const ex = q2[0] - q1[0], ey = q2[1] - q1[1];
      const den = dx * ey - dy * ex;
      if (Math.abs(den) < 1e-15) continue;
      const t = ((q1[0] - origin[0]) * ey - (q1[1] - origin[1]) * ex) / den;
      const u = ((q1[0] - origin[0]) * dy - (q1[1] - origin[1]) * dx) / den;
      if (t > 1e-9 && u >= -1e-12 && u <= 1 + 1e-12 && t < best) best = t;
    }
    return Number.isFinite(best) ? best : null;
  }

  function silhouetteElevation(pt3, azDeg, blocks) {
    let maxElev = 0;
    for (const b of blocks) {
      if (b.zTop <= pt3[2]) continue;
      const r = rayEntryDistance([pt3[0], pt3[1]], azDeg, b.footprint);
      if (r == null) continue;
      const e = Math.atan2(b.zTop - pt3[2], r);
      if (e > maxElev) maxElev = e;
    }
    return maxElev;
  }

  // 正射影による天空率(%)。Python版 sky_ratio_percent と同じ式。
  function skyRatioPercent(pt3, blocks, nAzimuth) {
    const dphi = (2 * Math.PI) / nAzimuth;
    let total = 0;
    for (let i = 0; i < nAzimuth; i++) {
      const rho = Math.cos(silhouetteElevation(pt3, (i * 360) / nAzimuth, blocks));
      total += 0.5 * rho * rho * dphi;
    }
    return (total / Math.PI) * 100;
  }

  const MEASUREMENT_EPSILON_M = 1e-3;

  function measurementPoints(site, intervalM) {
    const pts = [];
    site.edges.forEach((edge, idx) => {
      if (edge.kind === 'north' && !NORTH_SLANT_ZONES[site.zoning.zoneType]) return;
      if (!['road', 'adjacent', 'north'].includes(edge.kind)) return;
      const nIn = interiorNormal(edge.p1, edge.p2);
      const shift = (edge.kind === 'road' ? edge.roadWidthM : 0) + MEASUREMENT_EPSILON_M;
      const p1 = [edge.p1[0] - shift * nIn[0], edge.p1[1] - shift * nIn[1]];
      const p2 = [edge.p2[0] - shift * nIn[0], edge.p2[1] - shift * nIn[1]];
      const [dx, dy] = edgeDirection(p1, p2);
      const len = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
      const n = Math.max(2, Math.ceil(len / intervalM) + 1);
      for (let k = 0; k < n; k++) {
        const t = (len * k) / (n - 1);
        pts.push({ point: [p1[0] + t * dx, p1[1] + t * dy], kind: edge.kind, edgeIndex: idx });
      }
    });
    return pts;
  }

  function checkSkyRatio(site, proposed, reference, intervalM, nAzimuth, measurementHeight) {
    return measurementPoints(site, intervalM).map(mp => {
      const p3 = [mp.point[0], mp.point[1], measurementHeight];
      const ps = skyRatioPercent(p3, proposed, nAzimuth);
      const pr = skyRatioPercent(p3, reference, nAzimuth);
      return { point: mp.point, kind: mp.kind, ps, pr, ok: ps >= pr, margin: ps - pr };
    });
  }

  // ===== 太陽位置・日影 ===============================================
  function dayOfYear(month, day) {
    const cum = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    return cum[month - 1] + day;
  }

  const solarDeclinationDeg = doy =>
    23.45 * Math.sin(((360 / 365) * (284 + doy) * Math.PI) / 180);

  function solarPositionDeg(latDeg, decDeg, trueSolarHour) {
    const phi = (latDeg * Math.PI) / 180, dec = (decDeg * Math.PI) / 180;
    const H = ((15 * (trueSolarHour - 12)) * Math.PI) / 180;
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

  // 敷地外周を distance だけ外へ広げた多角形（角はマイター＝辺を延長して交点）
  function offsetRingOutward(sitePoints, distance) {
    const pts = ensureCCW(sitePoints);
    const moved = pts.map((p1, i) => {
      const p2 = pts[(i + 1) % pts.length];
      const n = interiorNormal(p1, p2);
      return [[p1[0] - distance * n[0], p1[1] - distance * n[1]],
              [p2[0] - distance * n[0], p2[1] - distance * n[1]]];
    });
    const corners = [];
    for (let i = 0; i < moved.length; i++) {
      const [a1, a2] = moved[i], [b1, b2] = moved[(i + 1) % moved.length];
      const d1 = [a2[0] - a1[0], a2[1] - a1[1]], d2 = [b2[0] - b1[0], b2[1] - b1[1]];
      const den = d1[0] * d2[1] - d1[1] * d2[0];
      if (Math.abs(den) < 1e-12) { corners.push(a2); continue; }
      const t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / den;
      corners.push([a1[0] + t * d1[0], a1[1] + t * d1[1]]);
    }
    return corners;
  }

  // 外側ライン上の測定点。Python版と同じく「周長を n 等分した位置」を取る
  // （辺ごとに刻むのではなく通し弧長で刻む点まで合わせてある）。
  function perimeterSamplePoints(sitePoints, distance, intervalM) {
    const ring = offsetRingOutward(sitePoints, distance);
    const segLen = ring.map((p, i) => {
      const q = ring[(i + 1) % ring.length];
      return Math.hypot(q[0] - p[0], q[1] - p[1]);
    });
    const total = segLen.reduce((a, b) => a + b, 0);
    if (total <= 0) return ring.slice();
    const n = Math.max(3, Math.ceil(total / intervalM));
    const samples = [];
    for (let i = 0; i < n; i++) {
      let target = (total * i) / n;
      let k = 0;
      while (k < segLen.length && target > segLen[k]) { target -= segLen[k]; k++; }
      if (k >= ring.length) k = ring.length - 1;
      const p = ring[k], q = ring[(k + 1) % ring.length];
      const f = segLen[k] > 0 ? target / segLen[k] : 0;
      samples.push([p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f]);
    }
    return samples;
  }

  // 点pが blocks の影に入っているか（ミンコフスキー和を線分交差で判定）
  function pointInShadow(p, blocks, altDeg, azDeg) {
    if (altDeg <= 0) return false;
    const tan = Math.tan((altDeg * Math.PI) / 180);
    const a = (azDeg * Math.PI) / 180;
    const away = [-Math.sin(a), -Math.cos(a)];   // 影は太陽の反対側へ伸びる
    for (const b of blocks) {
      const L = b.zTop / tan;
      const shift = [away[0] * L, away[1] * L];
      const q = [p[0] - shift[0], p[1] - shift[1]];
      if (segmentIntersectsPolygon(p, q, b.footprint)) return true;
    }
    return false;
  }

  function computeShadowHours(site, blocks, sp) {
    const dec = solarDeclinationDeg(dayOfYear(sp.measurementMonth, sp.measurementDay));
    const step = sp.timeStepMinutes / 60;
    const hours = [];
    for (let h = sp.startHour; h < sp.endHour - 1e-9; h += step) hours.push(h);

    const lines = [
      { name: 'line1', distance: sp.line1DistanceM, maxHours: sp.line1MaxHours },
      { name: 'line2', distance: sp.line2DistanceM, maxHours: sp.line2MaxHours },
    ];
    return lines.map(spec => {
      const pts = perimeterSamplePoints(site.points, spec.distance, sp.perimeterSampleIntervalM);
      const dur = new Array(pts.length).fill(0);
      for (const hour of hours) {
        const [alt, az] = solarPositionDeg(sp.latitudeDeg, dec, hour);
        if (alt <= 0 || !blocks.length) continue;
        for (let i = 0; i < pts.length; i++) {
          if (pointInShadow(pts[i], blocks, alt, az)) dur[i] += step;
        }
      }
      const worst = dur.length ? Math.max(...dur) : 0;
      return {
        lineName: spec.name, maxHours: spec.maxHours, worstHours: worst,
        ok: worst <= spec.maxHours + 1e-9,
        pointHours: pts.map((p, i) => ({ point: p, hours: dur[i] })),
      };
    });
  }

  global.JwcadVolumeEngine = {
    polygonArea, polygonSignedArea, ensureCCW, interiorNormal, pointLineDistance,
    pointInPolygon, clipByHalfPlane, offsetPolygonByEdgeDistances, erodePolygon,
    segmentIntersectsPolygon, azimuthDeg,
    zoneGroup, roadSlantParams, NORTH_SLANT_ZONES, ADJACENT_SLANT_BY_GROUP,
    requiredSetbackForHeight, heightLimitAtPoint, estimateMaxRelevantHeight,
    blocksAtThresholds, referenceBuildingBlocks,
    rayEntryDistance, silhouetteElevation, skyRatioPercent, measurementPoints, checkSkyRatio,
    dayOfYear, solarDeclinationDeg, solarPositionDeg,
    offsetRingOutward, perimeterSamplePoints, pointInShadow, computeShadowHours,
  };
})(typeof window !== 'undefined' ? window : globalThis);
