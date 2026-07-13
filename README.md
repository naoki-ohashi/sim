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
- JW-CAD/JWWへ読み込み可能なDXFファイル（平面・断面・サマリー付き）を出力

## インストール

```bash
pip install -e .
```

Python 3.9+、依存パッケージ: shapely, ezdxf, numpy, PyYAML（`pyproject.toml` 参照）。

## クイックスタート

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

## 構成

```
jwcad_volume/
  geometry.py                 # 敷地ポリゴン・エッジ別オフセット等の幾何ユーティリティ
  zoning.py                   # 用途地域・道路斜線の適用距離/勾配テーブル
  site.py                     # 敷地・境界線(Boundary)・用途地域パラメータのデータモデル
  massing.py                  # 建物ボリューム(Block=平面形状×高さ範囲の積層)
  solar.py                    # 太陽位置(高度・方位角)計算
  envelope.py                 # 最大ボリューム探索(compute_max_envelope)
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
    gaihen_text.py               # JWW外部変形ネイティブ形式(実験的・未検証)
  config.py                    # YAML設定ファイルの読み込み
  cli.py                       # コマンドラインエントリポイント
tests/                          # pytest一式(法令根拠の基準値検証を含む)
docs/
  disclaimer.md                # 免責事項・本ツールの限界
  legal_basis.md                # 各計算の法的根拠まとめ
  methodology.md                # 最大ボリューム探索アルゴリズムの解説
  jww_integration.md            # JW-CAD/JWWへの取り込み方法
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
