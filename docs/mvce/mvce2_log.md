# MVCE 2.0 実装ログ

基本設計書（`MVCE 2.0 基本設計書` 0.3 版）に沿った実装の進捗と、実装中に
下した判断の記録です。基本設計書そのものはリポジトリ外にあります。

フェーズの受入基準は基本設計書 第9章。着手条件は「前フェーズのテストが
全て緑であること」です。

| フェーズ | 内容 | 状態 |
|---|---|---|
| Phase 0 | 土台の整備（リネーム・モジュール移設・`Verdict`・台帳の骨組み） | **完了** |
| Phase 1 | 法規カーネルの穴埋め（令2条2項・座標系・法52条7項/9項・令135条の12第2項・法58条） | 未着手 |
| Phase 2 | 天空率の告示準拠化（プロファイル機構・適合建築物・算定位置） | 未着手 |
| Phase 3 | 逆解析エンジン（逆天空率・`ShadowAttribution`・等時間日影線・自治体追加規制線） | 未着手 |
| Phase 4 | SIM WORLD 接続と実機検証 | 未着手 |

---

## Phase 0 — 土台の整備

### やったこと

- `mve/` → `mvce/` のリネーム。あわせて `tests/mve/` → `tests/mvce/`、
  `web/mve/` → `web/mvce/`、`docs/mve/` → `docs/mvce/`、
  `tools/build_mve_web.py` → `tools/build_mvce_web.py`、
  `MVE実行.bat` → `MVCE実行.bat`、`examples/mve_sample.yaml` →
  `examples/mvce_sample.yaml`、配布物 `dist/MVE.html` → `dist/MVCE.html`。
  CLI のコマンド名も `mve` → `mvce`。
- 基本設計書 第3.2節のツリーに合わせたモジュール移設。

  | 移動前 | 移動後 |
  |---|---|
  | `mve/shadow_index.py` | `mvce/index/shadow_index.py` |
  | `mve/sky_index.py` | `mvce/index/sky_index.py` |
  | `mve/isochrone.py` | `mvce/index/isochrone.py` |
  | `mve/optimizer.py` | `mvce/solvers/optimizer.py` |
  | `mve/roof_envelope.py` | `mvce/inverse/shadow_envelope.py` |
  | （新規） | `mvce/profiles/`（Phase 2 で中身を実装） |

  テストも `tests/mvce/test_roof_envelope.py` →
  `tests/mvce/test_shadow_envelope.py` に追従。
- `mvce/verdict.py` を新設（`Verdict` / `Judgement` / `Reason` /
  `UNDETERMINED` 番兵）。テスト `tests/mvce/test_verdict.py` 45件。
- `docs/mvce/legal_basis.md` に条文照合台帳の骨組みを追加。

### 判断の記録

以下は基本設計書に明示がない、または書きぶりと現物がずれていた点について
実装側で下した判断です。**違うと思ったら差し替えてください。**

#### 1. DXF のレイヤ名は `MVE-*` のまま残した

基本設計書 第7.1節は等時間日影線のレイヤを `MVCE-ISOCHRONE-{時間}` と
書いています。しかし Phase 0 の受入基準は「挙動の変更ゼロ」であり、
レイヤ名は JW-CAD 側のテンプレート・線色設定・図面レイヤ分けが依存する
出力仕様です。ここで変えると既存図面の運用が黙って壊れます。

そこで Phase 0 では `MVE-SITE` などの既存レイヤ名をすべて維持しました。
`dxf_r12.py` の出力書式を変えないという禁止事項（第11章）とも整合します。

改名するなら、Phase 3 で等時間日影線を正式機能化するときに、
**旧名と新名のどちらで出すかを設定で選べる形**にするのが安全です。
一括改名してよいなら指示をください。

#### 2. `docs/legal_basis.md` ではなく `docs/mvce/legal_basis.md` に置いた

基本設計書 第3.2節のツリーは `docs/legal_basis.md` を指していますが、
このリポジトリの `docs/legal_basis.md` は旧 `jwcad_volume` パッケージの
ものとして既に存在します。MVCE の文書は `docs/mvce/` 配下にまとまって
いるので、そちらに置きました。`docs/mvce/profiles.md`（Phase 2）、
`docs/mvce/regression_notes.md`（Phase 2）も同じ場所に作る想定です。

#### 3. 不変条件 M-6 は `FAIL` に対しても効かせた

M-6 は「下位のどれか一つでも `UNDETERMINED` なら、上位の総合判定も
`UNDETERMINED`」と書いてあります。`FAIL` と `UNDETERMINED` が並んだとき
どちらが勝つかは書かれていませんが、条文どおり `UNDETERMINED` を勝たせ
ました。

理由は不変条件 M-3 です。MVCE の出力は「なぜこれ以上入らないか」
（`binding_constraint`）を答えられなければ事業収支の判断材料になりません。
判断できない制約が残っている限り支配的制約を名指しできないので、
総合判定は「判断できない」が正確です。

情報は落ちません。`Judgement.parts` に下位判定がそのまま残るので、
`judgement.find(Verdict.FAIL)` で明確な不適合を取り出せます。

「日影が明確に落ちているなら総合も `FAIL` にしてほしい」という運用なら、
`mvce/verdict.py` の `_PRECEDENCE` を1行変えるだけです。

#### 4. `Verdict.UNDETERMINED` には理由を必須にした

`Judgement` の生成時に、`UNDETERMINED` なのに `Reason` も下位判定も無い
場合は `VerdictError` にしています。原則H の「サイレントなデフォルト値
充填をしない」を、呼び出し側の心がけではなく型で担保するためです。

同じ考えで、`parts` を持つ `Judgement` の `verdict` が
`combine(parts)` と食い違う場合も生成時に落とします。集約する側が
`PASS` で握りつぶせません。

#### 5. `UNDETERMINED` 番兵は算術を拒否する

`achievable_far: float | UNDETERMINED`（第8.2節）のような数値フィールド
のために番兵オブジェクトを置きました。`0` や `NaN` として静かに計算へ
紛れ込むのを防ぐため、四則演算・比較・`float()` はすべて `TypeError` に
しています。`None`（未設定）とも区別します。

### 受入基準の確認

- 既存テスト全件と新規45件が緑（`python -m pytest`）。
- 挙動の変更は、リネームに伴う CLI コマンド名・配布 HTML のファイル名・
  設定サンプルのファイル名のみ。計算結果と DXF 出力は不変。

### Phase 1 に入る前に決めてほしいこと

- 上記「判断の記録」1（DXF レイヤ名）。
- 基本設計書 第12.3節 第1段の検証ケース 5〜8 件（Jw_cad → DXF 変換したもの）。
  Phase 2 の着手時期を直接左右します。Phase 1 は無くても進みます。
