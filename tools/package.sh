#!/bin/bash
# 제출 ZIP 만들기: bot/ 의 .py 와 submission.json 을 ZIP 최상위에 넣는다.
# usage: tools/package.sh [출력.zip]   (기본: dist/submission.zip)
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$ROOT/dist/submission.zip}
mkdir -p "$(dirname "$OUT")"
OUT=$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")
rm -f "$OUT"
(cd "$ROOT/bot" && zip -q -X "$OUT" submission.json *.py)
unzip -l "$OUT"
