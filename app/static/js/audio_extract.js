/**
 * AudioExtract — 동영상/m4a 에서 음성만 뽑아 mp3 로 만든다 (브라우저 안에서, ffmpeg.wasm).
 *
 * 왜 브라우저에서 하나:
 *   서버는 영상 파일을 받지 않는다. 그래야 약관의 "서버는 음원만 보관한다"가 사실이 된다.
 *   그래서 영상은 사용자 PC 자원으로 오디오만 추출해 전송한다.
 *
 * 왜 mp3 로 재인코딩하나 (스트림 복사가 아니라):
 *   서버 허용 형식이 mp3/ogg/wav/flac 뿐이다. mp4/m4a 컨테이너는 영상 트랙을 담을 수 있는데
 *   서버에 디먹서가 없어 '영상 없음'을 증명할 수 없어서 거부한다. 게다가 mp3 는 Safari 를
 *   포함한 모든 브라우저에서 재생된다 (Ogg 는 Safari 17 미만에서 안 된다).
 *
 * 왜 단일 스레드 코어인가:
 *   멀티스레드 코어는 SharedArrayBuffer → COOP/COEP 교차출처 격리가 필요한데,
 *   require-corp 를 켜면 유튜브 iframe·썸네일·눈누 웹폰트가 전부 차단된다.
 *
 * 자산이 배포되지 않았으면(32MB wasm 은 git 에 없다) available() 이 false 를 돌려주고
 * 호출부가 "음원 파일을 직접 올려주세요"로 축퇴시킨다.
 */
(function () {
    'use strict';

    var BASE = '/static/vendor/ffmpeg/';
    var CORE_WASM = BASE + 'ffmpeg-core.wasm';
    function abs(path) {
        return new URL(path, window.location.origin).href;
    }

    var availability = null;   // Promise<boolean> (한 번만 확인)
    var loadPromise = null;    // Promise<FFmpeg> (한 번만 로드)

    function loadScriptOnce(src) {
        return new Promise(function (resolve, reject) {
            var existing = document.querySelector('script[data-ffmpeg-src="' + src + '"]');
            if (existing) {
                if (existing.dataset.loaded === '1') return resolve();
                existing.addEventListener('load', function () { resolve(); });
                existing.addEventListener('error', function () { reject(new Error(src + ' 로드 실패')); });
                return;
            }
            var el = document.createElement('script');
            el.src = src;
            el.dataset.ffmpegSrc = src;
            el.onload = function () { el.dataset.loaded = '1'; resolve(); };
            el.onerror = function () { reject(new Error(src + ' 로드 실패')); };
            document.head.appendChild(el);
        });
    }

    /** 변환기 자산이 배포돼 있는지 (없으면 기능을 조용히 감춘다) */
    function available() {
        if (availability) return availability;
        availability = fetch(CORE_WASM, { method: 'HEAD' })
            .then(function (res) { return res.ok; })
            .catch(function () { return false; });
        return availability;
    }

    /** wasm 을 미리 받아 캐시에 올리면서 진행률을 보고한다 (ff.load 는 진행률을 안 준다) */
    function prewarm(onProgress) {
        return fetch(CORE_WASM).then(function (res) {
            if (!res.ok || !res.body) return;
            var total = parseInt(res.headers.get('content-length') || '0', 10);
            if (!total) return res.arrayBuffer().then(function () {});
            var reader = res.body.getReader();
            var got = 0;
            return (function pump() {
                return reader.read().then(function (r) {
                    if (r.done) return;
                    got += r.value.length;
                    if (onProgress) onProgress(got / total);
                    return pump();
                });
            })();
        }).catch(function () { /* 실패해도 ff.load 가 다시 받는다 */ });
    }

    function loadFfmpeg(onPhase, onProgress) {
        if (loadPromise) return loadPromise;
        loadPromise = Promise.resolve()
            .then(function () {
                onPhase('loading-ffmpeg', '음원 추출기를 준비하는 중… (최초 1회)');
                return prewarm(function (ratio) {
                    onPhase('loading-ffmpeg', '음원 추출기를 준비하는 중… ' + Math.round(ratio * 100) + '%');
                    if (onProgress) onProgress(ratio);
                });
            })
            .then(function () { return loadScriptOnce(BASE + 'ffmpeg.js'); })
            .then(function () {
                var ns = window.FFmpegWASM || window.FFmpeg;
                if (!ns || !ns.FFmpeg) throw new Error('변환기를 초기화할 수 없습니다.');
                return new ns.FFmpeg();
            })
            .catch(function (err) {
                loadPromise = null;   // 다음 시도에서 다시 받을 수 있게
                throw err;
            });
        return loadPromise;
    }

    function parseDurationMs(logText) {
        var m = /Duration:\s*(\d+):(\d+):(\d+)\.(\d+)/.exec(logText);
        if (!m) return null;
        return ((+m[1]) * 3600 + (+m[2]) * 60 + (+m[3])) * 1000 + (+m[4]) * 10;
    }

    /**
     * 입력 파일에서 오디오만 뽑아 mp3(192k) Blob 을 만든다.
     * @returns {Promise<{blob: Blob, durationMs: number|null}>}
     */
    function toMp3(file, opts) {
        opts = opts || {};
        var onPhase = opts.onPhase || function () {};
        var onProgress = opts.onProgress || function () {};

        var ff = null;
        var logs = [];
        var inName = 'input' + (/\.[a-z0-9]+$/i.test(file.name) ? file.name.match(/\.[a-z0-9]+$/i)[0] : '.bin');
        var outName = 'out.mp3';

        return loadFfmpeg(onPhase, onProgress)
            .then(function (instance) {
                ff = instance;
                ff.on('log', function (e) {
                    logs.push(e.message);
                    if (logs.length > 500) logs.shift();
                });
                ff.on('progress', function (e) {
                    if (typeof e.progress === 'number' && e.progress >= 0 && e.progress <= 1) {
                        onProgress(e.progress);
                        onPhase('extracting', '음원을 추출하는 중… ' + Math.round(e.progress * 100) + '%');
                    }
                });
                if (!ff.loaded) {
                    // classWorkerURL 을 넘기지 말 것.
                    //   UMD 빌드는 이 값이 있으면 워커를 {type:"module"} 로 만드는데,
                    //   워커 코드(814.ffmpeg.js)는 코어를 importScripts() 로 읽는다.
                    //   module 워커에서 importScripts 는 명세상 무조건 TypeError 라
                    //   변환이 100% 실패한다 (게다가 32MB 를 다 받은 뒤에).
                    //   생략하면 webpack publicPath(= 이 스크립트가 있는 디렉터리)에서
                    //   814.ffmpeg.js 를 classic 워커로 띄운다 — 그래서 그 파일이
                    //   ffmpeg.js 와 같은 디렉터리에 있어야 한다(scripts/fetch_ffmpeg.sh).
                    return ff.load({
                        coreURL: abs(BASE + 'ffmpeg-core.js'),
                        wasmURL: abs(CORE_WASM)
                    }).catch(function (e) {
                        // ff.load 는 Error 가 아니라 문자열로 거부한다 → err.message 가 undefined 가 되어
                        // 호출부가 원인을 못 보여준다. 여기서 Error 로 감싼다.
                        throw (e instanceof Error) ? e : new Error(String(e));
                    });
                }
            })
            .then(function () {
                onPhase('extracting', '음원을 추출하는 중…');
                return file.arrayBuffer();
            })
            .then(function (buf) {
                return ff.writeFile(inName, new Uint8Array(buf));
            })
            .then(function () {
                // -vn -sn -dn: 영상/자막/데이터 트랙 제거, -map 0:a:0: 첫 오디오 트랙만
                return ff.exec([
                    '-hide_banner', '-nostdin',
                    '-i', inName,
                    '-vn', '-sn', '-dn',
                    '-map', '0:a:0',
                    '-c:a', 'libmp3lame', '-b:a', '192k', '-ar', '44100', '-ac', '2',
                    outName
                ]);
            })
            .then(function (code) {
                if (code !== 0) {
                    var text = logs.join('\n');
                    if (/does not contain any stream|Stream map .* matches no streams/i.test(text)) {
                        throw new Error('이 파일에는 오디오 트랙이 없습니다.');
                    }
                    throw new Error('음원 추출에 실패했습니다.');
                }
                return ff.readFile(outName);
            })
            .then(function (data) {
                var blob = new Blob([data.buffer || data], { type: 'audio/mpeg' });
                var durationMs = parseDurationMs(logs.join('\n'));
                return { blob: blob, durationMs: durationMs };
            })
            .finally(function () {
                // 32MB wasm 힙 + 입출력 버퍼를 즉시 돌려준다
                // (유튜브 iframe 이 같이 떠 있는 탭이다)
                if (ff) {
                    try { ff.deleteFile(inName); } catch (e) {}
                    try { ff.deleteFile(outName); } catch (e) {}
                    try { ff.terminate(); } catch (e) {}
                    loadPromise = null;
                }
            });
    }

    window.AudioExtract = {
        available: available,
        toMp3: toMp3
    };
})();
