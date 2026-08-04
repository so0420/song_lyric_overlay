/**
 * AudioUpload — 음원 파일 선택·검증·(필요 시)변환·업로드.
 *
 * 서버는 mp3 / ogg / wav / flac 만 받는다. 이 형식들은 구조적으로 영상 트랙을 담을 수 없어서
 * "서버는 음원만 받는다"가 사실이 된다. 그래서:
 *   - 위 4종은 그대로 올린다 (대부분의 경우 — ffmpeg 을 아예 건드리지 않는다)
 *   - m4a/aac 나 동영상은 브라우저에서 ffmpeg.wasm 으로 mp3 변환 후 올린다
 *     (audio_extract.js — 실제로 필요할 때만 지연 로드된다)
 *
 * 진행률에 fetch 가 아니라 XHR 을 쓰는 이유: fetch 에는 업로드 진행 이벤트가 없다.
 */
(function () {
    'use strict';

    // 서버가 그대로 받아주는 형식 (변환 불필요)
    var DIRECT_EXT = /\.(mp3|ogg|oga|opus|wav|flac)$/i;
    var DIRECT_MIME = /^audio\/(mpeg|mp3|ogg|opus|wav|x-wav|wave|flac|x-flac)$/i;

    // 브라우저 안에서만 다루는 입력 파일의 상한 (업로드 한도와 별개).
    // wasm 힙이 입력+출력을 함께 들고 있어야 하므로 보수적으로 시작한다.
    var MAX_INPUT_BYTES = 200 * 1024 * 1024;

    var busy = false;

    function isDirectlyUploadable(file) {
        return DIRECT_EXT.test(file.name || '') || DIRECT_MIME.test(file.type || '');
    }

    function csrfHeader() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta && meta.content ? { 'X-CSRF-Token': meta.content } : {};
    }

    function formatBytes(n) {
        if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB';
        return Math.round(n / 1024) + 'KB';
    }

    /** <audio> 메타데이터로 재생 길이(ms)를 재본다. 못 구하면 null. */
    function probeDuration(blob) {
        return new Promise(function (resolve) {
            var url = URL.createObjectURL(blob);
            var el = new Audio();
            var done = false;
            function finish(value) {
                if (done) return;
                done = true;
                URL.revokeObjectURL(url);
                resolve(value);
            }
            el.preload = 'metadata';
            el.onloadedmetadata = function () {
                // VBR mp3 등에서는 Infinity/NaN 이 나온다 — 그때는 서버에 보내지 않는다
                finish(isFinite(el.duration) && el.duration > 0 ? Math.round(el.duration * 1000) : null);
            };
            el.onerror = function () { finish(null); };
            setTimeout(function () { finish(null); }, 10000);
            el.src = url;
        });
    }

    /** 본문을 파일 바이트 그대로 보내는 업로드 (멀티파트 아님 — 서버 주석 참고) */
    function upload(blob, filename, durationMs, onProgress) {
        return new Promise(function (resolve, reject) {
            var qs = '?filename=' + encodeURIComponent(filename || '');
            if (durationMs) qs += '&duration_ms=' + durationMs;

            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/v1/audio' + qs);
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
     * @param {object} opts { maxUploadBytes, onPhase(phase, detail), onProgress(ratio) }
     * @returns {Promise<{id,url,mime_type,byte_size,duration_ms,original_filename}>}
     */
    function handleFile(file, opts) {
        opts = opts || {};
        var maxUpload = opts.maxUploadBytes || 50 * 1024 * 1024;
        var phase = opts.onPhase || function () {};
        var progress = opts.onProgress || function () {};

        if (busy) return Promise.reject(new Error('이미 업로드가 진행 중입니다.'));
        busy = true;

        return Promise.resolve()
            .then(function () {
                phase('validating', '파일을 확인하는 중…');
                if (!file) throw new Error('파일을 선택해 주세요.');
                if (file.size === 0) throw new Error('빈 파일은 올릴 수 없습니다.');
                if (file.size > MAX_INPUT_BYTES) {
                    throw new Error('파일이 너무 큽니다. (' + formatBytes(MAX_INPUT_BYTES) + ' 이하)');
                }

                if (isDirectlyUploadable(file)) {
                    if (file.size > maxUpload) {
                        throw new Error('음원 파일은 ' + formatBytes(maxUpload) + ' 를 넘을 수 없습니다.');
                    }
                    return { blob: file, name: file.name, durationMs: null };
                }

                // m4a / 동영상 등 — 브라우저에서 mp3 로 변환한다
                if (!window.AudioExtract) {
                    throw new Error('이 형식은 mp3 변환이 필요한데 변환기를 불러올 수 없습니다. mp3/ogg/wav/flac 파일을 올려주세요.');
                }
                return window.AudioExtract.available().then(function (ok) {
                    if (!ok) {
                        throw new Error('동영상·m4a 변환 기능을 사용할 수 없습니다. mp3/ogg/wav/flac 파일을 직접 올려주세요.');
                    }
                    return window.AudioExtract.toMp3(file, {
                        onPhase: phase,
                        onProgress: progress
                    }).then(function (result) {
                        if (result.blob.size > maxUpload) {
                            throw new Error('변환된 음원이 ' + formatBytes(maxUpload) + ' 를 넘습니다. 더 짧은 파일을 사용해 주세요.');
                        }
                        return {
                            blob: result.blob,
                            name: (file.name || 'audio').replace(/\.[^.]+$/, '') + '.mp3',
                            durationMs: result.durationMs || null
                        };
                    });
                });
            })
            .then(function (prepared) {
                if (prepared.durationMs) return prepared;
                return probeDuration(prepared.blob).then(function (ms) {
                    prepared.durationMs = ms;
                    return prepared;
                });
            })
            .then(function (prepared) {
                phase('uploading', '업로드 중…');
                progress(0);
                return upload(prepared.blob, prepared.name, prepared.durationMs, function (ratio) {
                    progress(ratio);
                    phase('uploading', '업로드 중 ' + Math.round(ratio * 100) + '%');
                });
            })
            .then(function (result) {
                phase('done', '완료');
                busy = false;
                return result;
            })
            .catch(function (err) {
                phase('error', err.message || '실패했습니다.');
                busy = false;
                throw err;
            });
    }

    window.AudioUpload = {
        handleFile: handleFile,
        upload: upload,
        probeDuration: probeDuration,
        isDirectlyUploadable: isDirectlyUploadable,
        isBusy: function () { return busy; },
        MAX_INPUT_BYTES: MAX_INPUT_BYTES
    };
})();
