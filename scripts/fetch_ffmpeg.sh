#!/usr/bin/env bash
# ffmpeg.wasm 자산 내려받기 (동영상/m4a → mp3 변환기)
#
# 왜 필요한가:
#   ffmpeg-core.wasm 이 31MB 라 git 에 넣지 않고 .gitignore 로 제외했다.
#   배포할 때 이 스크립트를 한 번 돌려 app/static/vendor/ffmpeg/ 를 채운다.
#   자산이 없으면 편집기가 HEAD 요청으로 감지해 '음원 파일을 직접 올려주세요'로
#   축퇴하므로 서비스가 깨지지는 않는다 (동영상 업로드만 막힌다).
#
# 사용법:
#   bash scripts/fetch_ffmpeg.sh
#
# 필요 도구: npm, tar, sha256sum

set -euo pipefail

FFMPEG_VER="0.12.15"   # @ffmpeg/ffmpeg
CORE_VER="0.12.10"     # @ffmpeg/core (단일 스레드. core-mt 는 COOP/COEP 가 필요해 쓰지 않는다)

# 무결성 검증용 (버전을 올릴 때 함께 갱신할 것)
CORE_WASM_SHA256="9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7"
CORE_JS_SHA256="b266ab5b952555881dd6310663986994a182acb2b7ff25cf10a25f7a37ac2b21"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO_ROOT/app/static/vendor/ffmpeg"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "받는 중: @ffmpeg/ffmpeg@$FFMPEG_VER, @ffmpeg/core@$CORE_VER"
cd "$WORK"
npm pack "@ffmpeg/ffmpeg@$FFMPEG_VER" "@ffmpeg/core@$CORE_VER" >/dev/null

tar xzf "ffmpeg-ffmpeg-$FFMPEG_VER.tgz"
mkdir -p "$DEST"
# ffmpeg.js 는 워커 청크(814.ffmpeg.js)를 같은 디렉터리에서 찾는다 — 함께 복사해야 한다
cp package/dist/umd/ffmpeg.js "$DEST/"
cp package/dist/umd/814.ffmpeg.js "$DEST/"
rm -rf package

tar xzf "ffmpeg-core-$CORE_VER.tgz"
cp package/dist/umd/ffmpeg-core.js "$DEST/"
cp package/dist/umd/ffmpeg-core.wasm "$DEST/"
rm -rf package

echo "무결성 확인 중…"
echo "$CORE_WASM_SHA256  $DEST/ffmpeg-core.wasm" | sha256sum -c -
echo "$CORE_JS_SHA256  $DEST/ffmpeg-core.js" | sha256sum -c -

cat > "$DEST/VERSIONS.txt" <<EOF
@ffmpeg/ffmpeg  $FFMPEG_VER   (dist/umd/ffmpeg.js, dist/umd/814.ffmpeg.js)
@ffmpeg/core    $CORE_VER   (dist/umd/ffmpeg-core.js, dist/umd/ffmpeg-core.wasm)

단일 스레드 코어를 쓴다. 멀티스레드(core-mt)는 SharedArrayBuffer 때문에
COOP/COEP 교차출처 격리가 필요한데, 그걸 켜면 유튜브 iframe·썸네일·눈누 웹폰트가
전부 차단된다 (song_lyric.py 의 CSP 주석 참고).

버전을 올릴 때는 워커 청크 파일명(814.ffmpeg.js — webpack chunk id)이 바뀌었는지
반드시 확인할 것:  tar tzf ffmpeg-ffmpeg-<ver>.tgz | grep umd
EOF

echo
echo "완료: $DEST"
ls -lh "$DEST"
