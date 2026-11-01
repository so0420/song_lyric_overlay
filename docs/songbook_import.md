# 외부 노래책 → SongStudio Live 노래책 이관 절차

songstudio.live(외부 SongStudio)에 공개된 노래책을 보고, 우리 서비스의 특정 사용자
노래책(`streamers` / `streamer_songbooks`)에 같은 곡들을 등록하는 운영 절차.
지금까지 kone(꿍), nag, aru, ㅇㅇ(원본 귀털) 이관에 이 방식을 썼다. 최근 예시 스크립트: `temp/gwitul_import/`.

> 운영 DB에 직접 쓰는 작업이다. 반드시 **스냅샷 → 계획 파일 → 단일 트랜잭션 적용 → 검증**
> 순서로 하고, 계획(JSON)을 사람이 검토한 뒤에만 적용한다.

## 0. 작업 준비

- 작업 폴더: `temp/<대상>_import/` (예: `temp/gwitul_import/`). `temp/`는 커밋하지 않는다.
- 스크립트는 프로젝트 루트의 `.venv/bin/python`으로 실행한다(`app` 모듈 import).
- 공통 유틸(`norm`, `variants`, 가수 별칭 그룹 `artistvars`)은 이전 작업의
  `common.py` / `match.py`를 복사해 쓰고, 이번 원본에 나오는 가수 별칭을 추가한다.

### 대상 사용자·노래책 확인

```sql
SELECT id, name, email, is_active, overlay_approved
FROM users WHERE email = %s AND deleted_at IS NULL;

SELECT * FROM streamers WHERE user_id = %s;   -- 노래책 프로필
```

- `streamers` 행이 없으면 노래책을 만든다: `StreamerRepository.create_profile(user_id, slug)`.
  slug는 `app/api/v1/streamers.py`의 `_generate_unique_slug` 규칙(소문자/숫자/한글/`_`/`-`,
  2자 미만이면 `singer`, 중복이면 `-2`, `-3` …)을 따른다.
- `overlay_approved`가 0이면 공개 노래책에 노출되지 않으니 보고 시 알린다.

## 1. 원본 수집 (`fetch.py`)

원본 URL의 slug로 외부 공개 API를 호출한다. `/songbook/@slug`, `/songbook/platform/@slug`
형식 모두 같은 bundle API를 쓴다.

```
GET https://api.songstudio.live/api/v1/songbook/bundle?slug=<slug>
    → userId, songbookInfo.songCount
GET https://api.songstudio.live/api/v1/songbook/<userId>/songs?page=N&limit=100&sort=id&order=asc
GET https://api.songstudio.live/api/v1/songbook/<userId>/songs?page=1&limit=10000&sort=<id|title|createdAt>&order=asc
```

- 페이지 단위 수집 + 전체 요청을 **세 가지 정렬(id/title/createdAt)로 각각 받아 ID 집합이
  같은지** 확인한다. (nag 때 기본 정렬 페이지네이션에서 중복 ID가 나와 누락될 뻔했다.)
- `source.json`(id 정렬), `source-audit.json`(페이지별 개수, 고유 개수) 저장.
- 요청 사이 0.3초 정도 쉰다.

## 2. DB 스냅샷 (`snapshot.py`)

| 파일 | 내용 |
|---|---|
| `target.json` | 대상 user / streamer 행 |
| `before.json` | 대상 노래책의 현재 수록곡 |
| `catalogue.json` | `songs` + `artists.name` 전체 |
| `lyrics.json` | 대상 사용자가 **볼 수 있는** 가사(아래 조건) 중 본문이 비어 있지 않은 것 |
| `others.json` | 다른 노래책들의 수록곡(`song_id`, `custom_title`, `custom_artist`, `lyrics_id`) |

접근 가능한 가사 조건:

```sql
l.deleted_at IS NULL AND (
  l.visibility = 'public' OR l.owner_id = :uid OR
  (l.visibility = 'whitelist' AND EXISTS (
     SELECT 1 FROM lyrics_whitelist w WHERE w.lyrics_id = l.id AND w.user_id = :uid)))
```

## 3. 매칭 — 반드시 이 순서로

앞 단계에서 확정된 항목은 뒤 단계에서 다시 찾지 않는다. 각 단계는 스크립트가 후보를
뽑고, **사람(작업자)이 원본 제목·가수와 후보를 직접 비교해 확정**한다. 자동 결과를
그대로 쓰지 않는다.

### 1차: 가사가 있는 곡

- 가사 보유 곡(`lyrics.json`의 `song_id`)만 대상으로 제목 변형(`variants`: 괄호 안/밖,
  한국어 번역 제목 + 원제 분리, feat. 제거)과 가수 별칭으로 후보를 만든다.
- 원본은 일본 곡을 **한국어 번역 제목**으로 적는 경우가 많다(예: `사신 / 요네즈 켄시`).
  제목 매칭에서 빠진 것은 **가수별로 가사 보유 곡 전체를 펼쳐** 눈으로 대조한다.
- 가사 선택 순서: 공개 우선 → `is_verified` → `likes_count` (앱의
  `get_best_public_lyrics_id_for_song`과 같은 기준). 번안/키 변경 가사(예: “한국어버전”,
  “여자키”)는 원본이 그 버전을 가리킬 때만 고른다.
- 원본 제목이 애니/작품명인 경우도 있다(예: `위치 워치 / 요아소비` → OP `Watch me!`).
- 예외: **공개** 가사가 다른 사용자 소유 커스텀 곡에 달려 있으면 그 곡을 그대로 쓴다
  (가사 우선. 계정 파기 시에도 곡 행은 남는다 — `app/database/account_purge.py`).
  2·3단계에서는 타인 소유 커스텀 곡을 쓰지 않는다.

### 2차: 다른 사람 노래책에 있는 같은 곡

- `others.json`의 곡을 곡 원제목·가수 **및 그 노래책의 `custom_title`/`custom_artist`**까지
  합쳐 대조한다. 다른 스트리머가 이미 같은 표기로 등록해 둔 곡을 찾기 좋다.
- 찾으면 **같은 `song_id`를 그대로** 쓴다(새 곡을 만들지 않음).
- 다른 사용자가 소유한 커스텀 곡(`songs.owner_id`가 다른 사람, `song_external_id`가
  `custom_` + UUID)은 쓰지 않는다. iTunes 곡(`custom_it_<trackId>`)이나 원 카탈로그 곡만 재사용.
- 선택한 곡에 접근 가능한 가사가 있으면 함께 연결한다(앱의 자동 연결과 동일).

### 3차: iTunes 검색 (후보 100개까지 직접 검증)

- 검색 엔드포인트는 앱과 같은 `https://itunes.apple.com/search`(curl_cffi, `impersonate='chrome'`).
  앱의 `_search_sync`는 앨범명·발매일을 버리므로, 버전 비교를 위해 원본 응답 전체
  (`collectionName`, `releaseDate`, `trackTimeMillis`)를 저장하는 스크립트를 직접 쓰는 편이 낫다.
- **국가별 주의**:
  - `KR` 스토어는 한국어 검색어로 결과가 거의 안 나오고, `entity=song`을 붙이면 0건이 된다.
  - 한국 곡은 **`US` 스토어 + `entity=song` + 영문 가수명**(예: `Lee Jin Ah`, `Humming Urban Stereo`)이
    가장 잘 나온다. 단 US 스토어는 한국 곡을 영어 제목으로 표기하기도 한다(`또또또` → `Again and Again`).
  - 일본 곡은 `JP` 스토어 + 원어 제목/가수. 한국어 번역 제목은 원제로 바꿔 검색한다.
- 제목 유사도로 안 잡히면 해당 가수 쿼리 결과 100개를 **전부 펼쳐 직접** 대조한다.
  영어 제목 후보는 `lookup?id=…&country=KR`로 한글 원제를 확인한다(KR lookup은 정상 동작).
  번역 제목을 모르겠으면 수록 앨범을 `lookup?id=<collectionId>&entity=song&country=JP`로 펼친다.
- **rate limit**: 요청 사이 최소 3초 이상(지금까지 3.2초) 쉬고, 응답은 `search-*.json` /
  `extra-*.json`으로 저장해 재실행 시 다시 부르지 않는다. 403/429가 나면 길게 쉬었다 재개.
- 후보를 사람이 직접 비교해 고른다. 고를 때 확인할 것:
  - 가수 일치(원어/영문/한글 표기, 그룹·유닛·피처링 표기)
  - 버전: 라이브·Inst·MR·리믹스·Acoustic·Sped up·커버·가라오케 대신 **정규 음원**
  - 언어: 한국어 번안곡을 일본어 원곡으로, 또는 그 반대로 바꾸지 않는다.
  - Clean/Explicit 등은 원본 표기에 맞춘다.
- 이미 카탈로그에 같은 `custom_it_<trackId>`(또는 구형식 `custom_<trackId>`)가 있으면 그 곡을
  재사용, 없으면 새로 만든다
  (`artists`에 `custom_it_<artistId>` upsert → `songs`에 `custom_it_<trackId>` insert, 커버 = artwork).
- 신규 곡 표기: US 스토어에서 찾은 곡은 KR lookup 표기에 한글이 있으면 그 표기(기존 카탈로그
  관례, 예: `또또또 / 이진아`), JP 스토어에서 찾은 일본 곡은 원어 표기를 쓴다.
- 기존 곡 재사용이든 신규든, 접근 가능한 가사(같은 제목+가수 형제 곡 포함)가 있으면 연결한다.

### 4차: 커스텀 등록

- 위 세 단계에서 확정 못 한 곡만 `SongRepository.create_custom_song(title, artist, owner_id=<대상 uid>)`.
- 같은 사용자 소유로 같은 제목·가수의 커스텀 곡이 이미 있으면 재사용.
- 원본 표기가 불완전해 곡을 확정할 수 없는 경우도 추정 연결하지 말고 커스텀으로 둔다.

## 4. 계획 조립 (`assemble.py` → `plan.json`)

- 원본 항목마다 `method`(`existing_lyrics` / `songbook_existing` / `itunes_existing` /
  `itunes_new` / `custom_new`), `song_id`, `lyrics_id`, 근거를 기록한다.
- **노래책 표시명은 원본 표기 보존**: `custom_title` = 원본 제목, `custom_artist` = 원본 가수.
- 노래책은 사용자당 `song_id`가 유일하다. 원본에 같은 곡이 중복(표기만 다른 경우 포함)으로
  있으면 하나의 수록곡으로 합치고 보고서에 원본 ID 목록을 적는다. 원본 가수 표기가 틀렸지만
  같은 곡이 이미 목록에 있는 경우(예: `フォニイ / B코마치` = ツミキ `フォニイ`)도 합친다.
- 리믹스만 있고 정규 음원이 없는 곡은 리믹스로 연결하지 않고 커스텀으로 둔다.
- 미해결 0개, 원본 ID 전부가 계획에 포함되는지 assert.

## 5. 적용 (`import_final.py`) — 단일 트랜잭션

- `result.json`이 이미 있으면 재실행 금지(assert).
- 트랜잭션 안에서 `users` / `streamers` 행을 `FOR UPDATE`로 잡고, 현재 수록곡을
  `before-final.json`으로 백업.
- 가사 연결 전 접근 가능 조건을 다시 확인.
- `SongbookRepository(tx).add_song(streamer_pk, song_id, lyrics_id=…, custom_title=…, custom_artist=…)`.
- 이미 있는 수록곡은 덮어쓰지 않고(사용자가 수정한 메타데이터 보존) 가사만 비어 있으면 채운다.
- 커밋 직전 최종 수록곡 집합 = 목표 집합 ∪ 기존 집합인지 assert.

## 6. 검증·인덱싱 (`verify_final.py`)

- 새로 만든 카탈로그 곡(iTunes 신규, 커스텀)을 Meilisearch에 추가하고 task 성공까지 대기:
  문서 형태 `{id: song_external_id, title, singer: artist, image_url: cover_image_url, owner_id}`.
  (현재 호스트 실행 기준 `.env`의 `MEILISEARCH_HOST=http://localhost:8007`. Docker 전환 후에는
  Meilisearch 포트가 호스트에 게시되지 않으므로 웹 컨테이너 안에서 실행해야 한다.)
- DB 수록곡 수, 각 항목의 `song_id`/`lyrics_id`/`custom_title`/`custom_artist` 대조.
- 공개 API `GET http://127.0.0.1:8006/api/v1/songbook/<streamers.streamer_id>?limit=100&offset=N`
  전 페이지를 받아 항목 수와 `has_lyrics` 대조.
- `mapping.csv`(원본 ID ↔ 수록곡), `verification.json` 저장.

## 7. 보고 (`result.md`)

- 원본 URL, 원본/대상 ID, 원본 항목 수 → 최종 곡 수(중복 합침 내역)
- 단계별 개수: 기존 가사 / 다른 노래책 곡 / iTunes(기존·신규) / 커스텀
- 판단이 필요했던 버전 선택(라이브 대신 정규, 번안 여부 등), 커스텀으로 둔 곡과 이유
- 감사 자료 링크(mapping.csv, result.json, verification.json, before-final.json)
