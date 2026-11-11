/*
 * Note editor (Round 4 / part D): CodeMirror 6 (static/vendor/sb-editor.js) with a live
 * Markdown preview, [[link]] autocompletion, Ctrl+S / Esc, draft autosave in this browser,
 * save conflicts (diff dialog), rename with a link-update preview, delete and "new note".
 *
 * Everything is saved through /api/notes/* → core/notes_service.py → the single vault writer.
 */
(function () {
    'use strict';

    const area = document.getElementById('workspace-content-area');
    if (!area) return;
    const main = area.closest('main');
    const esc = (t) => window.escapeHtml(String(t ?? ''));
    const DRAFT_PREFIX = 'sb-note-draft:';
    const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/;

    let state = null;   // {path, name, baseSha, savedContent, editor, saving}
    let noteNames = null;

    // ------------------------------------------------------------------ helpers

    function draftKey(path) { return DRAFT_PREFIX + path; }
    function loadDraft(path) {
        try { return JSON.parse(localStorage.getItem(draftKey(path)) || 'null'); } catch (e) { return null; }
    }
    function storeDraft(path, content, baseSha) {
        try { localStorage.setItem(draftKey(path), JSON.stringify({ content, base_sha: baseSha, at: Date.now() })); } catch (e) { /* storage off */ }
    }
    function clearDraft(path) {
        try { localStorage.removeItem(draftKey(path)); } catch (e) { /* storage off */ }
    }

    async function api(url, payload) {
        const options = payload === undefined ? {} : { method: 'POST', headers: window.jsonHeaders(), body: JSON.stringify(payload) };
        const response = await fetch(url, options);
        let data = {};
        try { data = await response.json(); } catch (e) { data = { status: 'error', msg: `HTTP ${response.status}` }; }
        return { ok: response.ok, status: response.status, data };
    }

    async function loadNames() {
        if (noteNames) return noteNames;
        try {
            const { ok, data } = await api('/api/notes/names/');
            const names = new Set();
            if (ok) (data.notes || []).forEach((n) => { names.add(n.name); (n.aliases || []).forEach((a) => names.add(a)); });
            noteNames = Array.from(names).sort((a, b) => a.localeCompare(b));
        } catch (e) { noteNames = []; }
        return noteNames;
    }

    function setStatus(text, tone) {
        const el = document.getElementById('note-save-status');
        if (!el) return;
        el.textContent = text;
        el.className = 'text-xs font-semibold ' + (tone === 'error' ? 'text-danger' : tone === 'warn' ? 'text-warning' : tone === 'ok' ? 'text-success' : 'text-muted');
    }

    function renderDiff(pre, diff) {
        pre.textContent = '';
        String(diff || '').split('\n').forEach((line) => {
            const span = document.createElement('span');
            span.className = line.startsWith('@@') ? 'diff-hunk' : (line.startsWith('+') && !line.startsWith('+++')) ? 'diff-add'
                : (line.startsWith('-') && !line.startsWith('---')) ? 'diff-del' : 'diff-ctx';
            span.textContent = line || ' ';
            pre.appendChild(span);
        });
    }

    function renderPreview(text) {
        const preview = document.getElementById('note-preview');
        if (!preview) return;
        preview.textContent = '';
        let body = text;
        const match = FRONTMATTER.exec(text);
        if (match) {
            const details = document.createElement('details');
            details.className = 'note-props mb-3';
            const summary = document.createElement('summary');
            summary.textContent = 'Свойства';
            const pre = document.createElement('pre');
            pre.textContent = match[1];
            details.append(summary, pre);
            preview.appendChild(details);
            body = text.slice(match[0].length);
        }
        const content = document.createElement('div');
        preview.appendChild(content);
        if (window.renderMarkdownInto) window.renderMarkdownInto(content, body);
        else content.textContent = body;     // markdown.js missing: still safe
    }

    let previewTimer = null;
    let draftTimer = null;
    function onChange(text) {
        if (!state) return;
        // Small notes re-render on every keystroke; big ones are debounced.
        clearTimeout(previewTimer);
        if (text.length < 40000) renderPreview(text);
        else previewTimer = setTimeout(() => renderPreview(state.editor.getValue()), 250);
        const dirty = text !== state.savedContent;
        if (dirty) setStatus('Есть несохранённые изменения', 'warn');
        clearTimeout(draftTimer);
        draftTimer = setTimeout(() => {
            if (!state) return;
            const now = state.editor.getValue();
            if (now !== state.savedContent) storeDraft(state.path, now, state.baseSha);
            else clearDraft(state.path);
        }, 400);
    }

    function isDirty() { return !!state && state.editor.getValue() !== state.savedContent; }

    // ------------------------------------------------------------------ edit mode

    function selectTab(which) {
        const grid = document.getElementById('note-editor-grid');
        if (!grid) return;
        grid.dataset.tab = which;
        document.querySelectorAll('#note-editor-tabs [role="tab"]').forEach((tab) => {
            const on = tab.dataset.tab === which;
            tab.setAttribute('aria-selected', on ? 'true' : 'false');
            tab.tabIndex = on ? 0 : -1;
        });
        if (which === 'text' && state) state.editor.focus();
    }

    async function openEditor(path) {
        if (!window.SBEditor) { setStatus('Редактор ещё загружается…'); return; }
        area.innerHTML = '<div class="flex items-center gap-3 text-muted" role="status"><span class="spinner"></span> Открываю редактор…</div>';
        const [raw, names] = await Promise.all([api(`/api/notes/raw/?path=${encodeURIComponent(path)}`), loadNames()]);
        if (!raw.ok) {
            area.innerHTML = `<div class="alert alert-danger" role="alert"><h4 class="font-bold mb-1">Не удалось открыть редактор</h4><p class="text-sm">${esc(raw.data.msg)}</p></div>`;
            return;
        }
        const name = path.split('/').pop().replace(/\.md$/i, '');
        const draft = loadDraft(path);
        const useDraft = draft && typeof draft.content === 'string' && draft.content !== raw.data.content;
        if (draft && !useDraft) clearDraft(path);

        area.innerHTML = `
            <header class="flex flex-wrap items-start justify-between gap-3 mb-3">
                <div class="min-w-0">
                    <h1 class="text-xl sm:text-2xl font-bold text-fg break-words">${esc(name)}</h1>
                    <p class="text-xs text-muted font-mono break-all">${esc(path)}</p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                    <span id="note-save-status" class="text-xs text-muted" role="status" aria-live="polite"></span>
                    <button type="button" class="btn btn-primary min-h-11" data-editor="save" title="Ctrl+S">Сохранить</button>
                    <button type="button" class="btn btn-ghost min-h-11" data-editor="exit" title="Esc">Готово</button>
                </div>
            </header>
            <div id="note-draft-banner" class="alert alert-warning mb-3 hidden" role="status">
                <span>Восстановлен несохранённый черновик из этого браузера${useDraft ? ' (' + esc(new Date(draft.at).toLocaleString()) + ')' : ''}.</span>
                <button type="button" class="underline font-semibold ml-1 min-h-11" data-editor="discard-draft">Отбросить черновик</button>
            </div>
            <div id="note-editor-tabs" class="note-tabs mb-3" role="tablist" aria-label="Режим редактора">
                <button type="button" role="tab" data-tab="text" aria-selected="true" aria-controls="note-editor-pane">Текст</button>
                <button type="button" role="tab" data-tab="preview" aria-selected="false" aria-controls="note-preview" tabindex="-1">Просмотр</button>
            </div>
            <div id="note-editor-grid" class="note-editor-grid" data-tab="text">
                <div id="note-editor-pane" class="note-editor-pane" role="tabpanel" aria-label="Текст заметки"></div>
                <div id="note-preview" class="note-preview-pane markdown-body text-soft leading-relaxed" role="tabpanel" aria-label="Просмотр"></div>
            </div>
            <p class="text-xs text-muted mt-2">Ctrl+S — сохранить · Esc — выйти · [[ — ссылка на заметку. Черновик сохраняется в этом браузере автоматически.</p>`;

        state = { path, name, baseSha: useDraft && draft.base_sha ? draft.base_sha : raw.data.sha,
                  savedContent: raw.data.content, editor: null, saving: false };
        state.editor = window.SBEditor.create(document.getElementById('note-editor-pane'), {
            doc: useDraft ? draft.content : raw.data.content,
            noteNames: names,
            onSave: () => save(),
            onExit: () => exitEditor(),
            onChange,
            label: `Текст заметки ${name}`,
        });
        if (useDraft) {
            document.getElementById('note-draft-banner').classList.remove('hidden');
            setStatus('Есть несохранённые изменения', 'warn');
        }
        renderPreview(state.editor.getValue());
        state.editor.focus();
        window.SBNotes.beforeLeave = () => true;      // drafts survive navigation
    }

    function exitEditor() {
        if (!state) return;
        if (document.querySelector('.modal-overlay:not(.hidden)')) return;
        const path = state.path;
        clearTimeout(draftTimer);
        if (isDirty()) storeDraft(path, state.editor.getValue(), state.baseSha);
        state.editor.destroy();
        state = null;
        window.SBNotes.open(path);
    }

    async function save() {
        if (!state || state.saving) return;
        state.saving = true;
        const content = state.editor.getValue();
        setStatus('Сохранение…');
        let result;
        try {
            result = await api('/api/notes/save/', { path: state.path, content, base_sha: state.baseSha });
        } catch (e) {
            storeDraft(state.path, content, state.baseSha);
            setStatus('Нет связи с сайтом — черновик сохранён в этом браузере', 'error');
            state.saving = false;
            return;
        }
        state.saving = false;
        if (!state) return;
        const { ok, status, data } = result;
        if (ok && data.status === 'ok') {
            state.baseSha = data.sha;
            state.savedContent = content;
            clearDraft(state.path);
            document.getElementById('note-draft-banner')?.classList.add('hidden');
            if (isDirty()) storeDraft(state.path, state.editor.getValue(), state.baseSha);
            setStatus(data.queued ? 'Нет связи с GitHub — в очереди, отправится позже' : 'Сохранено ✓', data.queued ? 'warn' : 'ok');
        } else if (status === 409 && data.status === 'conflict') {
            storeDraft(state.path, content, state.baseSha);
            showConflict(data, content);
        } else {
            setStatus('Ошибка: ' + (data.msg || status), 'error');
        }
    }

    // ------------------------------------------------------------------ conflict dialog

    const conflict = document.getElementById('note-conflict');
    let conflictData = null;

    function showConflict(data, mine) {
        conflictData = { ...data, mine };
        renderDiff(document.getElementById('note-conflict-diff'), data.diff);
        conflict.classList.remove('hidden');
        setStatus('Конфликт: заметка изменилась в хранилище', 'error');
        conflict.querySelector('[data-conflict="mine"]').focus();
    }
    function closeConflict() {
        conflict.classList.add('hidden');
        if (state) state.editor.focus();
    }

    async function copyText(text) {
        try {
            if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
        } catch (e) { /* fall through */ }
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        let done = false;
        try { done = document.execCommand('copy'); } catch (e) { done = false; }
        ta.remove();
        return done;
    }

    conflict?.addEventListener('click', async (e) => {
        if (e.target === conflict || e.target.closest('[data-conflict-close]')) { closeConflict(); return; }
        const button = e.target.closest('[data-conflict]');
        if (!button || !state || !conflictData) return;
        const action = button.dataset.conflict;
        if (action === 'mine') {
            state.baseSha = conflictData.current_sha;        // overwrite the vault version
            closeConflict();
            await save();
        } else if (action === 'theirs') {
            state.editor.setValue(conflictData.current_content);
            state.baseSha = conflictData.current_sha;
            state.savedContent = conflictData.current_content;
            clearDraft(state.path);
            closeConflict();
            setStatus('Загружена версия из хранилища', 'ok');
        } else if (action === 'copy') {
            const done = await copyText(conflictData.mine);
            setStatus(done ? 'Ваш текст скопирован в буфер обмена' : 'Не удалось скопировать — текст остался в редакторе', done ? 'ok' : 'error');
            closeConflict();
        }
    });

    // ------------------------------------------------------------------ rename / delete

    const renameDialog = document.getElementById('note-rename');
    const renameInput = document.getElementById('rename-new-name');
    const renameConfirm = document.getElementById('rename-confirm-btn');
    const renameList = document.getElementById('rename-affected');
    const renameResult = document.getElementById('rename-result');
    let renamePath = null;

    function newPathFor(path, name) {
        const parts = path.split('/');
        parts[parts.length - 1] = name.trim() + '.md';
        return parts.join('/');
    }

    function openRename(path) {
        renamePath = path;
        renameInput.value = path.split('/').pop().replace(/\.md$/i, '');
        renameList.innerHTML = '';
        renameResult.textContent = '';
        renameConfirm.disabled = true;
        renameDialog.classList.remove('hidden');
        renameInput.focus();
        renameInput.select();
    }
    function closeRename() { renameDialog.classList.add('hidden'); }

    async function previewRename() {
        const name = renameInput.value.trim();
        if (!name) return;
        renameResult.textContent = 'Проверяю…';
        const { ok, data } = await api('/api/notes/rename/', { path: renamePath, new_path: newPathFor(renamePath, name), preview: true });
        renameList.innerHTML = '';
        if (!ok) { renameResult.textContent = data.msg || 'Ошибка'; renameConfirm.disabled = true; return; }
        const affected = data.affected || [];
        renameResult.textContent = affected.length
            ? `Ссылки будут обновлены в ${affected.length} заметк${affected.length === 1 ? 'е' : 'ах'}:`
            : 'Других заметок со ссылками на эту нет.';
        affected.forEach((p) => {
            const li = document.createElement('li');
            li.className = 'break-all';
            li.textContent = '• ' + p;
            renameList.appendChild(li);
        });
        renameConfirm.disabled = false;
    }

    async function confirmRename() {
        const newPath = newPathFor(renamePath, renameInput.value);
        renameConfirm.disabled = true;
        renameResult.textContent = 'Переименовываю…';
        const { ok, data } = await api('/api/notes/rename/', { path: renamePath, new_path: newPath });
        if (!ok) { renameResult.textContent = data.msg || 'Ошибка'; renameConfirm.disabled = false; return; }
        clearDraft(renamePath);
        window.location.href = `/notes/?path=${encodeURIComponent(data.path)}`;
    }

    renameInput?.addEventListener('input', () => { renameConfirm.disabled = true; renameList.innerHTML = ''; renameResult.textContent = ''; });
    renameInput?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); previewRename(); } });
    document.getElementById('rename-preview-btn')?.addEventListener('click', previewRename);
    renameConfirm?.addEventListener('click', confirmRename);
    renameDialog?.addEventListener('click', (e) => {
        if (e.target === renameDialog || e.target.closest('[data-rename-close]')) closeRename();
    });

    async function deleteNote(path) {
        const name = path.split('/').pop();
        if (!window.confirm(`Удалить заметку «${name}»?\n\nЭто отдельный коммит в хранилище — вернуть можно через историю git.`)) return;
        const { ok, data } = await api('/api/notes/delete/', { path });
        if (!ok) { window.alert(data.msg || 'Не удалось удалить.'); return; }
        clearDraft(path);
        window.location.href = '/notes/';
    }

    // ------------------------------------------------------------------ new note

    const createDialog = document.getElementById('note-create');
    const createForm = document.getElementById('note-create-form');
    const createError = document.getElementById('create-error');

    function fillSelect(select, values, labelFor, keepFirst) {
        const first = keepFirst ? select.querySelector('option') : null;
        select.innerHTML = '';
        if (first) select.appendChild(first);
        values.forEach((v) => {
            const opt = document.createElement('option');
            opt.value = v;
            opt.textContent = labelFor(v);
            select.appendChild(opt);
        });
    }

    async function openCreate() {
        createError.classList.add('hidden');
        createForm.reset();
        createDialog.classList.remove('hidden');
        document.getElementById('create-title').focus();
        const { ok, data } = await api('/api/notes/meta/');
        if (!ok) { createError.textContent = data.msg || 'Хранилище недоступно.'; createError.classList.remove('hidden'); return; }
        const folder = document.getElementById('create-folder');
        fillSelect(folder, data.folders || [''], (v) => v || '/ (корень хранилища)');
        if ((data.folders || []).includes('05 - Fleeting')) folder.value = '05 - Fleeting';
        fillSelect(document.getElementById('create-template'), data.templates || [], (v) => v, true);
        const moc = document.getElementById('create-moc');
        fillSelect(moc, data.mocs || [], (v) => v);
        if ((data.mocs || []).includes('Главная (Home)')) moc.value = 'Главная (Home)';
    }

    createForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        createError.classList.add('hidden');
        const tags = document.getElementById('create-tags').value.split(',').map((t) => t.trim().replace(/^#/, '')).filter(Boolean);
        const { ok, data } = await api('/api/notes/create/', {
            folder: document.getElementById('create-folder').value,
            title: document.getElementById('create-title').value,
            template: document.getElementById('create-template').value,
            moc: document.getElementById('create-moc').value,
            tags,
        });
        if (!ok) { createError.textContent = data.msg || 'Ошибка'; createError.classList.remove('hidden'); return; }
        window.location.href = `/notes/?path=${encodeURIComponent(data.path)}&edit=1`;
    });
    createDialog?.addEventListener('click', (e) => {
        if (e.target === createDialog || e.target.closest('[data-create-close]')) createDialog.classList.add('hidden');
    });
    document.getElementById('note-new-btn')?.addEventListener('click', openCreate);

    // ------------------------------------------------------------------ wiring

    area.addEventListener('click', (e) => {
        const action = e.target.closest('[data-note-action]');
        if (action) {
            const path = action.closest('[data-note-actions]').dataset.path;
            if (action.dataset.noteAction === 'edit') openEditor(path);
            else if (action.dataset.noteAction === 'rename') openRename(path);
            else if (action.dataset.noteAction === 'delete') deleteNote(path);
            return;
        }
        const control = e.target.closest('[data-editor]');
        if (control) {
            if (control.dataset.editor === 'save') save();
            else if (control.dataset.editor === 'exit') exitEditor();
            else if (control.dataset.editor === 'discard-draft' && state) {
                clearDraft(state.path);
                state.editor.setValue(state.savedContent);
                document.getElementById('note-draft-banner').classList.add('hidden');
                setStatus('Черновик отброшен');
            }
            return;
        }
        const tab = e.target.closest('#note-editor-tabs [role="tab"]');
        if (tab) selectTab(tab.dataset.tab);
    });

    area.addEventListener('keydown', (e) => {
        const tab = e.target.closest('#note-editor-tabs [role="tab"]');
        if (tab && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
            e.preventDefault();
            selectTab(tab.dataset.tab === 'text' ? 'preview' : 'text');
            document.querySelector('#note-editor-tabs [aria-selected="true"]').focus();
        }
    });

    // Ctrl+S / Esc also work when the focus is outside CodeMirror (preview, buttons).
    document.addEventListener('keydown', (e) => {
        const openModal = document.querySelector('.modal-overlay:not(.hidden)');
        if (e.key === 'Escape' && openModal) {
            openModal.classList.add('hidden');
            if (state) state.editor.focus();
            return;
        }
        if (!state || e.target.closest('.cm-editor')) return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
        else if (e.key === 'Escape') exitEditor();
    });

    // /notes/?path=…&edit=1 (after "new note") opens the editor right away.
    document.addEventListener('sb:note-loaded', (e) => {
        const params = new URLSearchParams(window.location.search);
        if (params.get('edit') === '1' && e.detail.editable && params.get('path') === e.detail.path) {
            params.delete('edit');
            window.history.replaceState({}, document.title, `${window.location.pathname}?${params}`);
            openEditor(e.detail.path);
        }
    });

    if (main && main.dataset.vaultEditable !== '1') return;
})();
