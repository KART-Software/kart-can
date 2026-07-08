#!/usr/bin/env bash
# can.yaml から全成果物を再生成する。
#   ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
CANTOOLS=.venv/bin/cantools

if [ ! -x "$PY" ]; then
  echo "venv がありません。セットアップします..."
  uv venv --python 3.12 .venv
  uv pip install --python "$PY" cantools pyyaml
fi

echo "== 1) can.yaml -> generated/kart.dbc（+ 自己テスト）=="
"$PY" tools/gen.py

echo
echo "== 2) generated/kart.dbc -> generated/kart_can.h / kart_can.c（firmware用Cコード）=="
# --database-name で出力ファイル名とシンボル接頭辞を kart_can に (include <kart_can.h>)
"$CANTOOLS" generate_c_source generated/kart.dbc --database-name kart_can --output-directory generated

echo
echo "== 3) 確認: generated/kart.dbc をロードし直してメッセージ一覧 =="
"$CANTOOLS" list generated/kart.dbc

echo
echo "完了: generated/kart.dbc / kart_can.h / kart_can.c"
