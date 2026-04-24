/**
 * 가사 공개 범위 편집 패널 (관리자 전용).
 *
 * 사용:
 *   mountVisibilityPanel(document.getElementById('panel'), lyricsId, {
 *     onSaved: () => { ... },    // visibility 또는 whitelist 저장 성공 시 콜백
 *   });
 *
 * 필요한 엔드포인트 (require_admin):
 *   GET    /api/v1/admin/lyrics/{id}/visibility
 *   PATCH  /api/v1/admin/lyrics/{id}/visibility  body {visibility}
 *   PUT    /api/v1/admin/lyrics/{id}/whitelist   body {user_ids}
 *   GET    /api/v1/admin/users/search?q=...&limit=20
 */
(function () {
    'use strict';

    const VISIBILITY_OPTIONS = [
        { value: 'public', label: '전체 공개', hint: '모든 사용자가 볼 수 있습니다.' },
        { value: 'private', label: '비공개', hint: '본인과 관리자만 접근할 수 있습니다.' },
        { value: 'whitelist', label: '화이트리스트', hint: '본인, 관리자, 그리고 아래 허용된 사용자만 접근할 수 있습니다.' },
    ];

    const STYLE_ID = 've-styles-v1';

    function injectStyles() {
        if (document.getElementById(STYLE_ID)) return;
        const style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
.ve-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.ve-panel h3 { margin: 0 0 12px; font-size: 0.95rem; color: #1e293b; display: flex; align-items: center; gap: 6px; }
.ve-panel .ve-hint { font-size: 0.8rem; color: #64748b; margin: 0 0 12px; }
.ve-panel .ve-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.ve-panel select { padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; font-size: 0.9rem; flex: 1; }
.ve-panel .ve-save-btn { padding: 6px 12px; background: #3b82f6; color: #fff; border: none; border-radius: 6px; font-size: 0.85rem; cursor: pointer; white-space: nowrap; }
.ve-panel .ve-save-btn:disabled { background: #cbd5e1; cursor: not-allowed; }
.ve-whitelist-section { border-top: 1px solid #f1f5f9; padding-top: 12px; margin-top: 8px; }
.ve-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; min-height: 28px; }
.ve-chip { display: inline-flex; align-items: center; gap: 4px; background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 999px; font-size: 0.8rem; }
.ve-chip button { background: none; border: none; color: #0369a1; cursor: pointer; font-size: 1rem; line-height: 1; padding: 0; margin-left: 2px; }
.ve-chip button:hover { color: #e11d48; }
.ve-search-wrap { position: relative; }
.ve-search-input { width: 100%; padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.85rem; box-sizing: border-box; }
.ve-dropdown { position: absolute; top: 100%; left: 0; right: 0; background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-top: 4px; max-height: 220px; overflow-y: auto; z-index: 20; }
.ve-dropdown-item { padding: 8px 10px; cursor: pointer; font-size: 0.85rem; }
.ve-dropdown-item:hover, .ve-dropdown-item.active { background: #f1f5f9; }
.ve-dropdown-item .ve-name { font-weight: 500; color: #1e293b; }
.ve-dropdown-item .ve-email { color: #64748b; font-size: 0.75rem; }
.ve-dropdown-empty { padding: 10px; color: #94a3b8; font-size: 0.85rem; text-align: center; }
.ve-status { font-size: 0.8rem; margin-top: 4px; min-height: 1em; }
.ve-status.ok { color: #059669; }
.ve-status.err { color: #dc2626; }
.ve-badge { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; font-weight: 500; }
.ve-badge.public { background: #dcfce7; color: #166534; }
.ve-badge.private { background: #e2e8f0; color: #475569; }
.ve-badge.whitelist { background: #ffedd5; color: #9a3412; }
`;
        document.head.appendChild(style);
    }

    function getCsrfHeaders() {
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['X-CSRF-Token'] = token;
        return headers;
    }

    function escapeHtml(s) {
        if (s == null) return '';
        const d = document.createElement('div');
        d.textContent = String(s);
        return d.innerHTML;
    }

    function debounce(fn, ms) {
        let t;
        return (...args) => {
            clearTimeout(t);
            t = setTimeout(() => fn(...args), ms);
        };
    }

    async function apiGet(url) {
        const res = await fetch(url, { credentials: 'same-origin' });
        if (!res.ok) throw new Error(`GET ${url} failed: ${res.status}`);
        return res.json();
    }

    async function apiPatch(url, body) {
        const res = await fetch(url, {
            method: 'PATCH',
            headers: getCsrfHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `PATCH ${url} failed: ${res.status}`);
        }
        return res.json();
    }

    async function apiPut(url, body) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: getCsrfHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `PUT ${url} failed: ${res.status}`);
        }
        return res.json();
    }

    function renderBadge(visibility, count) {
        const opt = VISIBILITY_OPTIONS.find(o => o.value === visibility) || VISIBILITY_OPTIONS[0];
        const label = visibility === 'whitelist' && count != null
            ? `${opt.label} (${count}명)`
            : opt.label;
        return `<span class="ve-badge ${visibility}">${escapeHtml(label)}</span>`;
    }

    async function mountVisibilityPanel(container, lyricsId, opts) {
        opts = opts || {};
        injectStyles();
        container.innerHTML = '<div class="ve-panel"><p class="ve-hint">공개 범위 불러오는 중...</p></div>';

        let state;
        try {
            state = await apiGet(`/api/v1/admin/lyrics/${lyricsId}/visibility`);
        } catch (e) {
            container.innerHTML = `<div class="ve-panel"><p class="ve-status err">${escapeHtml(e.message)}</p></div>`;
            return;
        }

        render();

        function render() {
            const visibility = state.visibility;
            const whitelist = state.whitelist || [];
            const showWhitelistSection = visibility === 'whitelist';

            container.innerHTML = `
                <div class="ve-panel">
                    <h3>공개 범위 ${renderBadge(visibility, whitelist.length)}</h3>
                    <div class="ve-row">
                        <select class="ve-select">
                            ${VISIBILITY_OPTIONS.map(o => `
                                <option value="${o.value}" ${o.value === visibility ? 'selected' : ''}>${escapeHtml(o.label)}</option>
                            `).join('')}
                        </select>
                        <button class="ve-save-btn ve-save-visibility" disabled>저장</button>
                    </div>
                    <p class="ve-hint ve-vis-hint"></p>
                    <div class="ve-whitelist-section" style="${showWhitelistSection ? '' : 'display:none'}">
                        <h3 style="font-size:0.9rem;">허용된 사용자</h3>
                        <div class="ve-chips"></div>
                        <div class="ve-search-wrap">
                            <input type="text" class="ve-search-input" placeholder="이름 또는 이메일로 검색해서 추가...">
                            <div class="ve-dropdown" style="display:none"></div>
                        </div>
                        <div class="ve-row" style="margin-top:10px;">
                            <button class="ve-save-btn ve-save-whitelist" disabled>화이트리스트 저장</button>
                        </div>
                    </div>
                    <p class="ve-status"></p>
                </div>
            `;

            const select = container.querySelector('.ve-select');
            const btnVis = container.querySelector('.ve-save-visibility');
            const visHint = container.querySelector('.ve-vis-hint');
            const statusEl = container.querySelector('.ve-status');
            const whitelistSection = container.querySelector('.ve-whitelist-section');
            const chipsEl = container.querySelector('.ve-chips');
            const searchInput = container.querySelector('.ve-search-input');
            const dropdown = container.querySelector('.ve-dropdown');
            const btnWl = container.querySelector('.ve-save-whitelist');

            const updateVisHint = () => {
                const sel = VISIBILITY_OPTIONS.find(o => o.value === select.value);
                visHint.textContent = sel ? sel.hint : '';
            };
            updateVisHint();

            // 로컬 state (편집 중)
            let pendingWhitelist = whitelist.slice();
            const pendingIds = () => pendingWhitelist.map(u => u.id);
            const originalIds = whitelist.map(u => u.id).sort().join(',');

            const renderChips = () => {
                if (!pendingWhitelist.length) {
                    chipsEl.innerHTML = '<span class="ve-hint" style="margin:0;">아직 추가된 사용자가 없습니다.</span>';
                } else {
                    chipsEl.innerHTML = pendingWhitelist.map(u => `
                        <span class="ve-chip" data-uid="${u.id}">
                            <span>${escapeHtml(u.name || u.email)}</span>
                            <button type="button" title="제거" aria-label="제거">×</button>
                        </span>
                    `).join('');
                    chipsEl.querySelectorAll('.ve-chip button').forEach(btn => {
                        btn.addEventListener('click', (ev) => {
                            const chip = ev.currentTarget.closest('.ve-chip');
                            const uid = parseInt(chip.dataset.uid, 10);
                            pendingWhitelist = pendingWhitelist.filter(u => u.id !== uid);
                            renderChips();
                            updateWlBtn();
                        });
                    });
                }
            };

            const updateWlBtn = () => {
                const current = pendingIds().slice().sort().join(',');
                btnWl.disabled = current === originalIds;
            };

            renderChips();

            // visibility select 변경
            select.addEventListener('change', () => {
                updateVisHint();
                btnVis.disabled = select.value === state.visibility;
                whitelistSection.style.display = select.value === 'whitelist' ? '' : 'none';
            });

            btnVis.addEventListener('click', async () => {
                btnVis.disabled = true;
                statusEl.className = 've-status';
                statusEl.textContent = '저장 중...';
                try {
                    const res = await apiPatch(
                        `/api/v1/admin/lyrics/${lyricsId}/visibility`,
                        { visibility: select.value },
                    );
                    state.visibility = res.visibility;
                    statusEl.className = 've-status ok';
                    statusEl.textContent = '공개 범위가 저장되었습니다.';
                    if (opts.onSaved) opts.onSaved('visibility', state);
                    // 다시 그려서 배지 갱신
                    render();
                } catch (e) {
                    statusEl.className = 've-status err';
                    statusEl.textContent = '저장 실패: ' + e.message;
                    btnVis.disabled = false;
                }
            });

            // 자동완성
            let activeIdx = -1;
            let currentResults = [];

            const hideDropdown = () => {
                dropdown.style.display = 'none';
                dropdown.innerHTML = '';
                activeIdx = -1;
                currentResults = [];
            };

            const renderDropdown = (results) => {
                currentResults = results;
                if (!results.length) {
                    dropdown.innerHTML = '<div class="ve-dropdown-empty">일치하는 사용자가 없습니다.</div>';
                } else {
                    dropdown.innerHTML = results.map((u, i) => `
                        <div class="ve-dropdown-item${i === activeIdx ? ' active' : ''}" data-uid="${u.id}">
                            <div class="ve-name">${escapeHtml(u.name || '(이름 없음)')}</div>
                            <div class="ve-email">${escapeHtml(u.email)}</div>
                        </div>
                    `).join('');
                    dropdown.querySelectorAll('.ve-dropdown-item').forEach((el, i) => {
                        el.addEventListener('mousedown', (ev) => {
                            ev.preventDefault();
                            pickUser(results[i]);
                        });
                    });
                }
                dropdown.style.display = 'block';
            };

            const pickUser = (u) => {
                if (pendingWhitelist.some(p => p.id === u.id)) {
                    statusEl.className = 've-status';
                    statusEl.textContent = '이미 추가된 사용자입니다.';
                } else {
                    pendingWhitelist.push(u);
                    renderChips();
                    updateWlBtn();
                    statusEl.textContent = '';
                }
                searchInput.value = '';
                hideDropdown();
            };

            const doSearch = debounce(async (q) => {
                if (!q.trim()) { hideDropdown(); return; }
                try {
                    const res = await apiGet(`/api/v1/admin/users/search?q=${encodeURIComponent(q)}&limit=10`);
                    renderDropdown(res);
                } catch (e) {
                    console.error(e);
                    hideDropdown();
                }
            }, 200);

            searchInput.addEventListener('input', (e) => doSearch(e.target.value));
            searchInput.addEventListener('keydown', (e) => {
                if (dropdown.style.display === 'none' || !currentResults.length) return;
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    activeIdx = Math.min(activeIdx + 1, currentResults.length - 1);
                    renderDropdown(currentResults);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    activeIdx = Math.max(activeIdx - 1, 0);
                    renderDropdown(currentResults);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (activeIdx >= 0) pickUser(currentResults[activeIdx]);
                } else if (e.key === 'Escape') {
                    hideDropdown();
                }
            });
            searchInput.addEventListener('blur', () => setTimeout(hideDropdown, 150));

            btnWl.addEventListener('click', async () => {
                btnWl.disabled = true;
                statusEl.className = 've-status';
                statusEl.textContent = '저장 중...';
                try {
                    const res = await apiPut(
                        `/api/v1/admin/lyrics/${lyricsId}/whitelist`,
                        { user_ids: pendingIds() },
                    );
                    state.whitelist = res.whitelist;
                    statusEl.className = 've-status ok';
                    const addN = res.diff.added.length;
                    const rmN = res.diff.removed.length;
                    statusEl.textContent = `화이트리스트 저장됨 (추가 ${addN}, 제거 ${rmN}).`;
                    if (opts.onSaved) opts.onSaved('whitelist', state);
                    render();
                } catch (e) {
                    statusEl.className = 've-status err';
                    statusEl.textContent = '저장 실패: ' + e.message;
                    btnWl.disabled = false;
                }
            });
        }
    }

    window.mountVisibilityPanel = mountVisibilityPanel;
    window.__visibilityEditorBadge = renderBadge;
})();
