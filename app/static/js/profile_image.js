/**
 * ProfileImage — 프로필 사진 선택·정사각형 축소·업로드.
 *
 * 서버에는 이미지 라이브러리가 없다(Pillow 미사용). 그래서 리사이즈를 브라우저에서
 * 끝낸다: 가운데를 정사각형으로 잘라 512px JPEG 으로 다시 인코딩해 올린다.
 * 덕분에 디스크에 원본 해상도 사진이 쌓이지 않고, 아바타로 쓸 때 비율도 일정하다.
 *
 * 다만 서버는 이 전제를 믿지 않는다 — 크기 한도와 매직바이트를 다시 확인한다
 * (app/api/v1/users.py 의 upload_my_picture).
 *
 * 업로드에 fetch 가 아니라 XHR 을 쓰는 이유는 audio_upload.js 와 같다(진행률 이벤트).
 */
(function () {
    'use strict';

    // 저장할 정사각형 한 변의 픽셀. 노래책 카드(56px)·헤더 아바타의 2~3배수라
    // 고밀도 화면에서도 뭉개지지 않는다.
    var OUTPUT_SIZE = 512;
    var OUTPUT_QUALITY = 0.88;

    // 브라우저 안에서만 다루는 입력 파일의 상한 (서버 업로드 한도 5MB 와 별개).
    // 축소 전 원본이라 넉넉히 잡되, 디코딩으로 탭이 죽지 않을 정도로만 허용한다.
    var MAX_INPUT_BYTES = 20 * 1024 * 1024;

    function csrfHeader() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta && meta.content ? { 'X-CSRF-Token': meta.content } : {};
    }

    /** 파일을 <img> 로 디코딩한다. 형식이 아니거나 깨졌으면 거부. */
    function loadImage(file) {
        return new Promise(function (resolve, reject) {
            var url = URL.createObjectURL(file);
            var img = new Image();
            img.onload = function () {
                URL.revokeObjectURL(url);
                if (!img.naturalWidth || !img.naturalHeight) {
                    reject(new Error('이미지를 읽을 수 없습니다.'));
                    return;
                }
                resolve(img);
            };
            img.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error('이미지 파일이 아니거나 열 수 없는 형식입니다.'));
            };
            img.src = url;
        });
    }

    /** 가운데를 정사각형으로 잘라 OUTPUT_SIZE JPEG blob 으로 만든다. */
    function toSquareJpeg(img) {
        return new Promise(function (resolve, reject) {
            var side = Math.min(img.naturalWidth, img.naturalHeight);
            var sx = (img.naturalWidth - side) / 2;
            var sy = (img.naturalHeight - side) / 2;
            // 원본이 작으면 늘리지 않는다 (없는 화질을 만들어내지 않는다)
            var out = Math.min(OUTPUT_SIZE, side);

            var canvas = document.createElement('canvas');
            canvas.width = out;
            canvas.height = out;
            var ctx = canvas.getContext('2d');
            // 투명 PNG 를 JPEG 으로 굽으면 배경이 검게 나온다 — 흰색을 깔아둔다
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, out, out);
            ctx.drawImage(img, sx, sy, side, side, 0, 0, out, out);

            canvas.toBlob(function (blob) {
                if (blob) resolve(blob);
                else reject(new Error('이미지를 변환하지 못했습니다.'));
            }, 'image/jpeg', OUTPUT_QUALITY);
        });
    }

    /** 본문을 이미지 바이트 그대로 보내는 업로드 (멀티파트 아님 — 서버 주석 참고) */
    function upload(blob, onProgress) {
        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/v1/users/me/picture');
            var headers = csrfHeader();
            Object.keys(headers).forEach(function (k) { xhr.setRequestHeader(k, headers[k]); });
            xhr.setRequestHeader('Content-Type', 'application/octet-stream');

            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
            };
            xhr.onload = function () {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try { resolve(JSON.parse(xhr.responseText)); }
                    catch (e) { reject(new Error('서버 응답을 해석할 수 없습니다.')); }
                } else {
                    var msg = '업로드에 실패했습니다.';
                    try {
                        var body = JSON.parse(xhr.responseText);
                        if (typeof body.detail === 'string') msg = body.detail;
                        else if (body.detail && body.detail.message) msg = body.detail.message;
                    } catch (e) {}
                    reject(new Error(msg));
                }
            };
            xhr.onerror = function () { reject(new Error('네트워크 오류로 업로드하지 못했습니다.')); };
            xhr.send(blob);
        });
    }

    /**
     * 파일 하나를 처리해 업로드까지 끝낸다.
     * @param {File} file
     * @param {object} opts { onPhase(phase, detail), onProgress(ratio) }
     * @returns {Promise<{success: boolean, picture: string}>}
     */
    function handleFile(file, opts) {
        opts = opts || {};
        var phase = opts.onPhase || function () {};
        var progress = opts.onProgress || function () {};

        return Promise.resolve()
            .then(function () {
                if (!file) throw new Error('파일을 선택해 주세요.');
                if (file.size === 0) throw new Error('빈 파일은 올릴 수 없습니다.');
                if (file.size > MAX_INPUT_BYTES) {
                    throw new Error('사진이 너무 큽니다. (20MB 이하)');
                }
                phase('processing', '사진을 다듬는 중…');
                return loadImage(file);
            })
            .then(toSquareJpeg)
            .then(function (blob) {
                phase('uploading', '업로드하는 중…');
                return upload(blob, progress);
            })
            .then(function (result) {
                phase('done', '완료');
                return result;
            });
    }

    function remove() {
        return fetch('/api/v1/users/me/picture', {
            method: 'DELETE',
            headers: csrfHeader(),
            credentials: 'same-origin'
        }).then(function (res) {
            if (!res.ok) throw new Error('사진을 삭제하지 못했습니다.');
            return res.json();
        });
    }

    window.ProfileImage = {
        handleFile: handleFile,
        remove: remove,
        OUTPUT_SIZE: OUTPUT_SIZE
    };
})();
