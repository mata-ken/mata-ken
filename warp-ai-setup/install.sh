#!/usr/bin/env bash
# Warp + Claude Code + Codex CLI を macOS にセットアップする。
# 何度実行しても安全（インストール済みのものはスキップ）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATES="$SCRIPT_DIR/templates"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

if [[ "$(uname)" != "Darwin" ]]; then
  warn "このスクリプトは macOS 向けです。"
  exit 1
fi

# 1. Homebrew
if ! command -v brew >/dev/null 2>&1; then
  info "Homebrew をインストールします"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

# 2. Warp
if [[ -d "/Applications/Warp.app" ]]; then
  info "Warp はインストール済み"
else
  info "Warp をインストールします"
  brew install --cask warp
fi

# 3. Claude Code（公式ネイティブインストーラー。自動アップデート対応）
if command -v claude >/dev/null 2>&1; then
  info "Claude Code はインストール済み: $(claude --version 2>/dev/null || true)"
else
  info "Claude Code をインストールします"
  curl -fsSL https://claude.ai/install.sh | bash
fi

# 4. Codex CLI
if command -v codex >/dev/null 2>&1; then
  info "Codex CLI はインストール済み: $(codex --version 2>/dev/null || true)"
else
  info "Codex CLI をインストールします"
  brew install --cask codex
fi

# 5. ~/.local/bin を PATH に（Claude Code のネイティブ版の配置先）
ZSHRC="$HOME/.zshrc"
if ! grep -q 'HOME/.local/bin' "$ZSHRC" 2>/dev/null; then
  info "~/.local/bin を PATH に追加します ($ZSHRC)"
  printf '\n# Claude Code\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$ZSHRC"
fi

# 6. 設定テンプレート（既存ファイルは上書きしない）
copy_if_absent() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [[ -e "$dst" ]]; then
    info "既存のためスキップ: $dst"
  else
    cp "$src" "$dst"
    info "作成: $dst"
  fi
}

copy_if_absent "$TEMPLATES/claude/settings.json" "$HOME/.claude/settings.json"
copy_if_absent "$TEMPLATES/claude/CLAUDE.md"     "$HOME/.claude/CLAUDE.md"
copy_if_absent "$TEMPLATES/codex/config.toml"    "$HOME/.codex/config.toml"
copy_if_absent "$TEMPLATES/codex/AGENTS.md"      "$HOME/.codex/AGENTS.md"
WARP_LC="$HOME/.warp/launch_configurations/ai-dev.yaml"
if [[ -e "$WARP_LC" ]]; then
  info "既存のためスキップ: $WARP_LC"
else
  mkdir -p "$(dirname "$WARP_LC")"
  sed "s#__HOME__#$HOME#g" "$TEMPLATES/warp/ai-dev.yaml" > "$WARP_LC"
  info "作成: $WARP_LC"
fi

cat <<'MSG'

セットアップ完了。次の手順:
  1. Warp を起動してログイン
  2. Warp で `claude` を実行 → ブラウザで Claude アカウントにログイン
  3. Claude Code 内で `/terminal-setup` を実行（Shift+Enter で改行できるように）
  4. Warp で `codex` を実行 → 「Sign in with ChatGPT」でログイン
  5. Warp のコマンドパレット (⌘P) → "Launch Configuration" → "AI Dev"
     で Claude Code と Codex を左右分割で起動
MSG
