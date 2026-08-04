"""업로드된 파일의 실제 음원 형식 판별 (매직바이트).

왜 클라이언트 신고값을 안 쓰나:
    Content-Type 과 확장자는 둘 다 클라이언트가 정하는 값이라 아무 것도 보장하지 않는다.
    여기서 판별한 값만 audio_files.mime_type 에 저장되고, 재생 시 그대로
    Content-Type 으로 나간다 (X-Content-Type-Options: nosniff 와 함께라야 안전하다).

왜 m4a/mp4/WebM 을 안 받나:
    이 컨테이너들은 영상 트랙을 담을 수 있는데 서버에는 디먹서가 없어서
    '영상이 없음'을 증명할 수 없다. 아래 4종은 구조적으로 영상을 담지 못하므로,
    "서버는 음원만 받는다"는 약관 문구가 계약이 아니라 사실이 된다.
    브라우저 쪽에서 m4a/동영상을 mp3 로 변환해 올린다 (app/static/js/audio_extract.js).
"""
from typing import Optional

# mime -> 저장 시 붙일 확장자
ALLOWED_AUDIO = {
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/flac": "flac",
}

# 판별에 필요한 앞부분 크기. Ogg 는 코덱 식별자가 28바이트 뒤에 오므로 넉넉히 잡는다.
SNIFF_BYTES = 512


def detect_audio_mime(head: bytes) -> Optional[str]:
    """파일 앞부분으로 실제 형식을 판별한다. 허용 목록에 없으면 None."""
    if len(head) < 4:
        return None

    # MP3: ID3v2 태그로 시작하거나, MPEG 프레임 싱크워드(11비트 1)로 시작
    if head[:3] == b"ID3":
        return "audio/mpeg"
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "audio/mpeg"

    # WAV: RIFF....WAVE
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"

    # FLAC (네이티브 스트림)
    if head[:4] == b"fLaC":
        return "audio/flac"

    # Ogg: 첫 페이지 안의 코덱 식별자까지 확인해야 한다.
    #      (OggS 만 보고 통과시키면 Ogg 로 감싼 Theora 영상도 들어올 수 있다)
    if head[:4] == b"OggS":
        first_page = head[:128]
        if b"OpusHead" in first_page or b"\x01vorbis" in first_page:
            return "audio/ogg"
        return None

    return None
