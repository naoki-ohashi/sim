/* Web版アプリの画面まわり（入力フォーム ⇔ 計算エンジン ⇔ 3Dビューア）
 *
 * 計算そのものは engine.js / envelope.js（Python版の移植）が担当し、
 * 描画は viewer.js（Python版の出力と共通）が担当します。ここはその接続と、
 * 設定YAMLの読み書きだけを持ちます。
 */
(function () {
  'use strict';

  const E = window.JwcadVolumeEngine;
  const V = window.JwcadVolumeEnvelope;
  const $ = id => document.getElementById(id);

  const PRECISION = {
    fast:   { nLayers: 8,  intervalM: 6.0, nAzimuth: 36,  iterations: 10 },
    normal: { nLayers: 14, intervalM: 4.0, nAzimuth: 60,  iterations: 14 },
    fine:   { nLayers: 24, intervalM: 2.0, nAzimuth: 120, iterations: 20 },
  };
  const KIND_LABELS = { road: '道路境界', adjacent: '隣地境界', north: '北側境界', none: '規制なし' };

  let lastResult = null;

  // ===== 入力の読み取り ===============================================
  function sitePoints() {
    if ($('shape-mode').value === 'rect') {
      const w = +$('width').value, d = +$('depth').value;
      return [[0, 0], [w, 0], [w, d], [0, d]];
    }
    const pts = $('poly-points').value.trim().split('\n')
      .map(line => line.split(',').map(s => parseFloat(s.trim())))
      .filter(p => p.length === 2 && p.every(Number.isFinite));
    if (pts.length < 3) throw new Error('敷地の頂点が3つ以上必要です');
    return E.ensureCCW(pts);
  }

  function rebuildEdgeKinds() {
    let pts;
    try { pts = sitePoints(); } catch { return; }
    const container = $('edge-kinds');
    const previous = Array.from(container.querySelectorAll('select')).map(s => s.value);
    // 長方形の既定: 南=道路 / 東西=隣地 / 北=北側境界
    const defaults = pts.length === 4 ? ['road', 'adjacent', 'north', 'adjacent'] : [];
    container.innerHTML = '';
    pts.forEach((_, i) => {
      const label = document.createElement('span');
      label.textContent = `${i + 1}番の辺`;
      label.style.color = 'var(--muted)';
      const select = document.createElement('select');
      for (const [value, text] of Object.entries(KIND_LABELS)) {
        const opt = document.createElement('option');
        opt.value = value; opt.textContent = text;
        select.appendChild(opt);
      }
      select.value = previous[i] || defaults[i] || 'none';
      container.appendChild(label);
      container.appendChild(select);
    });
  }

  function buildSite() {
    const pts = sitePoints();
    const kinds = Array.from($('edge-kinds').querySelectorAll('select')).map(s => s.value);
    const roadWidth = +$('road-width').value;
    const setback = +$('setback').value;
    const absHeight = $('abs-height').value === '' ? null : +$('abs-height').value;
    return {
      points: pts,
      edges: pts.map((p1, i) => ({
        p1, p2: pts[(i + 1) % pts.length],
        kind: kinds[i] || 'none',
        roadWidthM: (kinds[i] === 'road') ? roadWidth : 0,
        setbackM: setback,
      })),
      zoning: {
        zoneType: $('zone').value,
        farRatio: +$('far').value / 100,
        coverageRatio: +$('coverage').value / 100,
        absoluteHeightLimitM: absHeight,
      },
      floorHeightM: +$('floor-height').value,
    };
  }

  function buildOptions() {
    const p = PRECISION[$('precision').value];
    return {
      nLayers: p.nLayers, intervalM: p.intervalM, nAzimuth: p.nAzimuth,
      measurementHeight: 0, splitFractions: [0.3, 0.5, 0.7], iterations: p.iterations,
      stageInsetsM: [0, 3, 6], maxStages: +$('max-stages').value,
      useSkyRatio: $('use-sky').checked,
      shadowParams: $('shadow-on').checked ? {
        measurementMonth: 12, measurementDay: 22, startHour: 8, endHour: 16,
        timeStepMinutes: 20, latitudeDeg: +$('lat').value,
        line1DistanceM: +$('l1d').value, line1MaxHours: +$('l1h').value,
        line2DistanceM: +$('l2d').value, line2MaxHours: +$('l2h').value,
        perimeterSampleIntervalM: 5,
      } : null,
    };
  }

  // ===== 3Dビューア用データへの変換 ===================================
  // Python版 mesh.blocks_to_faces と同じく、側面・上面・底面を作る。
  function blocksToFaces(blocks, cx, cy) {
    const faces = [];
    const merged = [];
    for (const b of blocks) {
      const last = merged[merged.length - 1];
      const sameArea = last && Math.abs(E.polygonArea(b.footprint) - E.polygonArea(last.footprint)) < 1e-9;
      if (last && sameArea && Math.abs(b.zBottom - last.zTop) < 1e-9) last.zTop = b.zTop;
      else merged.push({ footprint: b.footprint, zBottom: b.zBottom, zTop: b.zTop });
    }
    const r = 1000;
    const round3 = v => Math.round(v * r) / r;
    for (const b of merged) {
      const ring = b.footprint;
      for (let i = 0; i < ring.length; i++) {
        const [x1, y1] = ring[i], [x2, y2] = ring[(i + 1) % ring.length];
        faces.push({ k: 'wall', v: [
          [round3(x1 - cx), round3(y1 - cy), round3(b.zBottom)],
          [round3(x2 - cx), round3(y2 - cy), round3(b.zBottom)],
          [round3(x2 - cx), round3(y2 - cy), round3(b.zTop)],
          [round3(x1 - cx), round3(y1 - cy), round3(b.zTop)],
        ] });
      }
      faces.push({ k: 'top', v: ring.map(p => [round3(p[0] - cx), round3(p[1] - cy), round3(b.zTop)]) });
      faces.push({ k: 'bottom', v: ring.slice().reverse()
        .map(p => [round3(p[0] - cx), round3(p[1] - cy), round3(b.zBottom)]) });
    }
    return faces;
  }

  function viewerData(result) {
    const pts = result.site.points;
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const top = result.baselineBlocks.reduce((m, b) => Math.max(m, b.zTop), 10);
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), top);
    return {
      site: pts.map(p => [p[0] - cx, p[1] - cy]),
      final: blocksToFaces(result.blocks, cx, cy),
      baseline: blocksToFaces(result.baselineBlocks, cx, cy),
      summary: V.summaryLinesJa(result),
      radius: span * 0.75 || 1,
    };
  }

  // ===== 実行 =========================================================
  function run() {
    const status = $('status');
    $('run').disabled = true;
    status.textContent = '計算中…';
    // 画面に「計算中」を出してから重い処理に入る
    setTimeout(() => {
      try {
        const site = buildSite();
        lastResult = V.computeMaxEnvelope(site, buildOptions());
        window.JwcadVolumeViewer.setData(viewerData(lastResult));
        const v = V.totalVolume(lastResult.blocks);
        status.textContent = v > 0
          ? `体積 ${v.toFixed(0)} m3 / 最高高さ ${V.maxHeight(lastResult.blocks).toFixed(1)} m`
          : '建てられるボリュームがありません（条件を見直してください）';
      } catch (err) {
        status.textContent = 'エラー: ' + err.message;
        console.error(err);
      } finally {
        $('run').disabled = false;
      }
    }, 30);
  }

  // ===== 設定YAMLの書き出し／読み込み =================================
  function toYaml() {
    const site = buildSite();
    const opt = buildOptions();
    const z = site.zoning;
    const lines = [
      '# jwcad-volume 設定ファイル（Web版から書き出し）',
      'site:', '  points:',
      ...site.points.map(p => `    - [${p[0]}, ${p[1]}]`),
      '  edges:',
    ];
    for (const e of site.edges) {
      lines.push(`    - kind: ${e.kind}`);
      if (e.kind === 'road') lines.push(`      road_width_m: ${e.roadWidthM}`);
      lines.push(`      setback_m: ${e.setbackM}`);
    }
    lines.push('  zoning:',
      `    zone_type: ${z.zoneType}`,
      `    far_ratio: ${z.farRatio}`,
      `    coverage_ratio: ${z.coverageRatio}`,
      `    absolute_height_limit_m: ${z.absoluteHeightLimitM === null ? 'null' : z.absoluteHeightLimitM}`,
      `  floor_height_m: ${site.floorHeightM}`,
      '', 'envelope:',
      `  n_layers: ${opt.nLayers}`,
      `  interval_m: ${opt.intervalM}`,
      `  n_azimuth: ${opt.nAzimuth}`,
      `  use_sky_ratio: ${opt.useSkyRatio}`,
      `  split_fractions: [${opt.splitFractions.join(', ')}]`,
      `  search_iterations: ${opt.iterations}`,
      `  stage_insets_m: [${opt.stageInsetsM.join(', ')}]`,
      `  max_stages: ${opt.maxStages}`);
    if (opt.shadowParams) {
      const s = opt.shadowParams;
      lines.push('', 'shadow:',
        `  measurement_month: ${s.measurementMonth}`, `  measurement_day: ${s.measurementDay}`,
        `  start_hour: ${s.startHour}`, `  end_hour: ${s.endHour}`,
        `  time_step_minutes: ${s.timeStepMinutes}`, `  latitude_deg: ${s.latitudeDeg}`,
        `  line1_distance_m: ${s.line1DistanceM}`, `  line1_max_hours: ${s.line1MaxHours}`,
        `  line2_distance_m: ${s.line2DistanceM}`, `  line2_max_hours: ${s.line2MaxHours}`,
        `  perimeter_sample_interval_m: ${s.perimeterSampleIntervalM}`);
    }
    lines.push('', 'output:', '  dxf_path: envelope.dxf', '  html3d_path: envelope_3d.html', '');
    return lines.join('\n');
  }

  // Python版が書いた設定YAMLを読む簡易パーサ（この書式に必要な範囲だけ）
  function fromYaml(text) {
    const num = re => { const m = text.match(re); return m ? parseFloat(m[1]) : null; };
    const str = re => { const m = text.match(re); return m ? m[1].trim() : null; };

    const pts = [];
    const ptSection = text.match(/points:\s*\n((?:\s*-\s*\[.*\]\s*\n)+)/);
    if (ptSection) {
      for (const line of ptSection[1].split('\n')) {
        const m = line.match(/\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]/);
        if (m) pts.push([parseFloat(m[1]), parseFloat(m[2])]);
      }
    }
    if (pts.length >= 3) {
      $('shape-mode').value = 'poly';
      $('poly-points').value = pts.map(p => `${p[0]},${p[1]}`).join('\n');
      toggleShapeMode();
    }

    const kinds = Array.from(text.matchAll(/-\s*kind:\s*(\w+)/g)).map(m => m[1]);
    const zone = str(/zone_type:\s*(\S+)/);
    if (zone) $('zone').value = zone;
    const far = num(/far_ratio:\s*([\d.]+)/); if (far !== null) $('far').value = far * 100;
    const cov = num(/coverage_ratio:\s*([\d.]+)/); if (cov !== null) $('coverage').value = cov * 100;
    const abs = str(/absolute_height_limit_m:\s*(\S+)/);
    $('abs-height').value = (abs && abs !== 'null') ? abs : '';
    const fh = num(/floor_height_m:\s*([\d.]+)/); if (fh !== null) $('floor-height').value = fh;
    const rw = num(/road_width_m:\s*([\d.]+)/); if (rw !== null) $('road-width').value = rw;
    const sb = num(/setback_m:\s*([\d.]+)/); if (sb !== null) $('setback').value = sb;
    const ms = num(/max_stages:\s*(\d+)/); if (ms !== null) $('max-stages').value = ms;

    const hasShadow = /\nshadow:/.test(text);
    $('shadow-on').checked = hasShadow;
    if (hasShadow) {
      const lat = num(/latitude_deg:\s*([\d.]+)/); if (lat !== null) $('lat').value = lat;
      const l1d = num(/line1_distance_m:\s*([\d.]+)/); if (l1d !== null) $('l1d').value = l1d;
      const l1h = num(/line1_max_hours:\s*([\d.]+)/); if (l1h !== null) $('l1h').value = l1h;
      const l2d = num(/line2_distance_m:\s*([\d.]+)/); if (l2d !== null) $('l2d').value = l2d;
      const l2h = num(/line2_max_hours:\s*([\d.]+)/); if (l2h !== null) $('l2h').value = l2h;
    }
    toggleShadow();

    rebuildEdgeKinds();
    if (kinds.length) {
      Array.from($('edge-kinds').querySelectorAll('select'))
        .forEach((s, i) => { if (kinds[i]) s.value = kinds[i]; });
    }
  }

  function download(name, text, mime) {
    const blob = new Blob([text], { type: mime || 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // Python版の write_viewer_html と同じ構成の単一HTMLを書き出す。
  // 描画コード(viewer.js)の中身が必要なので、単一ファイル版としてビルド
  // された場合(tools/build_web.py)のみ利用できる。
  function exportHtml() {
    if (!lastResult) { alert('先に「計算する」を押してください'); return; }
    const source = window.__VIEWER_JS_SOURCE__;
    if (!source) {
      alert('この機能は単一ファイル版でのみ使えます。\n'
        + 'python3 tools/build_web.py で作った jwcad-volume-web.html を開くか、\n'
        + '設定YAMLを保存してPython版で出力してください。');
      return;
    }
    const data = viewerData(lastResult);
    download('envelope_3d.html', window.__VIEWER_HTML_TEMPLATE__
      .replace('__TITLE__', '最大ボリューム 3Dビュー')
      .replace('__VIEWER_JS__', source)
      .replace('__DATA__', JSON.stringify(data)), 'text/html;charset=utf-8');
  }

  // ===== 画面の初期化 =================================================
  function toggleShapeMode() {
    const rect = $('shape-mode').value === 'rect';
    $('rect-inputs').style.display = rect ? '' : 'none';
    $('poly-inputs').style.display = rect ? 'none' : '';
  }
  function toggleShadow() {
    $('shadow-inputs').style.display = $('shadow-on').checked ? '' : 'none';
  }

  $('shape-mode').addEventListener('change', () => { toggleShapeMode(); rebuildEdgeKinds(); });
  $('poly-points').addEventListener('change', rebuildEdgeKinds);
  $('shadow-on').addEventListener('change', toggleShadow);
  $('run').addEventListener('click', run);
  $('export-yaml').addEventListener('click', () => {
    try { download('site.yaml', toYaml(), 'text/yaml;charset=utf-8'); }
    catch (err) { alert('エラー: ' + err.message); }
  });
  $('import-yaml').addEventListener('click', () => $('file-input').click());
  $('file-input').addEventListener('change', e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try { fromYaml(reader.result); $('status').textContent = '設定を読み込みました'; }
      catch (err) { alert('読み込みに失敗しました: ' + err.message); }
    };
    reader.readAsText(file);
    e.target.value = '';
  });
  $('export-html').addEventListener('click', exportHtml);

  toggleShapeMode();
  toggleShadow();
  rebuildEdgeKinds();
  window.JwcadVolumeViewer.init({ site: [], final: [], baseline: [], summary: [], radius: 1 });
  run();
})();
