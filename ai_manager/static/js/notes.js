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
                        ${data.editable ? `
                        <div class="flex flex-wrap gap-2 mt-4" data-note-actions data-path="${window.escapeHtml(data.path)}">
                            <button type="button" class="btn btn-primary min-h-11" data-note-action="edit">✏️ Edit</button>
                            <button type="button" class="btn btn-ghost min-h-11" data-note-action="rename">Rename</button>
                            <button type="button" class="btn btn-danger min-h-11" data-note-action="delete">Delete</button>
                        </div>` : ''}
                    </header>
                    <div class="text-soft leading-relaxed space-y-6 markdown-body">
                        ${data.html_content}
                    </div>
                `;

                currentNote = { name: data.name || noteName, path: data.path, editable: !!data.editable };
                document.dispatchEvent(new CustomEvent('sb:note-loaded', { detail: currentNote }));

                // Replace stale backlink cards so the right panel matches the new note.
                mentionsFeed.innerHTML = '';
                const totalBacklinks = data.backlinks.length;
                backlinksLabel.textContent = `${totalBacklinks} note${totalBacklinks === 1 ? '' : 's'} link here`;

                if (totalBacklinks > 0) {
                    data.backlinks.forEach(mention => {
                        const cardHtml = `
                            <button type="button" class="backlink-card w-full text-left p-4 rounded-xl border border-line hover:border-accent hover:shadow-[var(--glow-active)] transition-all cursor-pointer bg-base/40" data-target="${window.escapeHtml(mention.title)}">
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
            const linkedNoteTarget = wikiLinkAnchor.getAttribute('data-note');
            loadNoteArchitecture(linkedNoteTarget);
        }
    });

    // Delegate backlink clicks for cards rebuilt whenever another note is loaded.
    mentionsFeed.addEventListener('click', (e) => {
        const backlinkCard = e.target.closest('.backlink-card');
        if (backlinkCard) {
            const historyNodeTarget = backlinkCard.getAttribute('data-target');
            loadNoteArchitecture(historyNodeTarget);
        }
    });

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