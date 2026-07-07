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

echo "== 1) can.yaml -> kart.dbc（+ 自己テスト）=="
"$PY" gen.py

echo
echo "== 2) kart.dbc -> kart.h / kart.c（firmware用Cコード）=="
"$CANTOOLS" generate_c_source kart.dbc

echo
echo "== 3) 確認: kart.dbc をロードし直してメッセージ一覧 =="
"$CANTOOLS" list kart.dbc

echo
echo "完了: kart.dbc / kart.h / kart.c"
