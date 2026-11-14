/*
 * Interactive Obsidian note explorer for loading note bodies and backlinks.
 * The script calls Django's note-content API, renders the returned Markdown HTML,
 * and uses delegated events so dynamically inserted wiki links remain navigable.
 */
document.addEventListener('DOMContentLoaded', () => {
    
    // Cache the explorer, reading pane, and backlink region used throughout this page.
    const fileItems = document.querySelectorAll('.file-item');
    const contentArea = document.getElementById('workspace-content-area');
    const mentionsFeed = document.getElementById('linked-mentions-feed');
    const backlinksLabel = document.getElementById('backlinks-counter-label');

    if (!contentArea || !mentionsFeed) return;

    // Load one note for requests originating from the file list, a wiki link, or a backlink.
    // Parameters: noteName is the vault filename without the .md suffix.
    // Returns: a promise that resolves after the page regions reflect the API result.
    // Round 4: a note can also be opened by its vault-relative path (opts.path).
    async function loadNoteArchitecture(noteName, userInitiated = true, opts = {}) {
        if (!noteName && !opts.path) return;
        noteName = noteName || opts.path.split('/').pop().replace(/\.md$/i, '');

        // Highlight the selected source note before the network request completes.
        fileItems.forEach(item => {
            const same = opts.path ? item.getAttribute('data-path') === opts.path
                                   : item.getAttribute('data-filename') === noteName;
            if (same) {
                item.classList.add('text-fg', 'bg-accent/10', 'border-accent/40');
                item.setAttribute('aria-current', 'true');
            } else {
                item.classList.remove('text-fg', 'bg-accent/10', 'border-accent/40');
                item.removeAttribute('aria-current');
            }
        });

        // Provide immediate feedback because note retrieval may take noticeable time.
        contentArea.innerHTML = `
            <div class="flex flex-col gap-4" role="status" aria-label="Loading ${window.escapeHtml(noteName)}">
                <div class="skeleton h-9 w-2/3"></div>
                <div class="skeleton h-3 w-1/3"></div>
                <div class="skeleton h-4 w-full mt-4"></div>
                <div class="skeleton h-4 w-11/12"></div>
                <div class="skeleton h-4 w-4/5"></div>
            </div>
        `;
        // Below the 3-pane layout the reader sits under the explorer: bring it into view.
        if (window.innerWidth < 1280 && userInitiated) {
            contentArea.scrollIntoView({ behavior: window.prefersReducedMotion && window.prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
        }

        try {
            // Encode the filename because vault names may contain spaces or Unicode.
            const query = opts.path ? `path=${encodeURIComponent(opts.path)}` : `name=${encodeURIComponent(noteName)}`;
            const response = await fetch(`/api/get-note/?${query}`);
            const data = await response.json();

            if (data.status === 'ok') {
                // The API returns rendered Markdown plus backlink metadata for this note.
                contentArea.innerHTML = `
                    <header class="mb-6 sm:mb-8 border-b border-line pb-5 sm:pb-6">
                        <h1 class="text-2xl sm:text-3xl lg:text-4xl font-bold text-fg mb-2 tracking-tight break-words">${window.escapeHtml(data.name || noteName)}</h1>
                        <p class="text-xs text-accent uppercase tracking-widest font-mono font-semibold break-all">${window.escapeHtml(data.path || 'Markdown note')}</p>
                        <div class="flex flex-wrap gap-2 mt-4" data-note-actions data-path="${window.escapeHtml(data.path)}">
                            <button type="button" class="btn btn-ghost min-h-11" data-favorite aria-pressed="${data.favorite ? 'true' : 'false'}">${data.favorite ? '★ В избранном' : '☆ В избранное'}</button>
                        ${data.editable ? `
                            <button type="button" class="btn btn-primary min-h-11" data-note-action="edit">✏️ Edit</button>
                            <button type="button" class="btn btn-ghost min-h-11" data-note-action="rename">Rename</button>
                            <button type="button" class="btn btn-danger min-h-11" data-note-action="delete">Delete</button>` : ''}
                        </div>
                    </header>
                    <div class="text-soft leading-relaxed space-y-6 markdown-body" id="note-body">
                        ${window.SBRender ? window.SBRender.sanitize(data.html_content) : data.html_content}
                    </div>
                `;
                const body = document.getElementById('note-body');
                // A note whose first "# Title" repeats its name (often with an emoji) would show the
                // title twice: keep the page heading, drop the duplicate (like Obsidian's inline title).
                const ownH1 = body && body.querySelector('h1');
                const plain = t => (t || '').replace(/[^\p{L}\p{N}]+/gu, '').toLowerCase();
                if (ownH1 && plain(ownH1.textContent) === plain(data.name || noteName)) ownH1.remove();
                if (window.SBRender && body) {
                    window.SBRender.hydrate(body, { path: data.path, editable: !!data.editable,
                                                    reload: () => loadNoteArchitecture(null, false, { path: data.path }) });
                    if (opts.heading) window.SBRender.scrollToHeading(body, opts.heading);
                }
                revealInTree(data.path);
                renderUnlinked(data.unlinked || []);
                renderLocalGraph(data.path);
                if (userInitiated && data.path) {
                    const url = new URL(window.location.href);
                    url.searchParams.set('path', data.path);
                    window.history.replaceState({}, document.title, url);
                }

                currentNote = { name: data.name || noteName, path: data.path, editable: !!data.editable };
                document.dispatchEvent(new CustomEvent('sb:note-loaded', { detail: currentNote }));

                // Replace stale backlink cards so the right panel matches the new note.
                mentionsFeed.innerHTML = '';
                const totalBacklinks = data.backlinks.length;
                backlinksLabel.textContent = `${totalBacklinks} note${totalBacklinks === 1 ? '' : 's'} link here`;

                if (totalBacklinks > 0) {
                    data.backlinks.forEach(mention => {
                        const cardHtml = `
                            <button type="button" class="backlink-card w-full text-left p-4 rounded-xl border border-line hover:border-accent hover:shadow-[var(--glow-active)] transition-all cursor-pointer bg-base/40" data-target="${window.escapeHtml(mention.title)}" data-path="${window.escapeHtml(mention.path || '')}">
                                <span class="block font-medium text-fg text-sm mb-1 truncate">${window.escapeHtml(mention.title)}</span>
                                <span class="block text-xs text-muted leading-relaxed italic break-words">${window.escapeHtml(mention.snippet)}</span>
                            </button>
                        `;
                        mentionsFeed.insertAdjacentHTML('beforeend', cardHtml);
                    });
                } else {
                    mentionsFeed.innerHTML = '<div class="empty-state">No other note links here.</div>';
                }

            } else {
                // Keep server-side lookup/rendering errors inside the reading pane.
                contentArea.innerHTML = `
                    <div class="alert alert-danger" role="alert">
                        <h4 class="font-bold mb-1">Could not open “${window.escapeHtml(noteName)}”</h4>
                        <p class="text-sm">${window.escapeHtml(data.msg)}</p>
                    </div>
                `;
            }
        } catch (error) {
            console.error('API Transmission failure:', error);
            contentArea.innerHTML = `
                <div class="alert alert-danger" role="alert">
                    <h4 class="font-bold mb-1">Connection problem</h4>
                    <p class="text-sm">The note could not be loaded. Check your connection and try again.</p>
                </div>
            `;
        }
    }

    // Explorer items are static, so bind their click handlers once at initialization.
    fileItems.forEach(item => {
        item.addEventListener('click', () => {
            if (window.SBNotes.beforeLeave && !window.SBNotes.beforeLeave()) return;
            const targetNoteName = item.getAttribute('data-filename');
            loadNoteArchitecture(targetNoteName, true, { path: item.getAttribute('data-path') || undefined });
        });
    });

    // Round 4: the editor (note_editor.js) re-opens the read view through this hook.
    let currentNote = null;
    window.SBNotes = {
        open: (path, userInitiated = false) => loadNoteArchitecture(null, userInitiated, { path }),
        current: () => currentNote,
        beforeLeave: null,
    };
    const initialPath = new URLSearchParams(window.location.search).get('path');
    if (initialPath) loadNoteArchitecture(null, false, { path: initialPath });

    // Delegate wiki-link clicks because their anchors are injected after each API call.
    contentArea.addEventListener('click', (e) => {
        const wikiLinkAnchor = e.target.closest('.wiki-link');
        if (wikiLinkAnchor) {
            e.preventDefault();
            if (wikiLinkAnchor.classList.contains('unresolved')) return;
            const path = wikiLinkAnchor.getAttribute('data-path');
            const heading = wikiLinkAnchor.getAttribute('data-heading') || '';
            if (path && currentNote && path === currentNote.path && heading) {
                window.SBRender.scrollToHeading(document.getElementById('note-body'), heading);
                return;
            }
            if (path) loadNoteArchitecture(null, true, { path, heading });
            else loadNoteArchitecture(wikiLinkAnchor.getAttribute('data-note'));
            return;
        }
        const fav = e.target.closest('[data-favorite]');
        if (fav && currentNote) toggleFavorite(fav);
    });

    // Delegate backlink clicks for cards rebuilt whenever another note is loaded.
    mentionsFeed.addEventListener('click', (e) => {
        const backlinkCard = e.target.closest('.backlink-card');
        if (backlinkCard) {
            const path = backlinkCard.getAttribute('data-path');
            if (path) loadNoteArchitecture(null, true, { path });
            else loadNoteArchitecture(backlinkCard.getAttribute('data-target'));
        }
    });

    // ------------------------------------------------------------ Round 5 (F1): tree, search, favourites, graph
    const TREE_KEY = 'sb-tree-open';
    function openFolders() {
        try { return new Set(JSON.parse(localStorage.getItem(TREE_KEY) || '[]')); } catch (e) { return new Set(); }
    }
    function saveFolders(set) {
        try { localStorage.setItem(TREE_KEY, JSON.stringify([...set].slice(0, 300))); } catch (e) { /* ignore */ }
    }
    const folderState = openFolders();
    document.querySelectorAll('.vault-tree details[data-folder]').forEach(d => {
        if (folderState.has(d.dataset.folder)) d.open = true;
        d.addEventListener('toggle', () => {
            d.open ? folderState.add(d.dataset.folder) : folderState.delete(d.dataset.folder);
            saveFolders(folderState);
        });
    });
    function revealInTree(path) {
        if (!path) return;
        const item = Array.from(fileItems).find(i => i.getAttribute('data-path') === path);
        if (!item) return;
        let el = item.parentElement;
        while (el) {
            if (el.tagName === 'DETAILS') el.open = true;
            el = el.parentElement;
        }
        fileItems.forEach(i => {
            const same = i === item;
            i.classList.toggle('text-fg', same); i.classList.toggle('bg-accent/10', same); i.classList.toggle('border-accent/40', same);
            if (same) i.setAttribute('aria-current', 'true'); else i.removeAttribute('aria-current');
        });
    }

    const unlinkedFeed = document.getElementById('unlinked-mentions-feed');
    function renderUnlinked(items) {
        if (!unlinkedFeed) return;
        unlinkedFeed.innerHTML = items.length ? items.map(m => `
            <button type="button" class="backlink-card w-full text-left p-3 rounded-xl border border-line hover:border-accent transition-all bg-base/40" data-path="${window.escapeHtml(m.path)}" data-target="${window.escapeHtml(m.name)}">
                <span class="block font-medium text-fg text-sm mb-1 break-words">${window.escapeHtml(m.name)}</span>
                <span class="block text-xs text-muted leading-relaxed break-words search-hit">${window.SBRender ? window.SBRender.sanitize(m.snippet_html) : ''}</span>
            </button>`).join('') : '<div class="empty-state">Нет упоминаний без ссылки.</div>';
    }
    if (unlinkedFeed) unlinkedFeed.addEventListener('click', e => {
        const card = e.target.closest('[data-path]');
        if (card) loadNoteArchitecture(null, true, { path: card.dataset.path });
    });

    const graphBox = document.getElementById('local-graph');
    async function renderLocalGraph(path) {
        if (!graphBox || !window.SBGraph || !path) return;
        const link = document.getElementById('local-graph-link');
        if (link) link.href = '/notes/graph/?path=' + encodeURIComponent(path);
        try {
            const res = await fetch('/api/notes/graph/?path=' + encodeURIComponent(path));
            const data = await res.json();
            window.SBGraph.render(graphBox, data, { simple: true, onOpen: n => loadNoteArchitecture(null, true, { path: n.id }) });
        } catch (e) { graphBox.innerHTML = ''; }
    }

    async function toggleFavorite(btn) {
        const on = btn.getAttribute('aria-pressed') !== 'true';
        try {
            const res = await fetch('/api/notes/favorite/', { method: 'POST', headers: window.jsonHeaders(),
                body: JSON.stringify({ path: currentNote.path, favorite: on }) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.msg);
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
            btn.textContent = on ? '★ В избранном' : '☆ В избранное';
            renderFavorites(data.favorites || []);
        } catch (e) { /* keep the old state */ }
    }
    const favBox = document.getElementById('vault-favorites');
    function noteTitle(p) { return p.split('/').pop().replace(/\.md$/i, ''); }
    function renderFavorites(paths) {
        if (!favBox) return;
        favBox.innerHTML = paths.length ? '<p class="text-xs uppercase tracking-wider text-muted px-2 mb-1">★ Избранное</p><ul class="flex flex-col gap-0.5">' +
            paths.map(p => `<li><a href="?path=${encodeURIComponent(p)}" data-open-path="${window.escapeHtml(p)}" class="block px-2 py-2 min-h-11 rounded-md text-sm text-soft hover:text-fg hover:bg-surface break-words">${window.escapeHtml(noteTitle(p))}</a></li>`).join('') + '</ul>' : '';
    }
    fetch('/api/notes/tree/').then(r => r.ok ? r.json() : null).then(d => d && renderFavorites(d.favorites || [])).catch(() => {});
    document.addEventListener('click', e => {
        const a = e.target.closest('[data-open-path]');
        if (!a || e.ctrlKey || e.metaKey) return;
        e.preventDefault();
        if (window.SBNotes.beforeLeave && !window.SBNotes.beforeLeave()) return;
        loadNoteArchitecture(null, true, { path: a.dataset.openPath });
    });

    // Full-text search: debounce, filters, highlighted snippets (server escapes, <mark> only).
    const qInput = document.getElementById('vault-search-q');
    const resultsBox = document.getElementById('vault-search-results');
    const treeNav = document.getElementById('vault-tree-nav');
    let searchTimer = null, searchSeq = 0;
    async function runSearch() {
        const q = qInput.value.trim();
        const folder = document.getElementById('vault-search-folder').value;
        const tag = document.getElementById('vault-search-tag').value;
        const after = document.getElementById('vault-search-after').value;
        const active = q || folder || tag || after;
        resultsBox.classList.toggle('hidden', !active);
        treeNav.classList.toggle('hidden', !!active);
        if (!active) return;
        const seq = ++searchSeq;
        const params = new URLSearchParams({ q, folder, tag, after });
        resultsBox.innerHTML = '<div class="empty-state">Поиск…</div>';
        try {
            const res = await fetch('/api/notes/search/?' + params);
            const data = await res.json();
            if (seq !== searchSeq) return;
            const items = data.results || [];
            resultsBox.innerHTML = `<p class="text-xs text-muted mb-2">Найдено: ${items.length}</p>` + (items.length ? items.map(r => `
                <button type="button" class="w-full text-left p-3 mb-2 rounded-xl border border-line hover:border-accent bg-base/40 min-h-11" data-open-path="${window.escapeHtml(r.path)}">
                    <span class="block text-sm font-medium text-fg break-words">${window.escapeHtml(r.name)}</span>
                    <span class="block text-xs text-muted break-all mb-1">${window.escapeHtml(r.path)}</span>
                    <span class="block text-xs text-soft leading-relaxed break-words search-hit">${window.SBRender ? window.SBRender.sanitize(r.snippet_html) : ''}</span>
                </button>`).join('') : '<div class="empty-state">Ничего не найдено.</div>');
        } catch (e) {
            resultsBox.innerHTML = '<div class="alert alert-danger">Поиск недоступен (нет сети?).</div>';
        }
    }
    if (qInput && resultsBox) {
        document.getElementById('vault-search').addEventListener('submit', e => { e.preventDefault(); runSearch(); });
        qInput.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 250); });
        ['vault-search-folder', 'vault-search-tag', 'vault-search-after'].forEach(id =>
            document.getElementById(id).addEventListener('change', runSearch));
    }

    // --- Handle note links opened from the chat context list. ---
    const urlParams = new URLSearchParams(window.location.search);
    const encodedFile = urlParams.get('file');

    if (encodedFile) {
        try {
            // Decode the requested filename and normalize its optional extension.
            const requestedFile = decodeURIComponent(encodedFile).trim();
            const cleanRequestedName = requestedFile.replace(/\.md$/i, '').trim();


            // Match either the canonical data attribute or the visible explorer label.
            const requestedItem = Array.from(fileItems).find(item => {
                // Prefer the explicit filename attribute, ignoring an optional extension.
                const dataName = (item.getAttribute('data-filename') || '').replace(/\.md$/i, '').trim();

                // Fall back to the displayed text in case a legacy item lacks the attribute.
                const textName = item.textContent.trim();

                // Either representation is sufficient to identify the requested note.
                return dataName === cleanRequestedName || textName === cleanRequestedName;
            });

            if (requestedItem) {

                // Bring the matching item into view before triggering its normal handler.
                requestedItem.scrollIntoView({ block: 'nearest' });
                loadNoteArchitecture(requestedItem.getAttribute('data-filename'), false);

                // Remove the one-time parameter so a later reload does not reopen it.
                const newUrl = new URL(window.location.href);
                newUrl.searchParams.delete('file');
                window.history.replaceState({}, document.title, newUrl);
            } else {
                console.warn(`Note '${cleanRequestedName}' is not in the explorer.`);
            }
        } catch (error) {
            console.error('Could not open the linked note:', error);
        }
    }

});