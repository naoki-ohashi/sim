# MVCE3 実装ログ

`mvce3_basic_spec.md`（基本仕様書）・`mvce3_design_spec.md`（基本設計書）に
沿った実装の記録です。`mvce2_log.md` と同じ形式で、判断の理由を残します。

## やったこと

- `mvce/floors.py` — `OptimizeResult.blocks` を階ごとにまとめる
  `FloorSlab` とその組み立て
- `mvce/reports/floor_area_table.py` — 各階床面積表のデータ構造と
  `openpyxl` による `.xlsx` 出力
- `mvce/model3d/` — 3Dモデル化のバックエンド抽象（`mesh` / `freecad` /
  `blender`）と、耳切り法による三角形分割（`solid.py`）
- `mvce/cli.py`・`mvce/config.py` — `--floor-area-xlsx` /
  `--model3d-out` / `--model3d-backend`、設定YAMLの `output.*` 3項目
- `pyproject.toml` — `openpyxl` を `xlsx` エクストラに追加
- `tests/mvce/test_floors.py`・`test_floor_area_table.py`・
  `test_model3d.py`（新規20件、既存1070件はすべて緑）

## 判断の記録

### 1. `mvce` パッケージはリネームしなかった

依頼は「MVCE2を再検討してMVCE3を作る」でしたが、MVE→MVCEのときと違い、
**パッケージ名・CLIコマンド名・DXFレイヤ名は変えていません**
（`mvce3_basic_spec.md` 1.3節）。理由は次の2点です。

1. 法規カーネル（`regulations/`・`solvers/`・`verdict.py` 等）には一切
   手を入れておらず、MVE→MVCEのときのような実体の移動・改名に見合う
   変更が無いこと
2. 900件を超える既存テスト・examples・ドキュメントの参照をすべて
   `mvce3` に付け替えるコストが、今回の追加機能（3D強化・床面積表）の
   規模に見合わないこと

「MVCE3」は追加機能の名前として使い、パッケージは `mvce/` のまま
拡張しました。もし将来的に法規カーネル自体を大きく作り直すタイミングが
来れば、そのときは名前を含めた作り直し（MVE→MVCEと同じ形）を検討すべきです。

### 2. 中抜き（穴）の扱いを3バックエンドで揃えなかった

`mesh`（自前の耳切り法）と `blender`（`bpy`のメッシュ）は、穴のある階を
**外周のみ**で描画します。穴を正しく扱うには「穴を外周へブリッジする」
拡張耳切り法か、ブーリアン演算が要り、実装・検証のコストが両バックエンドの
位置づけ（`mesh`=最小構成の既定、`blender`=ビジュアライズ用途）に見合わないと
判断しました。

`freecad` バックエンドだけは `Part.Face` が内側ワイヤを直接扱えるため、
追加コストなしで正確に穴を表現できます。**穴のある平面が分かっている
案件では `freecad` バックエンドを使ってください**、とドキュメントに明記
しました（黙って不正確な結果を既定にしないため）。

### 3. FreeCAD・Blenderのバックエンドはこの環境で実行検証していない

このリポジトリの開発・テスト環境には、FreeCAD・Blenderのどちらも
インストールされておらず、`pip install` でも入りません（アプリケーション
本体が要るため）。したがって `freecad_backend.py`・`blender_backend.py` は
**両ツールの公開Python APIドキュメントの仕様に基づいて書きましたが、
実際にそのツールで実行して動作を確認できていません。**

これは`mvce2_log.md`の原則F（出典・限界を隠さない）と同じ考え方です。
「実装した」と「検証した」を混同しないよう、両モジュールのdocstring・
`mvce3_design_spec.md` 4.3〜4.4節・`disclaimer.md` すべてに同じ注記を
繰り返しています。自動テストで検証できているのは「ツールが無いときに
`Model3DBackendUnavailable` が正しく送出されること」までです。

利用者側でFreeCAD・Blenderが使える環境があれば、実際に試して
`mvce3_design_spec.md` の該当節を更新してください（未検証の期間が長引く
ほど、仕様変更（特にBlenderのオペレーター名。4.0で `export_scene.obj`
→ `wm.obj_export` に変更された前例あり）に気づけなくなります）。

### 4. `shapely.ops.triangulate` を使わず自前の耳切り法にした

`shapely.ops.triangulate` はドロネー三角形分割で、**凹多角形の外形を
はみ出したり内部が欠けたりします**。MVCE2の最大ボリューム計算は凹型の
建物配置（日影規制で一部だけ後退した形など）をごく普通に返すため、
見た目のための三角形分割であってもこの性質は許容できません。
`mvce/model3d/solid.py` に約80行の耳切り法を実装し、凸・凹（L字型）
両方で面積が保存されることをテストで固定しました。

### 5. Excelの行は上階から並べた

`mvce/reports/floor_area_table.py` の内部データ（`FloorAreaTable.rows`）は
階番号の昇順（1階→最上階）ですが、`.xlsx` に書き出すときは**上階から
下階の順**に並べ替えています。確認申請の各階床面積表の慣例に合わせた
表示上の判断で、内部データの並びには影響しません。

## 受入基準の確認

- 既存テスト1070件・新規20件がすべて緑（`python -m pytest`）
- CLIから `--floor-area-xlsx` と `--model3d-out --model3d-backend mesh`
  を同時に指定した実行で、`.xlsx` と `.obj` が実際に生成されることを
  手動で確認済み（`examples/mvce_sample.yaml` で実行）
- 法規カーネル側のテスト結果・出力（DXF・3D HTML・サマリー）に変更なし
