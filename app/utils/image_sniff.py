"""업로드된 프로필 사진의 실제 형식 판별 (매직바이트).

왜 클라이언트 신고값을 안 쓰나:
    app/utils/audio_sniff.py 와 같은 이유다. Content-Type 과 확장자는 클라이언트가
    정하는 값이라 아무 것도 보장하지 않는다. 여기서 판별한 값만 저장되고,
    이미지를 내려줄 때 그대로 Content-Type 으로 나간다
    (X-Content-Type-Options: nosniff 와 함께라야 안전하다).

왜 SVG 를 안 받나:
    SVG 는 스크립트를 품을 수 있는 문서다. 프로필 사진은 우리 도메인에서
    그대로 서빙되므로, SVG 를 허용하면 same-origin 스크립트 실행 통로가 된다.
    래스터 4종만 받는다.
"""
from typing import Optional

# mime -> 저장 시 붙일 확장자
ALLOWED_IMAGE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

# 판별에 필요한 앞부분 크기. WebP 는 'WEBP' 가 8바이트 뒤에 오므로 넉넉히 잡는다.
SNIFF_BYTES = 32


def detect_image_mime(head: bytes) -> Optional[str]:
    """파일 앞부분으로 실제 형식을 판별한다. 허용 목록에 없으면 None."""
    if len(head) < 12:
        return None

    # PNG 시그니처
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # JPEG: SOI + 첫 마커
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    # GIF
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    # WebP 는 RIFF 컨테이너다. RIFF 만 보고 통과시키면 WAV 도 들어오므로
    # 형식 태그까지 확인한다.
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"

    return None
