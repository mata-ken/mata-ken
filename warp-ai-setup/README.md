# Warp + Claude Code + Codex セットアップ（macOS）

ターミナル **Warp** 上で **Claude Code** と **OpenAI Codex CLI** を使うための初期設定一式です。

```
warp-ai-setup/
├── bootstrap.sh             # ワンライナー入口（旧PC: export / 新PC: setup）
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

## 使い方（コピペ1行ずつ）

### ① 旧PC：設定をバックアップ

ターミナルで以下を実行。バックアップは **iCloud Drive の `ai-cli-settings/`** に保存され、同じ Apple ID の新PCに自動で同期されます（iCloud がなければデスクトップに保存）。

```bash
curl -fsSL https://raw.githubusercontent.com/mata-ken/mata-ken/main/warp-ai-setup/bootstrap.sh | bash -s -- export
```

### ② 新PC：インストール + 設定の復元

iCloud の同期が終わったら（Finder の iCloud Drive に `ai-cli-settings` が見えたら）実行:

```bash
curl -fsSL https://raw.githubusercontent.com/mata-ken/mata-ken/main/warp-ai-setup/bootstrap.sh | bash
```

これで以下がすべて自動で行われます:

1. 旧PCのバックアップを探して展開（なければスキップ＝新規セットアップ）
2. Homebrew / Warp / Claude Code / Codex CLI をインストール（入っていればスキップ）
3. 足りない設定ファイルをテンプレートから作成（既存の設定は上書きしない）
4. Warp を起動

### ③ ログイン（ここだけ手動・各1回）

Warp で `claude` と `codex` を実行し、ブラウザでログインするだけです（下の「インストール後の初回設定」参照）。

<details>
<summary>手動で実行する場合</summary>

```bash
git clone https://github.com/mata-ken/mata-ken.git
cd mata-ken/warp-ai-setup
./export-from-old-pc.sh        # 旧PC
./import-to-new-pc.sh          # 新PC（引数なしで iCloud/デスクトップ/ダウンロードから自動検索）
./install.sh                   # 新PC
```
</details>

### 引き継がれるもの / 引き継がれないもの

| ツール | 引き継ぐ | 引き継がない（手動） |
|---|---|---|
| Claude Code | `settings.json`, `CLAUDE.md`, `commands/`, `agents/`, `skills/`, `hooks/`, `keybindings.json` | ログイン情報 → `claude` で再ログイン / MCPサーバー → `claude-mcp-list.txt` を見て `claude mcp add` し直す |
| Codex | `config.toml`, `AGENTS.md`, `prompts/` | ログイン情報（`auth.json`）→ `codex` で再ログイン |
| Warp | テーマ, ワークフロー, 起動構成, `keybindings.yaml` | 一般設定 → Warp に同じアカウントでログインすると **Settings Sync** で同期（Settings → Account で有効化） |

プロジェクトごとの設定（各リポジトリ内の `CLAUDE.md`, `.claude/`, `AGENTS.md`）はリポジトリと一緒に移るので作業不要です。

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
