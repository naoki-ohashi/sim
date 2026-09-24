---
summary: リポジトリを Obsidian で開いて md を読む・書く・受信箱を片付けるまでの手順を短くまとめた説明書。運用ルールの本体は knowledge_base.md。
status: stable
owner: 大橋
updated: 2026-09-24
---

# Obsidian 連携の簡単な説明書

> このリポジトリの `docs/` を Obsidian で読み書きするための手順です。
> **正本は Git にある md**、Obsidian は「見る・直す・リンクを確かめる」道具です。
> 置き場所や統合のルールは [文書の整理・統合ルール](knowledge_base.md) にあります。

## 1. 最初の 1 回だけ（10 分）

1. **Obsidian を入れる**: <https://obsidian.md/> からダウンロードしてインストール。
2. **リポジトリを手元に置く**: GitHub Desktop か `git clone` で `naoki-ohashi/sim` を
   取得する（例: `C:\work\sim`）。
3. **vault として開く**: Obsidian の起動画面で「フォルダを保管庫として開く」
   （Open folder as vault）を選び、**リポジトリのルート**（`sim` フォルダ）を指定する。
   - `docs/` だけを開かない。`AGENTS.md` や `db/siteinfo/schema.sql` へのリンクが切れる。
4. **設定は何もしなくてよい**: リンク形式・添付フォルダ・検索除外は、コミット済みの
   `.obsidian/app.json` で設定済み。
   - Markdown リンク（`[[ ]]` ではない）・相対パス
   - 画像は同じフォルダの `assets/` に保存
   - `mve/`、`web/`、`tests/`、`db/` などコードのフォルダは検索・一覧に出ない

## 2. 読む

- 入口は **`docs/INDEX.md`**（全文書の索引）。左のファイル一覧から開く。
  よく使うなら右クリック →「ブックマーク」に入れておく。
- 各文書の先頭にある `summary` / `status` / `owner` / `updated` は、
  Obsidian では「プロパティ」として表示される。
- 右上の「リンク」パネル（バックリンク）で、その文書を参照している文書が分かる。
- グラフビュー（左のリボン）で文書どうしのつながりを眺められる。

## 3. 書く・直す

| やりたいこと | 操作 |
|---|---|
| 別の文書へのリンク | `[` と打つか、ファイルを本文へドラッグ → `[項目定義書](siteinfo_field_definitions.md)` の形になる |
| 見出しへのリンク | `[DB 設計 §4](siteinfo_db_design.md#4-主要な設計判断)` |
| 画像を貼る | 画像を本文へドラッグ → `assets/` に保存される |
| 文書を改名・移動 | Obsidian 上で行う（リンクが自動で書き換わる）。エクスプローラーでは動かさない |

守ること（詳しくは [knowledge_base.md §2](knowledge_base.md#2-ファイルの書き方3-ツール共通)）:

- 新しい md には frontmatter（`summary` / `status` / `owner` / `updated`）を付ける。
- `[[wikilink]]` は使わない（GitHub で表示されず、AI エージェントも辿れない）。
- 正本は 1 テーマ 1 ファイル。似た文書を増やさず、既存の文書に節を足す。

## 4. AI が書いた md を片付ける（受信箱）

Codex・Claude Code・Gemini・ChatGPT が書いた md は `docs/inbox/<tool>/` に届きます。

1. `docs/inbox/` を開いて中身を読む（Dataview を入れていれば一覧で見られる。§6）。
2. 採用する部分を正本（`docs/worldsim/` など）の該当節へ移す。
   自分でやっても、エージェントに頼んでもよい
   （依頼文は [siteinfo_agent_prompts.md](siteinfo_agent_prompts.md)）。
3. 元ファイルは `docs/archive/` へ移し、`status: archived` にする。
4. §5 のとおり索引を作り直してコミットする。

流れの図と細かい決まりは [knowledge_base.md §3](knowledge_base.md#3-ai-が書いた-md-を統合する流れ)。

## 5. 保存・同期（Git）

同期は **Git だけ** で行います（Obsidian Sync や OneDrive 共有は使わない）。

1. 作業の前に最新を取る（GitHub Desktop の「Fetch / Pull」か `git pull`）。
2. 文書を追加・削除・改名したら、索引を作り直す。

   ```bash
   python3 tools/build_docs_index.py          # docs/INDEX.md を更新し、リンク切れを表示
   python3 tools/build_docs_index.py --check  # 確認だけ（リンク切れ 0 ならOK）
   ```

3. コミットしてプッシュ（大きな変更はブランチを切って PR）。

`.obsidian/` のうちコミットするのは `app.json` だけです。
ワークスペースの状態などの個人設定は `.gitignore` で除外してあるので、気にせず使ってよい。

## 6. 入れると便利なプラグイン（任意）

設定 →「コミュニティプラグイン」→ 制限モードをオフ →「閲覧」から入れる。
無くても運用できます。

- **Dataview**: 受信箱の一覧を表にする。任意の md に次を書くと表示される。

  ````markdown
  ```dataview
  TABLE summary, updated FROM "docs/inbox" WHERE status = "inbox" SORT updated DESC
  ```
  ````

- **Git**: Obsidian の中から pull・コミット・プッシュできる。
  GitHub Desktop を使うなら不要。

## 7. 困ったとき

| 症状 | 原因と対処 |
|---|---|
| リンクをクリックしても開かない・新しい空ファイルができる | vault を `docs/` で開いている → リポジトリのルートで開き直す |
| リンクが `[[...]]` になる | `.obsidian/app.json` が読まれていない → `git pull` 後に Obsidian を再起動 |
| `build_docs_index.py` がリンク切れを出す | 表示されたファイルと行のリンク先を直す（改名はエクスプローラーでなく Obsidian で） |
| `mve/` などのコードが検索に出てこない | 仕様（`app.json` で除外）。コードはエディタで開く |
| スマホで読みたい | GitHub のアプリ／サイトで md を読む。編集は PC で行う |
