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
    async function loadNoteArchitecture(noteName, userInitiated = true) {
        if (!noteName) return;

        // Highlight the selected source note before the network request completes.
        fileItems.forEach(item => {
            if (item.getAttribute('data-filename') === noteName) {
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
            const response = await fetch(`/api/get-note/?name=${encodeURIComponent(noteName)}`);
            const data = await response.json();

            if (data.status === 'ok') {
                // The API returns rendered Markdown plus backlink metadata for this note.
                contentArea.innerHTML = `
                    <header class="mb-6 sm:mb-8 border-b border-line pb-5 sm:pb-6">
                        <h1 class="text-2xl sm:text-3xl lg:text-4xl font-bold text-fg mb-2 tracking-tight break-words">${window.escapeHtml(noteName)}</h1>
                        <p class="text-xs text-accent uppercase tracking-widest font-mono font-semibold">Markdown note</p>
                    </header>
                    <div class="text-soft leading-relaxed space-y-6 markdown-body">
                        ${data.html_content}
                    </div>
                `;

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
            const targetNoteName = item.getAttribute('data-filename');
            loadNoteArchitecture(targetNoteName);
        });
    });

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