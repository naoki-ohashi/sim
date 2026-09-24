---
title: 文書索引（Map of Content）
status: generated
---

# 文書索引（Map of Content）

> このファイルは `python3 tools/build_docs_index.py` が生成します。マーカーの間は手で編集しないでください。
> 運用ルールは [worldsim/knowledge_base.md](worldsim/knowledge_base.md)。

<!-- BEGIN GENERATED INDEX -->
## WorldSim / SiteInfo（構想・要件・設計・実装指示）

| 文書 | 内容 | 状態 |
|---|---|---|
| [文書の整理・統合ルール（Obsidian + AI エージェント）](worldsim/knowledge_base.md) | リポジトリを Obsidian の vault として開き、Codex・Claude Code・Gemini・ChatGPT が書いた md を受信箱から正本へ統合する運用ルール。 | stable |
| [Obsidian 連携の簡単な説明書](worldsim/obsidian_guide.md) | リポジトリを Obsidian で開いて md を読む・書く・受信箱を片付けるまでの手順を短くまとめた説明書。運用ルールの本体は knowledge_base.md。 | stable |
| [SiteInfo 実装のエージェントへの渡し方（Codex／Claude Code／Gemini）](worldsim/siteinfo_agent_prompts.md) | 実装指示書をエージェントに渡すときの依頼文のひな形（マイルストーン別）。 | stable |
| [SiteInfo データベース構造図・PostGIS テーブル設計 v0.2（草案）](worldsim/siteinfo_db_design.md) | SiteInfo の ER 図とテーブル一覧、provenance・法令行・分割ポリゴンなどの設計判断、MVE へのマッピング。DDL は db/siteinfo/schema.sql が正。 | draft |
| [SiteInfo 項目定義書 v0.2（草案）](worldsim/siteinfo_field_definitions.md) | SiteInfo の入力項目（グループ A〜K）、メタ属性、用途地域が 2 以上にまたがる場合の按分ルール、確定条件。 | draft |
| [SiteInfo 実装指示書 v0.2（Codex／Claude Code 共通）](worldsim/siteinfo_implementation_guide.md) | Codex／Claude Code／Gemini 向けの実装指示。API、GeoJSON 入出力、取得元ごとの自動入力アダプタ、マイルストーン M1〜M6。 | draft |
| [SiteInfo 入力要件ノート（大橋の指示）](worldsim/siteinfo_requirements.md) | SiteInfo の入力要件 3 点。重要事項説明書の法令制限を必須にする、日影規制の時間を入力できる、GIS 自動入力は補助でユーザーが最終確認。 | stable |
| [SiteInfo 入力・確認画面 設計書 v0.2（草案）](worldsim/siteinfo_ui_design.md) | SiteInfo の入力・確認画面。3 ステップ構成、項目行の標準、境界トレース UI、状態遷移、受け入れ条件。 | draft |
| [WorldSim 構想ノート（大橋の考え方）](worldsim/vision.md) | WorldSim 全体の考え方。正確性の層と表現の層を分ける原則、AI とツールの役割分担、Presentation Twin。 | stable |

## MVE（最大ボリューム計算）

| 文書 | 内容 | 状態 |
|---|---|---|
| [MVE — Maximum Volume Engine](mve/README.md) | 日影規制・斜線制限（天空率を含む）をチェックしながら、敷地に建てられる |  |
| [MVE 設計仕様書](mve/design_spec.md) | 敷地に建てられる最大容積を求める計算エンジン。 |  |
| [MVE の免責事項・位置づけ](mve/disclaimer.md) | MVE（Maximum Volume Engine）は、建築基準法の斜線制限・日影規制・容積率を |  |
| [MVE の法令根拠](mve/legal_basis.md) | 各計算がどの条文に基づいているかの対応表です。条文番号は実装時点の理解に |  |
| [MVE 取扱説明書](mve/manual.md) | 容積率をふまえて、敷地に建てられる最大容積を試算するツールです。 |  |
| [MVE の計算方法](mve/methodology.md) | 敷地図 → 壁面後退線 → 建物外郭線 → メッシュ → 各マスの階数を決める |  |
| [MVE Web版UI（ブラウザだけで使う）](mve/web_ui.md) | Pythonのインストールもコマンド入力も不要で、ブラウザだけで敷地条件を |  |

## MVE 以前の文書（JW-CAD 版など）

| 文書 | 内容 | 状態 |
|---|---|---|
| [3Dで確認する](3d_view.md) | 計算した最大ボリュームを立体で確認する方法が2つあります。用途が違うので |  |
| [免責事項・本ツールの位置づけ](disclaimer.md) | このツール（jwcad-volume）は、建築基準法における道路斜線制限・隣地斜線制限・ |  |
| [JW-CAD/JWWへの取り込み方法](jww_integration.md) | 導入手順そのものは windows_setup.md にまとめてあります。ここでは |  |
| [法令根拠まとめ](legal_basis.md) | 各モジュールが実装している計算の法的根拠。条文番号は本ツール実装時点の |  |
| [最大ボリューム探索アルゴリズムの考え方](methodology.md) | envelope.py の compute_max_envelope は次の順に計算します。 |  |
| [Web版（ブラウザだけで計算する）](web_app.md) | Pythonのインストールなしで、ブラウザだけで敷地条件を入力して最大ボリューム |  |
| [Windows導入手順](windows_setup.md) | 使い方は2通りあります。目的に応じて選んでください。 |  |

## 受信箱（AI が書いた未統合の md）

| 文書 | 内容 | 状態 |
|---|---|---|
| [受信箱（docs/inbox）](inbox/README.md) | AI エージェントや ChatGPT が書いた未統合の md を置く場所。レビュー後に正本へ統合し、元ファイルは archive へ。 | stable |

## 保管（統合済み・古い版）

| 文書 | 内容 | 状態 |
|---|---|---|
| [保管（docs/archive）](archive/README.md) | 統合済み・古い版の md の保管場所。参照はしない。 | stable |
<!-- END GENERATED INDEX -->
