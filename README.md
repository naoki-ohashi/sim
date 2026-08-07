# MVE / jwcad-volume

このリポジトリには2つのパッケージがあります。

| | 用途 | 状態 |
|---|---|---|
| **`mve/`** | 日影規制・斜線制限をふまえた最大容積の計算エンジン | **現行**。日影対応をボクセル法で作り直し、複数前面道路・各種緩和・真北・測定面選択に対応 |
| `jwcad_volume/` | JW-CAD外部変形連携（JWC形式・バッチ・exe化） | 実績があるため維持。計算エンジンとしてはMVEが後継 |

**MVEの使い方は [`docs/mve/README.md`](docs/mve/README.md) を参照してください。**

```bash
mve examples/mve_sample.yaml
```

以下は `jwcad_volume` の説明です。

---

# jwcad-volume

JW-CAD（JWW）向けの外部変形プログラム：**道路斜線制限・隣地斜線制限・北側斜線
制限**を天空率算定（建築基準法56条7項）で読み替え、日影規制もあわせて確認
しながら、敷地に建築可能な**最大ボリューム**を計算・作図します。

> **重要:** これは設計初期段階の検討ツールです。確認申請に使える精度・様式
> ではありません。必ず `docs/disclaimer.md` を読んでから使ってください。

## できること

- 敷地形状・前面道路幅員・用途地域・容積率・建蔽率から、斜線制限のみによる
  適合建築物（ベースライン）のボリュームを算定
- 天空率算定により、斜線制限を超える高さを許容する「ポディウム＋タワー」型の
  ボリューム増分を探索（ヒューリスティックです。`docs/methodology.md` 参照）
- 冬至等の指定日の日影時間を計算し、日影規制ラインでの適合性を確認、
  違反時は建物高さを自動的に縮小
- 建蔽率・容積率の上限を反映
- JW-CAD/JWWへ読み込み可能なDXFファイル（平面・断面・アイソメ・サマリー付き）を出力
- **ブラウザで回して見られる3Dビューア**（単一HTML・外部ライブラリなし）を出力

## 使い方は3通り

| | Web版（ブラウザだけ） | A. コマンド実行 → DXFをJWWで開く | B. JWWの外部変形として使う |
|---|---|---|---|
| 必要なもの | ブラウザのみ | Python | exeビルド（Python不要な配布可） |
| 手軽さ | ◎ 入力してすぐ結果 | ○ すぐ試せる | △ ビルドが必要 |
| 確実性 | ◎ | ◎ DXF読込はJWWの標準機能 | △ 外部変形の書式は実機未検証 |
| 出力 | 画面の3D / 設定YAML / 3D HTML | DXF・3D HTML | 図面に直接作図 |

Web版で条件を詰めて設定YAMLを保存し、Python版でDXFやJWWに出す、という
使い分けができます（`docs/web_app.md`）。

**Windowsでの導入手順は `docs/windows_setup.md` に詳しくまとめてあります。**

## Web版をすぐ試す

```bash
python3 tools/build_web.py     # dist/jwcad-volume-web.html ができます
```

出来たHTMLをダブルクリックするだけです。通信は一切せず、外部ライブラリも
CDNも使っていません。計算エンジンはPython版の移植で、**同じ入力なら同じ
結果になることを自動テストで担保**しています（`tests/test_js_parity.py`）。

## インストール

```bash
pip install -e .
```

Python 3.9+、依存パッケージ: shapely, ezdxf, numpy, PyYAML（`pyproject.toml` 参照）。

## A. クイックスタート（コマンド実行）

```bash
jwcad-volume examples/sample_site.yaml
```

`examples/sample_site.yaml` を自分の敷地に合わせて編集してください
（敷地座標・道路幅員・用途地域・容積率・建蔽率・日影規制の時間数など）。
実行すると計算結果のサマリーが標準出力に表示され、`output.dxf_path` に
指定したDXFファイルが生成されます。生成したDXFはJW-CAD/JWWの通常の
DXF読み込み機能でそのまま開けます（レイヤー構成は
`docs/jww_integration.md` 参照）。

計算の速度と精度はトレードオフです。デフォルトはクイックプレビュー用の
低解像度設定です。パラメータを固めた後の最終チェックでは、
`examples/sample_site.yaml` の `envelope:` セクションのコメントに従って
`n_layers` / `interval_m` / `n_azimuth` / `search_iterations` を上げてください
（数十秒～数分かかるようになります）。

## 3Dで確認する

```bash
jwcad-volume examples/sample_site.yaml --html-out volume3d.html
```

出来たHTMLをダブルクリックすればブラウザで開き、マウスで回して確認
できます。**斜線制限のエンベロープ（青の半透明）の中に最終ボリューム
（オレンジ）が収まっている**様子が見え、すき間が建蔽率・容積率・
日影規制で削られた分になります。外部ライブラリもCDNも使っていないので
オフラインで開け、そのままメール添付で渡せます。

JWWの中で立体を見たい場合は、平行投影した**アイソメ図**が平面図の隣に
2Dの線分として作図されます（JWWは2D CADなので回転はできませんが、
視点の方位・仰角は設定で変更でき、新しいソフトは不要です）。

詳しくは `docs/3d_view.md` を参照してください。

## B. JWWの外部変形として使う

Windowsで `build_windows.bat` を実行するとexe一式が `dist\jww\` にできます
（Pythonのないパソコンでも動くexeになります）。

JWWで敷地の外形線を**辺ごとに線色を変えて**描き、範囲選択して
[その他]-[外部変形] から `最大ボリューム計算.bat` を選ぶと、結果が
図面に作図されます。

| 線色 | 意味 |
|---|---|
| 線色1 | 道路境界線 |
| 線色2 | 隣地境界線 |
| 線色3 | 北側境界線（真北側の辺） |

用途地域・容積率・道路幅員など図面から読み取れない条件は
`gaihen_params.yaml` に書きます。

> **外部変形のデータ書式は実機JWWで検証できていません**（開発環境で
> JWW本体を実行できないため）。うまく動かない場合は、同梱の
> `診断_データ確認.bat` でJWWが実際に渡してくるデータを採取し、
> `docs/jww_integration.md` の手順で調整してください。書式を直す箇所は
> `jwc.py` とバッチの制御行だけで、計算エンジンには影響しません。

## 構成

```
jwcad_volume/
  geometry.py                 # 敷地ポリゴン・エッジ別オフセット等の幾何ユーティリティ
  zoning.py                   # 用途地域・道路斜線の適用距離/勾配テーブル
  site.py                     # 敷地・境界線(Boundary)・用途地域パラメータのデータモデル
  massing.py                  # 建物ボリューム(Block=平面形状×高さ範囲の積層)
  solar.py                    # 太陽位置(高度・方位角)計算
  envelope.py                 # 最大ボリューム探索(compute_max_envelope)
  jwc.py                      # JWW外部変形のデータ形式(JWC_TEMP.TXT)読み書き
  ring_builder.py             # バラバラの線分群から閉じた敷地ポリゴンを再構成
  gaihen.py                   # 外部変形エントリポイント(図面→計算→図面)
  mesh.py                     # 3D面の生成と軸測投影(3Dビューア/アイソメ共通)
  regulations/
    road_slant.py             # 道路斜線制限
    adjacent_slant.py         # 隣地斜線制限
    north_slant.py            # 北側斜線制限
    combined.py                # 3斜線の合成、高さ→必要後退距離の逆算
    reference_building.py     # 天空率比較用の適合建築物(ベースライン)生成
    sky_ratio.py               # 天空率算定エンジン(Ps/Pr比較)
    shadow.py                  # 日影規制(日影時間の集計)
  output/
    dxf_writer.py               # DXF出力(検証済み・推奨)
    html3d.py                    # ブラウザ3Dビューア(単一HTML・依存ライブラリなし)
    isometric.py                 # アイソメ図を2D線分として生成
    gaihen_text.py               # JWW外部変形ネイティブ形式(実験的・未検証)
  config.py                    # YAML設定ファイルの読み込み
  cli.py                       # コマンドラインエントリポイント
tests/                          # pytest一式(法令根拠の基準値検証を含む)
web/                            # Web版(ブラウザだけで動く)
  index.html                    # 画面
  engine.js                     # 斜線制限・天空率・日影の計算(Python版の移植)
  envelope.js                   # 最大ボリューム探索(Python版の移植)
  viewer.js                     # 3D描画(Python版の出力と共通)
  app.js                        # 画面とエンジンの接続
tools/build_web.py              # Web版を単一HTMLにまとめる
packaging/                      # PyInstallerのspecと起動スクリプト
docs/
  windows_setup.md              # Windows導入手順(A/B両方)
  web_app.md                    # Web版の使い方とPython版との一致検証
  3d_view.md                    # 3D確認の方法(ブラウザ/アイソメ図)
  disclaimer.md                # 免責事項・本ツールの限界
  legal_basis.md                # 各計算の法的根拠まとめ
  methodology.md                # 最大ボリューム探索アルゴリズムの解説
  jww_integration.md            # JW-CAD/JWWへの取り込み方法・書式調整
jww/                            # JWW外部変形として配布するファイル
  最大ボリューム計算.bat          # 外部変形メニューに登録するバッチ
  診断_データ確認.bat             # 書式確認用(図面は変更しない)
  gaihen_params.yaml            # 用途地域・道路幅員などの設定
build_windows.bat               # Windows用exeビルドスクリプト
examples/sample_site.yaml       # サンプル設定ファイル
```

## テスト

```bash
pip install -e ".[dev]"
pytest
```

すべての斜線制限・天空率・日影規制の計算式は、法令の基準値（例:
道路斜線1.25/1.5勾配、隣地斜線20m+1.25・31m+2.5、北側斜線5m/10m+1.25、
冬至の太陽高度等）に対するユニットテストで検証しています。

## JW-CAD/JWWとの連携について

推奨されるのはDXF読み込みです。外部変形メニューへの直接登録や、JWW
ネイティブのデータ交換形式については `docs/jww_integration.md` を参照して
ください（ネイティブ形式は実機のJWWで検証できていない実験的機能です）。

## 免責事項

`docs/disclaimer.md` および `docs/legal_basis.md` を必ず参照してください。
本ツールの計算結果は建築士等の専門家による確認・検証を経てから実務に
用いてください。
