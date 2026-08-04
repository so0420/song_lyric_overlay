/**
 * MediaPlayer — 유튜브 IFrame 플레이어와 <audio> 를 하나의 인터페이스로 감싼다.
 *
 * 설계 의도:
 *   노래하기 페이지(overlay.html)와 가사 편집기(lyric_editor.html)는 유튜브 IFrame API 를
 *   50곳 가까이 직접 호출한다. 그래서 파사드는 **YT 메서드 이름과 상태 코드를 그대로
 *   유지**한다 (playVideo / cueVideoById / getCurrentTime / seekTo ...,
 *   상태는 -1, 0, 1, 2, 3, 5). 덕분에 기존 호출부 대부분이 무수정으로 동작한다.
 *   새로 쓰는 코드는 아래쪽의 중립 별칭(load/play/pause/getTime/on)을 쓰면 된다.
 *
 * 중요한 불변식:
 *   - 유튜브 iframe 은 절대 파괴/재생성하지 않는다. 소스를 바꿔도 숨기고 일시정지만 한다.
 *     (overlay.html 의 PiP 모드가 iframe 재마운트를 못 견딘다)
 *   - <audio> 의 waiting 은 150ms 이상 지속될 때만 BUFFERING 으로 올린다. 그러지 않으면
 *     스크럽할 때마다 isPlaying=false 가 OBS 로 전송돼 오버레이가 덜컥거린다.
 */
(function () {
    'use strict';

    var State = {
        UNSTARTED: -1,
        ENDED: 0,
        PLAYING: 1,
        PAUSED: 2,
        BUFFERING: 3,
        CUED: 5
    };

    // waiting 이 이 시간 이상 이어질 때만 '버퍼링'으로 본다
    var BUFFER_DEBOUNCE_MS = 150;

    function createFacade(opts) {
        opts = opts || {};

        var ytHost = opts.ytHostId;
        var audioHostEl = opts.audioHostId ? document.getElementById(opts.audioHostId) : null;
        var audioEl = opts.audioElId ? document.getElementById(opts.audioElId) : null;

        var yt = null;              // YT.Player 인스턴스
        var ytReady = false;
        var ytApiArrived = false;
        var active = null;          // 'youtube' | 'audio'
        var current = null;         // 현재 소스 서술자
        var pending = null;         // 백엔드가 준비되기 전 요청된 소스
        var lastState = State.UNSTARTED;
        var volume = 100;
        var muted = false;
        var bufferTimer = null;
        var facade;

        function emitState(code) {
            if (code === lastState) return;
            lastState = code;
            if (opts.onStateChange) {
                try { opts.onStateChange({ data: code, target: facade }); } catch (e) { console.error(e); }
            }
        }

        // -------------------------------------------------------------
        // YouTube 백엔드
        // -------------------------------------------------------------
        function buildYt() {
            if (yt || !ytHost || !window.YT || !window.YT.Player) return;
            if (!document.getElementById(ytHost)) return;
            yt = new YT.Player(ytHost, {
                height: '100%',
                width: '100%',
                playerVars: opts.ytPlayerVars || {
                    playsinline: 1, rel: 0, modestbranding: 1,
                    enablejsapi: 1, origin: window.location.origin
                },
                events: {
                    onReady: function () {
                        ytReady = true;
                        try { yt.setVolume(volume); } catch (e) {}
                        if (muted) { try { yt.mute(); } catch (e) {} }
                        drainPending();
                        if (opts.onReady) opts.onReady({ target: facade });
                    },
                    onStateChange: function (e) {
                        if (active === 'youtube') emitState(e.data);
                    }
                }
            });
        }

        // -------------------------------------------------------------
        // <audio> 백엔드
        // -------------------------------------------------------------
        function ensureAudio() {
            if (audioEl) return audioEl;
            if (!audioHostEl) return null;
            audioEl = document.createElement('audio');
            audioEl.id = (opts.audioElId || 'mediaPlayerAudio');
            audioEl.preload = opts.audioPreload || 'metadata';
            audioHostEl.appendChild(audioEl);
            return audioEl;
        }

        function clearBufferTimer() {
            if (bufferTimer) { clearTimeout(bufferTimer); bufferTimer = null; }
        }

        function bindAudio(el) {
            if (!el || el.__mpBound) return;
            el.__mpBound = true;

            el.addEventListener('playing', function () {
                if (active !== 'audio') return;
                clearBufferTimer();
                emitState(State.PLAYING);
            });
            el.addEventListener('play', function () {
                if (active !== 'audio') return;
                clearBufferTimer();
            });
            el.addEventListener('pause', function () {
                if (active !== 'audio') return;
                clearBufferTimer();
                if (!el.ended) emitState(State.PAUSED);
            });
            el.addEventListener('ended', function () {
                if (active !== 'audio') return;
                clearBufferTimer();
                emitState(State.ENDED);
            });
            el.addEventListener('loadedmetadata', function () {
                if (active !== 'audio') return;
                if (el.paused) emitState(State.CUED);
                if (opts.onDurationChange) opts.onDurationChange(el.duration);
            });
            el.addEventListener('waiting', function () {
                if (active !== 'audio') return;
                // 목표 지점이 이미 버퍼 안이면 곧 재개되므로 무시한다
                if (isBuffered(el, el.currentTime)) return;
                clearBufferTimer();
                bufferTimer = setTimeout(function () {
                    if (active === 'audio' && !el.paused) emitState(State.BUFFERING);
                }, BUFFER_DEBOUNCE_MS);
            });
            el.addEventListener('error', function () {
                if (active !== 'audio') return;
                clearBufferTimer();
                emitState(State.PAUSED);
                if (opts.onError) opts.onError(el.error, current);
            });
        }

        function isBuffered(el, time) {
            try {
                for (var i = 0; i < el.buffered.length; i++) {
                    if (time >= el.buffered.start(i) && time <= el.buffered.end(i)) return true;
                }
            } catch (e) {}
            return false;
        }

        // -------------------------------------------------------------
        // 소스 전환
        // -------------------------------------------------------------
        function showHost(kind) {
            var ytEl = ytHost ? document.getElementById(ytHost) : null;
            if (ytEl) ytEl.style.display = (kind === 'youtube') ? '' : 'none';
            if (audioHostEl) audioHostEl.style.display = (kind === 'audio') ? '' : 'none';
        }

        function drainPending() {
            if (!pending) return;
            var src = pending;
            pending = null;
            applySource(src.source, src.autoplay);
        }

        function applySource(source, autoplay) {
            if (!source) return;

            if (source.type === 'audio') {
                var el = ensureAudio();
                if (!el) { pending = { source: source, autoplay: autoplay }; return; }
                bindAudio(el);
                // 유튜브는 멈추기만 하고 절대 파괴하지 않는다 (PiP 가 iframe 재마운트를 못 견딘다)
                if (yt && ytReady) { try { yt.pauseVideo(); } catch (e) {} }
                active = 'audio';
                current = source;
                showHost('audio');
                lastState = State.UNSTARTED;
                el.src = source.url;
                el.volume = Math.max(0, Math.min(100, volume)) / 100;
                el.muted = muted;
                el.load();
                if (autoplay) safePlay(el);
                return;
            }

            // youtube
            if (!yt || !ytReady) { pending = { source: source, autoplay: autoplay }; buildYt(); return; }
            if (audioEl) { try { audioEl.pause(); } catch (e) {} }
            active = 'youtube';
            current = source;
            showHost('youtube');
            lastState = State.UNSTARTED;
            if (autoplay) yt.loadVideoById(source.videoId);
            else yt.cueVideoById(source.videoId);
        }

        function safePlay(el) {
            var p = el.play();
            if (p && typeof p.catch === 'function') {
                p.catch(function (err) {
                    // 사용자 제스처 없이 재생하려 한 경우 — 조용히 실패하지 않게 알린다
                    emitState(State.PAUSED);
                    if (opts.onAutoplayBlocked) opts.onAutoplayBlocked(err);
                });
            }
        }

        function audioActive() {
            return active === 'audio' && audioEl;
        }

        function ytActive() {
            return active === 'youtube' && yt && ytReady;
        }

        // -------------------------------------------------------------
        // 공개 인터페이스 (YT 호환 이름)
        // -------------------------------------------------------------
        facade = {
            // --- 로딩 ---
            cueVideoById: function (videoId) { applySource({ type: 'youtube', videoId: videoId }, false); },
            loadVideoById: function (videoId) { applySource({ type: 'youtube', videoId: videoId }, true); },
            load: function (source) { applySource(source, false); },
            loadAndPlay: function (source) { applySource(source, true); },

            // --- 재생 제어 ---
            playVideo: function () {
                if (audioActive()) return safePlay(audioEl);
                if (ytActive()) yt.playVideo();
            },
            pauseVideo: function () {
                if (audioActive()) return audioEl.pause();
                if (ytActive()) yt.pauseVideo();
            },
            stopVideo: function () {
                if (audioActive()) { audioEl.pause(); try { audioEl.currentTime = 0; } catch (e) {} return; }
                if (ytActive()) yt.stopVideo();
            },
            seekTo: function (seconds, allowSeekAhead) {
                if (audioActive()) {
                    try { audioEl.currentTime = seconds; } catch (e) {}
                    return;
                }
                if (ytActive()) yt.seekTo(seconds, allowSeekAhead !== false);
            },

            // --- 시간 ---
            getCurrentTime: function () {
                if (audioActive()) return audioEl.currentTime || 0;
                if (ytActive() && yt.getCurrentTime) return yt.getCurrentTime() || 0;
                return 0;
            },
            getDuration: function () {
                if (audioActive()) {
                    var d = audioEl.duration;
                    if (isFinite(d) && d > 0) return d;
                    // VBR mp3 등 메타데이터가 부실할 때는 업로드 시 받은 길이로 대체
                    return current && current.durationMs ? current.durationMs / 1000 : 0;
                }
                if (ytActive() && yt.getDuration) return yt.getDuration() || 0;
                return 0;
            },

            // --- 볼륨 ---
            setVolume: function (v) {
                volume = Math.max(0, Math.min(100, v));
                if (audioEl) audioEl.volume = volume / 100;
                if (yt && ytReady) { try { yt.setVolume(volume); } catch (e) {} }
            },
            getVolume: function () { return volume; },
            mute: function () {
                muted = true;
                if (audioEl) audioEl.muted = true;
                if (yt && ytReady) { try { yt.mute(); } catch (e) {} }
            },
            unMute: function () {
                muted = false;
                if (audioEl) audioEl.muted = false;
                if (yt && ytReady) { try { yt.unMute(); } catch (e) {} }
            },
            isMuted: function () { return muted; },

            // --- 상태 ---
            getPlayerState: function () {
                if (audioActive()) return lastState;
                if (ytActive() && yt.getPlayerState) return yt.getPlayerState();
                return State.UNSTARTED;
            },

            // --- 파사드 고유 ---
            get isReady() {
                // 음원 백엔드는 유튜브 스크립트와 무관하게 항상 쓸 수 있다.
                // (이 값이 유튜브 전용이면 음원만 쓰는 사용자에게 OBS 동기화가 조용히 죽는다)
                return ytReady || !!audioHostEl || !!audioEl;
            },
            get activeType() { return active; },
            currentSource: function () { return current; },
            hasSource: function () { return !!(current || pending); },
            clearSource: function () {
                current = null;
                pending = null;
                if (audioEl) { try { audioEl.pause(); audioEl.removeAttribute('src'); audioEl.load(); } catch (e) {} }
                if (ytActive()) { try { yt.stopVideo(); } catch (e) {} }
                active = null;
                lastState = State.UNSTARTED;
            },
            setAudioPreload: function (mode) { if (audioEl) audioEl.preload = mode; },
            audioElement: function () { return audioEl; },
            ytPlayer: function () { return yt; },

            /** 유튜브 IFrame API 스크립트가 도착했을 때 호출 (페이지의 onYouTubeIframeAPIReady) */
            notifyYouTubeApiReady: function () {
                ytApiArrived = true;
                buildYt();
            },
            isYouTubeApiReady: function () { return ytApiArrived; }
        };

        // 중립 별칭 — 새로 쓰는 코드용
        facade.play = facade.playVideo;
        facade.pause = facade.pauseVideo;
        facade.stop = facade.stopVideo;
        facade.getTime = facade.getCurrentTime;

        // 페이지보다 유튜브 스크립트가 먼저 도착해 있을 수 있다
        if (window.YT && window.YT.Player) {
            ytApiArrived = true;
            buildYt();
        }
        if (audioEl) bindAudio(audioEl);
        if (audioHostEl) audioHostEl.style.display = 'none';

        return facade;
    }

    window.MediaPlayer = {
        State: State,
        create: createFacade
    };
})();
