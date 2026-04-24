#!/usr/bin/env bash
# Meilisearch에서 단일 문서(노래) 하나를 삭제한다.
# 사용법: ./delete_meilisearch_song.sh [document_id]
#   document_id 생략 시 기본값: custom_b6d42d59-0563-46f4-85c2-def19458c567
set -euo pipefail

DOC_ID="${1:-custom_b6d42d59-0563-46f4-85c2-def19458c567}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "[error] .env not found at $ENV_FILE" >&2
    exit 1
fi

read_env() {
    grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

HOST="$(read_env MEILISEARCH_HOST)"
KEY="$(read_env MEILISEARCH_API_KEY)"
INDEX="$(read_env MEILISEARCH_INDEX_NAME)"

if [ -z "$HOST" ] || [ -z "$KEY" ] || [ -z "$INDEX" ]; then
    echo "[error] MEILISEARCH_HOST / MEILISEARCH_API_KEY / MEILISEARCH_INDEX_NAME not set in .env" >&2
    exit 1
fi

HOST="${HOST%/}"
URL="$HOST/indexes/$INDEX/documents/$DOC_ID"

echo "[info] target: $URL"
echo

echo "[info] 현재 문서 조회:"
curl -sS -w "\nHTTP:%{http_code}\n" \
    -H "Authorization: Bearer $KEY" \
    "$URL"
echo

echo "[info] 문서 삭제 요청:"
curl -sS -X DELETE -w "\nHTTP:%{http_code}\n" \
    -H "Authorization: Bearer $KEY" \
    "$URL"
echo

echo "[info] 삭제 후 재조회(404면 삭제 성공):"
curl -sS -w "\nHTTP:%{http_code}\n" \
    -H "Authorization: Bearer $KEY" \
    "$URL"
echo
echo "[info] done."
