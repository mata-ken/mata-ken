#!/bin/bash
# ダブルクリックで Logic プラグイン総点検を実行します。
cd "$(dirname "$0")" || exit 1

if ! /usr/bin/python3 -c 'import sys' >/dev/null 2>&1; then
  echo "Python 3 が見つかりません。"
  echo "このあと表示される「コマンドライン・デベロッパ・ツール」のインストールを完了してから、もう一度ダブルクリックしてください。"
  xcode-select --install
  read -r -n1 -p "何かキーを押すと閉じます"
  exit 1
fi

/usr/bin/python3 plugin_audit.py "$@"
echo
read -r -n1 -p "何かキーを押すとこのウィンドウを閉じます"
