#!/usr/bin/env bash
# ワンライナー用エントリーポイント。
#   旧PC: curl -fsSL https://raw.githubusercontent.com/mata-ken/mata-ken/main/warp-ai-setup/bootstrap.sh | bash -s -- export
#   新PC: curl -fsSL https://raw.githubusercontent.com/mata-ken/mata-ken/main/warp-ai-setup/bootstrap.sh | bash
set -euo pipefail

# curl | bash で実行されるため、全体を関数にして最後に呼ぶ（途中までのダウンロードで実行されない）
main() {
  local mode="${1:-setup}"
  local ref="${WARP_AI_SETUP_REF:-main}"
  local work dir
  work="$(mktemp -d)"
  trap "rm -rf '$work'" EXIT

  curl -fsSL "https://github.com/mata-ken/mata-ken/archive/refs/heads/$ref.tar.gz" | tar -xz -C "$work"
  dir="$(echo "$work"/*/warp-ai-setup)"

  # 子スクリプトの入力はパイプではなく端末から（sudo パスワード入力などのため）
  local tty=/dev/null
  if [[ -r /dev/tty ]] && (: < /dev/tty) 2>/dev/null; then tty=/dev/tty; fi

  case "$mode" in
    export)
      bash "$dir/export-from-old-pc.sh" < "$tty"
      ;;
    setup)
      # 旧PCの設定を先に展開 → 足りないものだけインストール（既存設定は上書きしない）
      bash "$dir/import-to-new-pc.sh" < "$tty"
      bash "$dir/install.sh" < "$tty"
      open -a Warp 2>/dev/null || true
      ;;
    *)
      echo "使い方: bootstrap.sh [setup|export]"; exit 1 ;;
  esac
}

main "$@"
