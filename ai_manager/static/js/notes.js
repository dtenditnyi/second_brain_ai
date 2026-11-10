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
    async function loadNoteArchitecture(noteName) {
        if (!noteName) return;

        // Highlight the selected source note before the network request completes.
        fileItems.forEach(item => {
            if (item.getAttribute('data-filename') === noteName) {
                item.classList.add('text-[var(--text-primary)]', 'bg-[var(--active-accent)]/10', 'shadow-[var(--glow-active)]', 'border', 'border-[var(--active-accent)]/20');
            } else {
                item.classList.remove('text-[var(--text-primary)]', 'bg-[var(--active-accent)]/10', 'shadow-[var(--glow-active)]', 'border', 'border-[var(--active-accent)]/20');
            }
        });

        // Provide immediate feedback because note retrieval may take noticeable time.
        contentArea.innerHTML = `
            <div class="flex items-center justify-center h-full">
                <p class="text-[var(--active-accent)] animate-pulse font-mono text-sm uppercase tracking-widest">
                    Defragmenting Vault Node Content: ${window.escapeHtml(noteName)}...
                </p>
            </div>
        `;

        try {
            // Encode the filename because vault names may contain spaces or Unicode.
            const response = await fetch(`/api/get-note/?name=${encodeURIComponent(noteName)}`);
            const data = await response.json();

            if (data.status === 'ok') {
                // The API returns rendered Markdown plus backlink metadata for this note.
                contentArea.innerHTML = `
                    <header class="mb-8 border-b border-[var(--border-glass)] pb-6">
                        <h1 class="text-3xl lg:text-4xl font-bold text-[var(--text-primary)] mb-2 tracking-tight">${window.escapeHtml(noteName)}</h1>
                        <p class="text-xs text-[var(--active-accent)] opacity-80 uppercase tracking-widest font-mono font-semibold">
                            Secure Sandbox Node Sync Matrix
                        </p>
                    </header>
                    <div class="text-[var(--text-secondary)] leading-relaxed space-y-6 markdown-body">
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
                            <article class="backlink-card p-4 rounded-xl border border-[var(--border-glass)] hover:border-[var(--active-accent)] hover:shadow-[var(--glow-active)] transition-all cursor-pointer bg-[var(--bg-base)]/40 hover:-translate-y-0.5" data-target="${window.escapeHtml(mention.title)}">
                                <h4 class="font-medium text-[var(--text-primary)] text-sm mb-1 truncate">${window.escapeHtml(mention.title)}</h4>
                                <p class="text-[11px] opacity-60 leading-relaxed font-serif italic">${window.escapeHtml(mention.snippet)}</p>
                            </article>
                        `;
                        mentionsFeed.insertAdjacentHTML('beforeend', cardHtml);
                    });
                } else {
                    mentionsFeed.innerHTML = `
                        <div class="p-4 rounded-xl border border-dashed border-[var(--border-glass)] text-center text-xs opacity-50 italic">
                            No active backlinks mapped for this node.
                        </div>
                    `;
                }

            } else {
                // Keep server-side lookup/rendering errors inside the reading pane.
                contentArea.innerHTML = `
                    <div class="p-5 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400">
                        <h4 class="font-bold mb-1">Core Link Interrupted</h4>
                        <p class="text-xs opacity-80">${window.escapeHtml(data.msg)}</p>
                    </div>
                `;
            }
        } catch (error) {
            console.error('API Transmission failure:', error);
            contentArea.innerHTML = `
                <div class="p-5 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400">
                    <h4 class="font-bold mb-1">Network Synchronization Loss</h4>
                    <p class="text-xs opacity-80">Failed to establish handshake pipeline with server cluster.</p>
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
    console.log("Проверяем наличие внешнего параметра 'file':", encodedFile);

    if (encodedFile) {
        try {
            // Decode the requested filename and normalize its optional extension.
            const requestedFile = decodeURIComponent(encodedFile).trim();
            const cleanRequestedName = requestedFile.replace(/\.md$/i, '').trim();

            console.log("Пытаемся открыть заметку:", cleanRequestedName);

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
                console.log("Заметка найдена! Кликаем.");

                // Bring the matching item into view before triggering its normal handler.
                requestedItem.scrollIntoView({ behavior: 'smooth', block: 'center' });

                // Reuse the regular click flow to load note content and backlinks.
                requestedItem.click();

                // Remove the one-time parameter so a later reload does not reopen it.
                const newUrl = new URL(window.location.href);
                newUrl.searchParams.delete('file');
                window.history.replaceState({}, document.title, newUrl);
            } else {
                console.warn(`Файл '${cleanRequestedName}' не найден в File Explorer. Проверь классы и текст.`);
            }
        } catch (error) {
            console.error('Ошибка при обработке ссылки:', error);
        }
    }

});