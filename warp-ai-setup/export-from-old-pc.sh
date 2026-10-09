#!/usr/bin/env bash
# 【旧PCで実行】Claude Code / Codex / Warp の設定をバックアップ用 tar.gz にまとめる。
# 認証情報（ログイントークン）は含めない。新PCでは再ログインしてください。
set -euo pipefail

# 保存先: iCloud Drive があればそこへ（同じ Apple ID の新PCに自動で同期される）
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
if [[ -d "$ICLOUD" ]]; then
  DEST_DIR="$ICLOUD/ai-cli-settings"
else
  DEST_DIR="$HOME/Desktop"
fi
mkdir -p "$DEST_DIR"
OUT="${1:-$DEST_DIR/ai-cli-settings-$(date +%Y%m%d%H%M%S).tar.gz}"
cd "$HOME"

ITEMS=()
add() { [[ -e "$1" ]] && ITEMS+=("$1") || true; }

# Claude Code: ユーザー設定・グローバル指示・カスタムコマンド/エージェント/スキル/フック
add .claude/settings.json
add .claude/CLAUDE.md
add .claude/commands
add .claude/agents
add .claude/skills
add .claude/hooks
add .claude/keybindings.json
add .claude/statusline.sh
# Codex CLI: 設定・グローバル指示・プロンプト
add .codex/config.toml
add .codex/AGENTS.md
add .codex/prompts
# Warp: テーマ・ワークフロー・起動構成・キーバインド
add .warp/themes
add .warp/workflows
add .warp/launch_configurations
add .warp/keybindings.yaml

if [[ ${#ITEMS[@]} -eq 0 ]]; then
  echo "書き出す設定が見つかりませんでした。"
  exit 1
fi

tar -czf "$OUT" "${ITEMS[@]}"
echo "書き出し完了: $OUT"
printf '  - %s\n' "${ITEMS[@]}"

# MCP サーバー（user スコープ）は ~/.claude.json に認証情報と一緒に入っているため、
# 一覧だけ控えておき、新PCで `claude mcp add` し直す。
if command -v claude >/dev/null 2>&1; then
  claude mcp list > "$DEST_DIR/claude-mcp-list.txt" 2>&1 || true
  echo "MCP サーバー一覧: $DEST_DIR/claude-mcp-list.txt"
fi
