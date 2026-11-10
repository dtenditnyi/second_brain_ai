/*
 * AI chat page controller for message submission and document-context selection.
 * It coordinates the modal checkboxes, selected-file preview, local UI history,
 * and the JSON chat API; retrieval and persistence are handled by Django/RAG.
 */
document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('.chat-input-form');
    const input = document.getElementById('chat-input');
    const chatFeed = document.getElementById('chat-feed');
    const contextList = document.getElementById('context-file-list');
    const contextModal = document.getElementById('context-modal');
    const addDocumentsButton = document.getElementById('add-documents-button');
    const closeContextModalButton = document.getElementById('close-context-modal');
    const applyContextButton = document.getElementById('apply-context-button');
    const contextModalBackdrop = document.getElementById('context-modal-backdrop');
    const selectedFilesCount = document.getElementById('selected-files-count');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const fileCheckboxes = Array.from(document.querySelectorAll('.file-checkbox'));
    let selectedFiles = getSelectedFiles();

    if (chatFeed) {
        chatFeed.scrollTop = chatFeed.scrollHeight;
    }

    // Read the current checkbox state when the user applies context or submits chat.
    function getSelectedFiles() {
        return Array.from(document.querySelectorAll('#document-selector input[type="checkbox"]:checked'))
            .map((checkbox) => checkbox.value);
    }

    // Keep the displayed count and Select All control consistent with file choices.
    function updateSelectedFilesCount() {
        const checkedCount = fileCheckboxes.filter((checkbox) => checkbox.checked).length;
        if (selectedFilesCount) {
            selectedFilesCount.textContent = `${checkedCount} selected`;
        }
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = fileCheckboxes.length > 0 && checkedCount === fileCheckboxes.length;
        }
    }

    // Rebuild the sidebar context list using DOM nodes to avoid interpreting filenames as HTML.
    function renderContextFiles() {
        if (!contextList) return;
        contextList.replaceChildren();

        if (!selectedFiles.length) {
            const emptyState = document.createElement('li');
            emptyState.className = 'text-sm opacity-60 italic';
            emptyState.textContent = 'All documents';
            contextList.appendChild(emptyState);
            return;
        }

        selectedFiles.forEach((file) => {
            const item = document.createElement('li');
            const link = document.createElement('a');
            link.href = `/notes/?file=${encodeURIComponent(file)}`;
            link.className = 'glass-card rounded-lg p-3 flex items-center gap-3 cursor-pointer hover:bg-gray-800 transition-colors';

            const icon = document.createElement('span');
            icon.className = 'text-xl';
            icon.textContent = '📄';
            const details = document.createElement('div');
            details.className = 'flex flex-col';
            const name = document.createElement('span');
            name.className = 'font-medium text-[var(--text-primary)] text-sm truncate w-48';
            name.textContent = `${file}.md`;
            const type = document.createElement('span');
            type.className = 'text-xs opacity-60 uppercase tracking-wide';
            type.textContent = 'note';
            details.append(name, type);
            link.append(icon, details);
            item.appendChild(link);
            contextList.appendChild(item);
        });
    }

    // Toggle modal visibility and prevent background document scrolling while open.
    function setContextModalOpen(isOpen) {
        if (!contextModal) return;
        contextModal.classList.toggle('hidden', !isOpen);
        contextModal.classList.toggle('flex', isOpen);
        document.body.classList.toggle('overflow-hidden', isOpen);
        if (isOpen) updateSelectedFilesCount();
    }

    fileCheckboxes.forEach((checkbox) => {
        checkbox.addEventListener('change', updateSelectedFilesCount);
    });

    // Bulk selection updates every note checkbox, then runs the same counter sync
    // used by individual file changes.
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', () => {
            fileCheckboxes.forEach((checkbox) => {
                checkbox.checked = selectAllCheckbox.checked;
            });
            updateSelectedFilesCount();
        });
    }

    if (addDocumentsButton) addDocumentsButton.addEventListener('click', () => setContextModalOpen(true));
    if (closeContextModalButton) closeContextModalButton.addEventListener('click', () => setContextModalOpen(false));
    if (contextModalBackdrop) contextModalBackdrop.addEventListener('click', () => setContextModalOpen(false));
    // Apply remains the commit point: only here is the sidebar context list refreshed.
    if (applyContextButton) {
        applyContextButton.addEventListener('click', () => {
            selectedFiles = getSelectedFiles();
            renderContextFiles();
            setContextModalOpen(false);
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') setContextModalOpen(false);
    });
    updateSelectedFilesCount();

    if (!form) return;

    // A query initiated from the dashboard is consumed once after navigation.
    const pendingQuery = sessionStorage.getItem('pending_ai_query');
    if (pendingQuery && input) {
        // Clear memory to prevent endless loops on reload
        sessionStorage.removeItem('pending_ai_query');

        // Inject string and artificially trigger form submission
        input.value = pendingQuery;

        // Use a slight timeout for visual smoothness (simulating typing)
        setTimeout(() => {
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }, 300);
    }

    // Append the user turn optimistically, request an answer, then replace the
    // temporary assistant status with the response or a connection error.
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const message = input.value.trim();
        if (!message) return;

        // Draw User message
        appendMessage('user', message);
        input.value = '';

        // Draw AI loading placeholder
        const loadingId = appendMessage('ai', 'Processing logical cores...');

        try {
            const response = await fetch('/api/send-message/', {
                method: 'POST',
                headers: window.jsonHeaders(),
                body: JSON.stringify({ message: message, selected_files: selectedFiles })
            });

            const data = await response.json();
            // Show the server's error text instead of throwing on a missing reply (B-18).
            updateMessage(loadingId, data.reply || data.message || `⚠️ ${data.msg || 'The AI request was rejected.'}`);

        } catch (error) {
            updateMessage(loadingId, '❌ Connection to local AI core failed.');
            console.error(error);
        }
    });

    // Create a chat bubble for either participant and scroll the feed to the latest turn.
    function appendMessage(sender, text) {
        const id = 'msg-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
        const isAI = sender === 'ai';
        const avatar = isAI ? '✨' : '👤';

        // Use Tailwind / Glassmorphism logic based on sender
        const alignmentClass = isAI ? 'self-start' : 'self-end flex-row-reverse';
        const bubbleStyle = isAI
            ? 'rounded-tl-none border-[var(--active-accent)] shadow-[var(--glow-active)]'
            : 'rounded-tr-none bg-[var(--active-accent)] bg-opacity-10 border border-[var(--active-accent)]';

        const html = `
            <article class="flex gap-4 w-full ${alignmentClass}" id="${id}">
                <div class="text-2xl mt-1">${avatar}</div>
                <div class="glass-card rounded-2xl p-4 max-w-[85%] ${bubbleStyle}">
                    <p class="text-[var(--text-primary)] leading-relaxed">${window.escapeHtml(text).replace(/\n/g, '<br>')}</p>
                </div>
            </article>
        `;

        chatFeed.insertAdjacentHTML('beforeend', html);
        chatFeed.scrollTop = chatFeed.scrollHeight;
        return id;
    }

    // Replace the content of an existing bubble identified by its generated DOM id.
    function updateMessage(id, text) {
        const msgEl = document.getElementById(id);
        if (msgEl) {
            // Escape before inserting: replies may contain HTML from notes or the LLM (B-09).
            msgEl.querySelector('p').innerHTML = window.escapeHtml(text).replace(/\n/g, '<br>');
        }
    }

    // Auto-resize textarea and submit on Enter
    if (input) {
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                form.requestSubmit();
            }
        });

        input.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            if (this.value === '') this.style.height = '60px'; // Reset to min-height
        });
    }
});