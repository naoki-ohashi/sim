# SiteInfo 実装のエージェントへの渡し方（Codex／Claude Code）

[`siteinfo_implementation_guide.md`](siteinfo_implementation_guide.md) を
Codex と Claude Code のどちらにも同じように実装させるための手順と、
コピーして使う指示文です。

## 1. 共通の準備

- リポジトリ直下に `AGENTS.md`（Codex が読む）と `CLAUDE.md`（Claude Code が読む）
  を置いてある。内容は同じで、読むべき文書の順番と守るべき原則だけを書いている。
- 環境変数（PostGIS がある場合）:
  - `SITEINFO_DSN=postgresql://.../siteinfo`（アプリ用）
  - `SITEINFO_TEST_DSN=...`（テスト用。無ければ DB テストは skip）
  - `REINFOLIB_API_KEY=...`（任意。無ければ reinfolib アダプタは「無効」と報告）
- PostGIS が無い環境（Claude Code on the web など）では、
  `apt-get install postgresql-16-postgis-3` で入れてローカルに起動できる
  （`db/siteinfo/README.md`）。

## 2. マイルストーンごとの指示文

マイルストーンは指示書 10 章。**1 回の依頼で 1 マイルストーン**。
`<M1>` の部分を置き換えて使う。

### 2.1 最初の依頼（M1）

```
docs/worldsim/siteinfo_implementation_guide.md の M1 を実装してください。

先に次を順番に読んでください:
1. docs/worldsim/vision.md
2. docs/worldsim/siteinfo_requirements.md
3. docs/worldsim/siteinfo_field_definitions.md
4. docs/worldsim/siteinfo_db_design.md と db/siteinfo/schema.sql
5. docs/worldsim/siteinfo_implementation_guide.md（全体、特に 0 章と 10 章の M1）

守ること:
- 指示書 0 章の原則。特に「自動入力は補助、確定はユーザー」「推測で法令値を書かない」。
- 指示書 1 章のスタックと配置。別のライブラリや構成にしない。
- 既存の mve/ web/ jwcad_volume/ は変更しない。
- M1 の受け入れ条件をすべて満たしてから PR を作る。PR 本文に受け入れ条件の
  チェックリストを貼り、各項目をどう確認したか 1 行ずつ書く。
- pytest と ruff を通す。PostGIS が使えるなら db/siteinfo/smoke_test.sql も通す。
- 判断に迷ったら、推測で進めず docs/worldsim/siteinfo_field_definitions.md 13 節に
  未決事項として追記し、PR 本文で質問する。
```

### 2.2 続きの依頼（M2 以降）

```
docs/worldsim/siteinfo_implementation_guide.md の <M2> を実装してください。
前提と守ることは M1 のときと同じです（AGENTS.md / CLAUDE.md 参照）。
M1 で作ったコードの構成を変えないでください。変える必要があれば理由を PR 本文に書いてください。
受け入れ条件をすべて満たしてから PR を作ってください。
```

### 2.3 レビュー依頼

```
PR #<番号> を docs/worldsim/siteinfo_implementation_guide.md に照らしてレビューしてください。
確認する順番:
1. 0 章の原則に反していないか（自動値が確認済みを上書きしていないか、法令値の出典があるか）
2. 受け入れ条件が実際に満たされているか（テストが存在し、通るか）
3. API の入出力が 3 章の仕様と一致しているか
4. GeoJSON 出力に v0.1 のキーがすべてあるか
見つけた問題は重要度順に、ファイルと行を示して列挙してください。修正はしないでください。
```

## 3. ツールごとの違い

| 項目 | Codex | Claude Code |
|---|---|---|
| 読む設定ファイル | `AGENTS.md` | `CLAUDE.md` |
| PR の作り方 | Codex の UI で作成 | セッションが自動で draft PR を作る |
| DB テスト | サンドボックスに PostGIS が無いことが多い。`SITEINFO_TEST_DSN` 未設定で skip される単体テストで検証し、DB テストは PR 後に人が回す | web 版はコンテナに PostGIS を入れて実行できる |
| 実 API | 原則ネットワーク不可。fixture で検証 | 同じ。`SITEINFO_LIVE_TESTS=1` は人が手元で回す |
| 途中の質問 | PR 本文に書かせる | セッションの会話で聞かせてよい |

どちらも、**指示書に書いてないことを勝手に決めさせない**のが要点です。
決めてほしいことが出てきたら、指示書を直してから再依頼します。

## 4. 進捗の記録

マイルストーンが終わるたびに、指示書 10 章のチェックボックスを PR で更新する。
仕様を変えたときは、指示書と項目定義書と DB 設計を同じ PR で直す。
