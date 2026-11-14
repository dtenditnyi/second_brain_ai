/*
 * Round 5 (F2): client side of the Obsidian-like note view.
 *  - sanitize(): DOMPurify over the server HTML (defence in depth: the server already escapes
 *    raw HTML from notes);
 *  - hydrate(): KaTeX for .math, Mermaid for pre.mermaid (both local, loaded only when a note
 *    needs them), clickable task checkboxes → /api/notes/toggle-task/ (one commit per click,
 *    through the vault writer), wiki links to a heading scroll to it.
 */
(function () {
    const STATIC = (document.querySelector('script[src*="note_render"]')?.getAttribute('src') || '/static/js/note_render.js')
        .replace(/js\/note_render\.js.*$/, '');
    const loaded = {};

    function loadScript(src) {
        if (!loaded[src]) {
            loaded[src] = new Promise((resolve, reject) => {
                const s = document.createElement('script');
                s.src = src; s.onload = resolve; s.onerror = reject;
                document.head.appendChild(s);
            });
        }
        return loaded[src];
    }
    function loadCss(href) {
        if (document.querySelector(`link[href="${href}"]`)) return;
        const l = document.createElement('link');
        l.rel = 'stylesheet'; l.href = href;
        document.head.appendChild(l);
    }

    function sanitize(html) {
        if (!window.DOMPurify) return html;
        return window.DOMPurify.sanitize(html, { ADD_ATTR: ['open', 'target'], FORBID_TAGS: ['style', 'form'] });
    }

    async function renderMath(root) {
        const nodes = root.querySelectorAll('.math');
        if (!nodes.length) return;
        loadCss(STATIC + 'vendor/katex/katex.min.css');
        try { await loadScript(STATIC + 'vendor/katex/katex.min.js'); } catch (e) { return; }
        nodes.forEach(el => {
            try {
                window.katex.render(el.textContent, el, { displayMode: el.classList.contains('math-display'), throwOnError: false, trust: false });
            } catch (e) { /* leave the TeX source visible */ }
        });
    }

    async function renderMermaid(root) {
        const nodes = root.querySelectorAll('pre.mermaid');
        if (!nodes.length) return;
        try { await loadScript(STATIC + 'vendor/mermaid.min.js'); } catch (e) { return; }
        const dark = document.documentElement.dataset.theme !== 'light';
        window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'default' });
        try { await window.mermaid.run({ nodes }); } catch (e) { /* the source stays visible */ }
    }

    const NEXT = { ' ': 'done', 'x': 'todo', 'X': 'todo', '/': 'done', '>': 'todo', '-': 'todo' };
    const CLASS = { todo: ' ', done: 'x', in_progress: '/', forwarded: '>', cancelled: '-' };

    function bindTasks(root, ctx) {
        root.querySelectorAll('input.task-cb[data-task-line]:not([disabled])').forEach(box => {
            if (!ctx.editable || box.dataset.taskLine === '') { box.disabled = true; return; }
            box.addEventListener('click', async e => {
                e.preventDefault();
                const status = NEXT[box.dataset.status] || 'done';
                box.disabled = true;
                try {
                    const res = await fetch('/api/notes/toggle-task/', {
                        method: 'POST', headers: window.jsonHeaders(),
                        body: JSON.stringify({ path: ctx.path, line: box.dataset.taskRaw, line_no: Number(box.dataset.taskLine), status }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error(data.msg || 'HTTP ' + res.status);
                    const ch = CLASS[status];
                    box.dataset.status = ch;
                    if (data.raw) box.dataset.taskRaw = data.raw;
                    box.checked = status === 'done';
                    box.className = 'task-cb task-' + status;
                    box.setAttribute('aria-label', status === 'done' ? 'сделано' : 'надо');
                } catch (err) {
                    alert('Не удалось изменить задачу: ' + err.message);
                    if (ctx.reload) ctx.reload();
                } finally {
                    box.disabled = false;
                }
            });
        });
    }

    function scrollToHeading(root, slug) {
        if (!slug) return;
        const el = root.querySelector(`[id="${CSS.escape(slug)}"]`);
        if (el) el.scrollIntoView({ block: 'start' });
    }

    function hydrate(root, ctx = {}) {
        bindTasks(root, ctx);
        renderMath(root);
        renderMermaid(root);
    }

    window.SBRender = { sanitize, hydrate, scrollToHeading };
})();
