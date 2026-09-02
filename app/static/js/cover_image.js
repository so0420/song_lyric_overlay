/**
 * CoverImage — 노래책 수록곡 커버 이미지의 선택·축소·업로드.
 *
 * 서버에는 이미지 라이브러리가 없다(Pillow 미사용). 그래서 리사이즈를 브라우저에서
 * 끝낸다: 가운데를 정사각형으로 잘라 640px JPEG 으로 다시 인코딩해 올린다.
 * 커버 자리는 어디서나 정사각형(object-fit: cover)으로 그려지므로 정사각형으로
 * 잘라도 보이는 게 달라지지 않고, 디스크에 원본 해상도 사진이 쌓이지 않는다.
 *
 * 다만 서버는 이 전제를 믿지 않는다 — 크기 한도와 매직바이트를 다시 확인한다
 * (app/api/v1/songbook.py 의 upload_entry_cover).
 *
 * 파일을 얻는 경로가 셋이라(파일 선택 / 드래그&드롭 / 붙여넣기) 어디서 왔든
 * File 하나로 좁힌 뒤 같은 절차를 타게 했다.
 *
 * 업로드에 fetch 가 아니라 XHR 을 쓰는 이유는 audio_upload.js 와 같다(진행률 이벤트).
 * (profile_image.js 와 하는 일이 비슷하지만, 출력 크기·업로드 대상·미리보기 흐름이
 *  달라 합치지 않았다)
 */
(function () {
    'use strict';

    // 저장할 정사각형 한 변의 픽셀. 노래책 카드(56px)·오버레이 커버(최대 ~200px)의
    // 3배수 이상이라 고밀도 화면에서도 뭉개지지 않는다.
    var OUTPUT_SIZE = 640;
    var OUTPUT_QUALITY = 0.86;

    // 브라우저 안에서만 다루는 입력 파일의 상한 (서버 업로드 한도 5MB 와 별개).
    // 축소 전 원본이라 넉넉히 잡되, 디코딩으로 탭이 죽지 않을 정도로만 허용한다.
    var MAX_INPUT_BYTES = 20 * 1024 * 1024;

    function csrfHeader() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta && meta.content ? { 'X-CSRF-Token': meta.content } : {};
    }

    /** DataTransfer / ClipboardData 에서 첫 이미지 파일을 꺼낸다. 없으면 null.
     *
     * files 와 items 를 둘 다 보는 이유: 브라우저·출처에 따라 한쪽만 채워진다
     * (윈도우 캡처 붙여넣기는 items 에만, 탐색기 드래그는 files 에 온다).
     */
    function pickImageFile(source) {
        if (!source) return null;

        var files = source.files;
        if (files && files.length) {
            for (var i = 0; i < files.length; i++) {
                if (files[i] && files[i].type && files[i].type.indexOf('image/') === 0) return files[i];
            }
        }

        var items = source.items;
        if (items && items.length) {
            for (var j = 0; j < items.length; j++) {
                var it = items[j];
                if (it && it.kind === 'file' && it.type && it.type.indexOf('image/') === 0) {
                    var f = it.getAsFile();
                    if (f) return f;
                }
            }
        }
        return null;
    }

    /** 드래그 중인 데이터가 파일인지 (파일이 아닐 때 드롭 UI 를 띄우지 않으려고) */
    function hasFiles(dataTransfer) {
        if (!dataTransfer) return false;
        var types = dataTransfer.types;
        if (!types) return false;
        for (var i = 0; i < types.length; i++) {
            if (types[i] === 'Files') return true;
        }
        return false;
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
            // 투명 PNG 를 JPEG 으로 구우면 배경이 검게 나온다 — 흰색을 깔아둔다
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, out, out);
            ctx.drawImage(img, sx, sy, side, side, 0, 0, out, out);

            canvas.toBlob(function (blob) {
                if (blob) resolve(blob);
                else reject(new Error('이미지를 변환하지 못했습니다.'));
            }, 'image/jpeg', OUTPUT_QUALITY);
        });
    }

    /**
     * 파일 하나를 업로드 가능한 형태로 다듬는다 (업로드는 하지 않는다).
     *
     * 곡 추가 흐름에서는 아직 수록곡 id 가 없어서 바로 올릴 수 없다 — 그래서
     * '다듬기'와 '올리기'를 나눠 두고, 저장 시점에 올린다.
     *
     * @param {File} file
     * @returns {Promise<{blob: Blob, previewUrl: string}>} previewUrl 은 호출자가
     *          다 쓰고 URL.revokeObjectURL 로 정리한다.
     */
    function prepare(file) {
        return Promise.resolve()
            .then(function () {
                if (!file) throw new Error('이미지를 선택해 주세요.');
                if (file.size === 0) throw new Error('빈 파일은 올릴 수 없습니다.');
                if (file.size > MAX_INPUT_BYTES) {
                    throw new Error('이미지가 너무 큽니다. (20MB 이하)');
                }
                return loadImage(file);
            })
            .then(toSquareJpeg)
            .then(function (blob) {
                return { blob: blob, previewUrl: URL.createObjectURL(blob) };
            });
    }

    /** 본문을 이미지 바이트 그대로 보내는 업로드 (멀티파트 아님 — 서버 주석 참고) */
    function upload(entryId, blob, onProgress) {
        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/v1/songbook/' + encodeURIComponent(entryId) + '/cover');
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
                    var msg = '커버 업로드에 실패했습니다.';
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

    function remove(entryId) {
        return fetch('/api/v1/songbook/' + encodeURIComponent(entryId) + '/cover', {
            method: 'DELETE',
            headers: csrfHeader(),
            credentials: 'same-origin'
        }).then(function (res) {
            if (!res.ok) throw new Error('커버를 삭제하지 못했습니다.');
            return res.json();
        });
    }

    window.CoverImage = {
        prepare: prepare,
        upload: upload,
        remove: remove,
        pickImageFile: pickImageFile,
        hasFiles: hasFiles,
        OUTPUT_SIZE: OUTPUT_SIZE
    };
})();
