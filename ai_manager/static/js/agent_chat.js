/*
 * Chat "Agent" mode (Round 4 / G-E3, G-E6): sends the request to /api/agent/run/, shows the
 * agent's steps, its Markdown answer and a card with the proposed changes (per-file diff or
 * final text). Nothing is written until "Применить всё" / "Применить выбранное"; an applied
 * batch can be reverted. All text from the server is escaped or sanitised before insertion.
 */
(function () {
    const esc = (s) => window.escapeHtml(String(s == null ? '' : s));
    const KIND = { append: 'дописать', replace: 'заменить фрагмент', create: 'новая заметка',
                   add_task: 'новая задача', update_task: 'изменить задачу' };

    async function post(url, payload) {
        try {
            const response = await fetch(url, { method: 'POST', headers: window.jsonHeaders(), body: JSON.stringify(payload || {}) });
            let data = {};
            try { data = await response.json(); } catch (e) { /* non-JSON error page */ }
            return { ok: response.ok, data };
        } catch (e) {
            return { ok: false, data: { msg: 'Нет соединения с сервером.' } };
        }
    }

    function diffHtml(diff) {
        return String(diff || '').split('\n').filter((l) => !/^(---|\+\+\+) /.test(l)).map((line) => {
            const cls = line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-del' : line.startsWith('@@') ? 'diff-hunk' : '';
            return `<span class="${cls}">${esc(line) || ' '}</span>`;
        }).join('\n');
    }

    function finalTexts(changes) {
        const byPath = new Map();
        changes.forEach((c) => byPath.set(c.path, c.after));
        return [...byPath.entries()];
    }

    function statusText(batch) {
        return { applied: '✅ Применено', partial: '✅ Применено частично', rejected: '✖ Отклонено',
                 reverted: '↩ Откат выполнен', pending: '' }[batch.status] || '';
    }

    function renderCard(card, batch) {
        const pending = batch.changes.filter((c) => c.pending);
        const canApply = ['pending', 'partial'].includes(batch.status) && pending.length > 0;
        const canRevert = ['applied', 'partial'].includes(batch.status) && batch.commits.length > 0;
        const mode = card.dataset.view || 'diff';
        card.innerHTML = `
            <header class="flex flex-wrap items-center justify-between gap-2 mb-2">
                <h3 class="font-semibold text-fg">Предложенные изменения (${batch.changes.length})</h3>
                <div class="agent-view-switch" role="group" aria-label="Вид">
                    <button type="button" class="btn btn-ghost btn-sm min-h-11" data-view="diff" aria-pressed="${mode === 'diff'}">Изменения</button>
                    <button type="button" class="btn btn-ghost btn-sm min-h-11" data-view="final" aria-pressed="${mode === 'final'}">Итоговый текст</button>
                </div>
            </header>
            <div class="${mode === 'diff' ? '' : 'hidden'} flex flex-col gap-3">
                ${batch.changes.map((c) => `
                <section class="agent-change">
                    <label class="flex items-center gap-2 min-h-11 cursor-pointer">
                        <span class="tap-zone"><input type="checkbox" data-index="${c.index}" ${c.pending ? 'checked' : 'disabled'}></span>
                        <span class="min-w-0 text-sm"><strong class="text-fg break-all">${esc(c.path)}</strong>
                            <span class="text-muted"> · ${esc(KIND[c.kind] || c.kind)}${c.applied ? ' · применено' : ''}</span></span>
                    </label>
                    <pre class="agent-diff">${diffHtml(c.diff)}</pre>
                </section>`).join('')}
            </div>
            <div class="${mode === 'final' ? '' : 'hidden'} flex flex-col gap-3">
                ${finalTexts(batch.changes).map(([path, text]) => `
                <section><p class="text-sm font-semibold text-fg break-all mb-1">${esc(path)}</p>
                    <pre class="agent-final-text">${esc(text)}</pre></section>`).join('')}
            </div>
            <p class="agent-applied text-sm mt-3 ${statusText(batch) ? '' : 'hidden'}" role="status" aria-live="polite">${esc(statusText(batch))}</p>
            <p class="agent-error alert alert-danger mt-3 hidden" role="alert"></p>
            <div class="flex flex-wrap gap-2 mt-3">
                ${canApply ? `<button type="button" class="btn btn-primary min-h-11" data-act="all">Применить всё</button>
                <button type="button" class="btn btn-ghost min-h-11" data-act="selected">Применить выбранное</button>
                <button type="button" class="btn btn-ghost min-h-11" data-act="reject">Отклонить</button>` : ''}
                ${canRevert ? '<button type="button" class="btn btn-danger min-h-11" data-act="revert">Откатить</button>' : ''}
            </div>`;
        card.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
            card.dataset.view = b.dataset.view;
            renderCard(card, batch);
        }));
        card.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => act(card, batch, b.dataset.act)));
    }

    async function act(card, batch, what) {
        const base = `/api/agent/batch/${batch.id}/`;
        let result;
        card.querySelectorAll('[data-act]').forEach((b) => { b.disabled = true; });
        if (what === 'all') result = await post(base + 'apply/', {});
        else if (what === 'selected') {
            const indices = [...card.querySelectorAll('input[data-index]:checked:not(:disabled)')].map((i) => Number(i.dataset.index));
            if (!indices.length) { showError(card, 'Отметьте хотя бы одно изменение.'); card.querySelectorAll('[data-act]').forEach((b) => { b.disabled = false; }); return; }
            result = await post(base + 'apply/', { indices });
        } else result = await post(base + what + '/', {});
        if (result.ok && result.data.batch) {
            renderCard(card, result.data.batch);
        } else {
            card.querySelectorAll('[data-act]').forEach((b) => { b.disabled = false; });
            showError(card, result.data.msg || 'Не удалось выполнить действие.');
        }
    }

    function showError(card, msg) {
        const el = card.querySelector('.agent-error');
        el.textContent = msg;
        el.classList.remove('hidden');
    }

    async function run(message, article, scrollToBottom) {
        const bubble = article.querySelector('.chat-bubble');
        bubble.innerHTML = '<p class="text-muted flex items-center gap-2" role="status"><span class="spinner"></span> Агент работает: ищу, читаю заметки, готовлю изменения…</p>';
        const result = await post('/api/agent/run/', { message });
        const data = result.data || {};
        if (!result.ok) {
            bubble.innerHTML = `<p class="text-fg">⚠️ ${esc(data.msg || 'Запрос агента отклонён.')}</p>`;
            bubble.classList.add('is-notice');
            return;
        }
        bubble.innerHTML = '';
        if (data.steps && data.steps.length) {
            const ol = document.createElement('ol');
            ol.className = 'agent-steps';
            ol.innerHTML = data.steps.map((s) => `<li class="agent-step${s.ok ? '' : ' is-failed'}">${esc(s.label)}${s.ok ? '' : ' — ошибка'}</li>`).join('');
            bubble.appendChild(ol);
        }
        const body = document.createElement('div');
        body.className = 'text-fg leading-relaxed';
        if (window.renderMarkdownInto) window.renderMarkdownInto(body, data.text || '');
        else body.textContent = data.text || '';
        bubble.appendChild(body);
        if (data.batch) {
            const card = document.createElement('div');
            card.className = 'agent-diff-card';
            bubble.appendChild(card);
            renderCard(card, data.batch);
        }
        if (data.provider) {
            const meta = document.createElement('p');
            meta.className = 'mt-2 text-xs text-muted';
            meta.textContent = `Агент · ${data.provider}`;
            bubble.appendChild(meta);
        }
        scrollToBottom(true);
    }

    window.SBAgent = { run };
})();
