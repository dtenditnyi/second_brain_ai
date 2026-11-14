/*
 * Round 5 (F1): quick switcher — Ctrl+K / ⌘K (or the sidebar "Поиск" button) on every page.
 * Fuzzy match over note names and aliases from /api/notes/names/ (loaded once per page).
 * On the notes page the note opens in place (window.SBNotes), elsewhere → /notes/?path=…
 */
(function () {
    const overlay = document.getElementById('quick-switcher');
    if (!overlay) return;
    const input = document.getElementById('qs-input');
    const list = document.getElementById('qs-list');
    let notes = null, results = [], active = 0, lastFocus = null;

    // Subsequence fuzzy score: consecutive and word-start matches score higher; null = no match.
    function score(query, text) {
        const q = query.toLowerCase(), t = text.toLowerCase();
        if (!q) return 0;
        const direct = t.indexOf(q);
        if (direct >= 0) return 1000 - direct * 2 - (t.length - q.length) * 0.1 + (direct === 0 ? 200 : 0);
        let ti = 0, s = 0, run = 0;
        for (const ch of q) {
            const found = t.indexOf(ch, ti);
            if (found < 0) return null;
            run = found === ti ? run + 1 : 0;
            s += 10 + run * 5 + (found === 0 || /[\s\-_(/]/.test(t[found - 1]) ? 8 : 0) - Math.min(found - ti, 10);
            ti = found + 1;
        }
        return s;
    }

    function search(query) {
        const out = [];
        (notes || []).forEach(n => {
            let best = score(query, n.name), via = null;
            (n.aliases || []).forEach(a => {
                const s = score(query, a);
                if (s !== null && (best === null || s > best)) { best = s; via = a; }
            });
            if (best !== null) out.push({ note: n, score: best, via });
        });
        out.sort((a, b) => b.score - a.score || a.note.name.localeCompare(b.note.name));
        return out.slice(0, 30);
    }

    function render() {
        results = search(input.value.trim());
        if (active >= results.length) active = 0;
        list.innerHTML = results.length ? results.map((r, i) => `
            <li id="qs-opt-${i}" role="option" aria-selected="${i === active}" data-index="${i}"
                class="qs-option rounded-lg px-3 py-2 min-h-11 cursor-pointer flex flex-col justify-center">
                <span class="text-fg text-sm break-words">${window.escapeHtml(r.note.name)}${r.via ? ` <span class="text-muted">· ${window.escapeHtml(r.via)}</span>` : ''}</span>
                <span class="text-xs text-muted break-all">${window.escapeHtml(r.note.path)}</span>
            </li>`).join('')
            : `<li class="empty-state my-2" role="presentation">${notes ? 'Ничего не найдено' : 'Загрузка…'}</li>`;
        input.setAttribute('aria-activedescendant', results.length ? `qs-opt-${active}` : '');
        const el = document.getElementById(`qs-opt-${active}`);
        if (el) el.scrollIntoView({ block: 'nearest' });
    }

    async function load() {
        if (notes) return;
        try {
            const res = await fetch('/api/notes/names/');
            const data = await res.json();
            notes = data.notes || [];
        } catch (e) {
            notes = [];
        }
        render();
    }

    function open() {
        lastFocus = document.activeElement;
        overlay.classList.remove('hidden');
        input.value = '';
        active = 0;
        render();
        input.focus();
        load();
    }
    function close() {
        overlay.classList.add('hidden');
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
    function choose(i) {
        const r = results[i];
        if (!r) return;
        close();
        if (window.SBNotes && window.SBNotes.open) window.SBNotes.open(r.note.path, true);
        else window.location.href = '/notes/?path=' + encodeURIComponent(r.note.path);
    }

    window.SBSwitcher = { open, close };
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K' || e.code === 'KeyK')) {
            e.preventDefault();
            overlay.classList.contains('hidden') ? open() : close();
        }
    });
    document.querySelectorAll('[data-open-switcher]').forEach(b => b.addEventListener('click', open));
    input.addEventListener('input', () => { active = 0; render(); });
    input.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, results.length - 1); render(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
        else if (e.key === 'Enter') { e.preventDefault(); choose(active); }
        else if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
    list.addEventListener('click', e => {
        const li = e.target.closest('[data-index]');
        if (li) choose(Number(li.dataset.index));
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
})();
