# Warp + Claude Code + Codex セットアップ（macOS）

ターミナル **Warp** 上で **Claude Code** と **OpenAI Codex CLI** を使うための初期設定一式です。

```
warp-ai-setup/
├── install.sh               # 新PC: Warp / Claude Code / Codex をインストール + 設定テンプレート配置
├── export-from-old-pc.sh    # 旧PC: 既存の設定を tar.gz に書き出す（認証情報は含めない）
├── import-to-new-pc.sh      # 新PC: 書き出した設定を展開する
└── templates/
    ├── claude/settings.json # ~/.claude/settings.json（権限設定）
    ├── claude/CLAUDE.md     # ~/.claude/CLAUDE.md（全プロジェクト共通の指示）
    ├── codex/config.toml    # ~/.codex/config.toml
    ├── codex/AGENTS.md      # ~/.codex/AGENTS.md（全プロジェクト共通の指示）
    └── warp/ai-dev.yaml     # Warp 起動構成（Claude | Codex の左右分割）
```

> ⚠️ このリポジトリは公開（プロフィール用）です。APIキーやトークンはコミットしないでください。

---

## A. 旧PCの設定を引き継ぐ場合（推奨）

**旧PC** で:

```bash
git clone https://github.com/mata-ken/mata-ken.git
cd mata-ken/warp-ai-setup
./export-from-old-pc.sh
# → ~/Desktop/ai-cli-settings-YYYYMMDD.tar.gz と claude-mcp-list.txt ができる
```

この2ファイルを AirDrop などで **新PC** に送り、新PCで:

```bash
git clone https://github.com/mata-ken/mata-ken.git
cd mata-ken/warp-ai-setup
./import-to-new-pc.sh ~/Downloads/ai-cli-settings-YYYYMMDD.tar.gz   # 先に旧設定を展開
./install.sh                                                         # 足りないものだけ入れる
```

`install.sh` は既存の設定ファイルを上書きしないので、旧PCの設定がそのまま優先されます。

### 引き継がれるもの / 引き継がれないもの

| ツール | 引き継ぐ | 引き継がない（手動） |
|---|---|---|
| Claude Code | `settings.json`, `CLAUDE.md`, `commands/`, `agents/`, `skills/`, `hooks/`, `keybindings.json` | ログイン情報 → `claude` で再ログイン / MCPサーバー → `claude-mcp-list.txt` を見て `claude mcp add` し直す |
| Codex | `config.toml`, `AGENTS.md`, `prompts/` | ログイン情報（`auth.json`）→ `codex` で再ログイン |
| Warp | テーマ, ワークフロー, 起動構成, `keybindings.yaml` | 一般設定 → Warp に同じアカウントでログインすると **Settings Sync** で同期（Settings → Account で有効化） |

プロジェクトごとの設定（各リポジトリ内の `CLAUDE.md`, `.claude/`, `AGENTS.md`）はリポジトリと一緒に移るので作業不要です。

## B. まっさらに始める場合

```bash
git clone https://github.com/mata-ken/mata-ken.git
cd mata-ken/warp-ai-setup
./install.sh
```

---

## インストール後の初回設定

1. **Warp** を起動してログイン（Settings Sync を使うなら旧PCと同じアカウント）
2. Warp で `claude` → ブラウザで Claude アカウントにログイン
3. Claude Code 内で `/terminal-setup` を実行（Shift+Enter で改行できるようにする）
4. Warp で `codex` → **Sign in with ChatGPT** でログイン
5. 動作確認:
   ```bash
   claude --version
   codex --version
   claude doctor
   ```

## Warp での使い方のコツ

- **左右分割で両方起動**: コマンドパレット `⌘P` → `Launch Configuration` → **AI Dev**
- 手動分割: `⌘D`（左右）/ `⌘⇧D`（上下）。片方で `claude`、もう片方で `codex`
- プロジェクトで使うときは、そのディレクトリに `cd` してから `claude` / `codex` を起動
- Warp 標準の AI 機能（Agent Mode）と区別するため、Claude Code / Codex は普通のコマンドとして起動すればOK

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `claude: command not found` | Warp を再起動、または `source ~/.zshrc`（`~/.local/bin` が PATH に必要） |
| `codex: command not found` | `brew install --cask codex`（または `npm install -g @openai/codex`） |
| Shift+Enter で改行できない | Claude Code で `/terminal-setup`、または `\` + Enter で改行 |
| 状態の診断 | `claude doctor` |
