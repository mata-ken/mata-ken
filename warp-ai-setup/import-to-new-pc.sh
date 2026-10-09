#!/usr/bin/env bash
# 【新PCで実行】export-from-old-pc.sh で作った tar.gz をホームに展開する。
# 既存ファイルは ~/.ai-settings-backup-<日時>/ に退避してから上書きする。
set -euo pipefail

# 引数がなければ iCloud Drive / デスクトップ / ダウンロードから最新のバックアップを探す
ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" ]]; then
  ARCHIVE="$(ls -t \
    "$HOME/Library/Mobile Documents/com~apple~CloudDocs/ai-cli-settings/"ai-cli-settings-*.tar.gz \
    "$HOME/Desktop/"ai-cli-settings-*.tar.gz \
    "$HOME/Downloads/"ai-cli-settings-*.tar.gz 2>/dev/null | head -1 || true)"
fi
if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "旧PCのバックアップが見つかりませんでした（スキップ）。"
  exit 0
fi
echo "バックアップを使用: $ARCHIVE"
BACKUP="$HOME/.ai-settings-backup-$(date +%Y%m%d%H%M%S)"

while IFS= read -r path; do
  path="${path%/}"
  if [[ -e "$HOME/$path" && ! -d "$HOME/$path" ]]; then
    mkdir -p "$BACKUP/$(dirname "$path")"
    cp -p "$HOME/$path" "$BACKUP/$path"
  fi
done < <(tar -tzf "$ARCHIVE")

tar -xzf "$ARCHIVE" -C "$HOME"
echo "展開完了。上書き前のファイル: $BACKUP（存在した場合のみ）"
echo "Claude Code と Codex は各コマンドを起動して再ログインしてください。"
