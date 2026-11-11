/*
 * AI chat page controller: message submission, the "Choose notes" modal and
 * the search scope (Q12: no selection = whole vault; a selection narrows it;
 * "Reset" returns to the whole vault). Optional "Smart answer" sends smart=true
 * (GEMINI_MODEL_SMART). Retrieval, memory and persistence happen on the server.
 */
document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('.chat-input-form');
    const input = document.getElementById('chat-input');
    const chatFeed = document.getElementById('chat-feed');
    const contextList = document.getElementById('context-file-list');
    const contextMode = document.getElementById('context-mode');
    const contextModal = document.getElementById('context-modal');
    const addDocumentsButton = document.getElementById('add-documents-button');
    const resetButton = document.getElementById('reset-context-button');
    const closeContextModalButton = document.getElementById('close-context-modal');
    const applyContextButton = document.getElementById('apply-context-button');
    const selectedFilesCount = document.getElementById('selected-files-count');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const smartToggle = document.getElementById('smart-answer-toggle');
    const fileCheckboxes = Array.from(document.querySelectorAll('.file-checkbox'));
    const totalNotes = fileCheckboxes.length;
    let selectedFiles = getSelectedFiles();
    let lastFocus = null;

    // Jump to the newest message on load; later messages scroll smoothly.
    function scrollToBottom(smooth) {
        if (!chatFeed) return;
        const behavior = smooth && !(window.prefersReducedMotion && window.prefersReducedMotion()) ? 'smooth' : 'auto';
        chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior });
    }
    scrollToBottom(false);

    function getSelectedFiles() {
        return fileCheckboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
    }

    // Keep the displayed count and Select All control consistent with file choices.
    function updateSelectedFilesCount() {
        const checkedCount = fileCheckboxes.filter((checkbox) => checkbox.checked).length;
        if (selectedFilesCount) selectedFilesCount.textContent = `${checkedCount} selected`;
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = totalNotes > 0 && checkedCount === totalNotes;
            selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < totalNotes;
        }
    }

    // Scope label + desktop list, built with DOM nodes (filenames are never HTML).
    function renderContextFiles() {
        const count = selectedFiles.length;
        if (contextMode) {
            contextMode.textContent = count
                ? `Selected: ${count} ${count === 1 ? 'note' : 'notes'}`
                : 'Searching the whole vault';
        }
        if (resetButton) resetButton.classList.toggle('hidden', count === 0);
        if (!contextList) return;
        contextList.replaceChildren();

        if (!count) {
            const emptyState = document.createElement('li');
            emptyState.className = 'empty-state';
            emptyState.textContent = `All ${totalNotes} notes are searched.`;
            contextList.appendChild(emptyState);
            return;
        }

        selectedFiles.forEach((file) => {
            const item = document.createElement('li');
            const link = document.createElement('a');
            link.href = `/notes/?file=${encodeURIComponent(file)}`;
            link.className = 'glass-card rounded-lg p-3 flex items-center gap-3 hover:border-accent transition-colors min-w-0';
            const icon = document.createElement('span');
            icon.setAttribute('aria-hidden', 'true');
            icon.textContent = '📄';
            const name = document.createElement('span');
            name.className = 'font-medium text-fg text-sm truncate min-w-0';
            name.textContent = `${file}.md`;
            link.append(icon, name);
            item.appendChild(link);
            contextList.appendChild(item);
        });
    }

    // The modal shows the applied selection each time it opens.
    function setContextModalOpen(isOpen) {
        if (!contextModal) return;
        if (isOpen === !contextModal.classList.contains('hidden')) return;
        contextModal.classList.toggle('hidden', !isOpen);
        window.lockScroll && window.lockScroll(isOpen);
        if (isOpen) {
            lastFocus = document.activeElement;
            fileCheckboxes.forEach((checkbox) => { checkbox.checked = selectedFiles.includes(checkbox.value); });
            updateSelectedFilesCount();
            (closeContextModalButton || contextModal).focus();
        } else if (lastFocus) {
            lastFocus.focus();
        }
    }

    fileCheckboxes.forEach((checkbox) => checkbox.addEventListener('change', updateSelectedFilesCount));
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', () => {
            fileCheckboxes.forEach((checkbox) => { checkbox.checked = selectAllCheckbox.checked; });
            updateSelectedFilesCount();
        });
    }

    if (addDocumentsButton) addDocumentsButton.addEventListener('click', () => setContextModalOpen(true));
    if (closeContextModalButton) closeContextModalButton.addEventListener('click', () => setContextModalOpen(false));
    if (contextModal) contextModal.addEventListener('click', (e) => { if (e.target === contextModal) setContextModalOpen(false); });
    if (applyContextButton) {
        applyContextButton.addEventListener('click', () => {
            selectedFiles = getSelectedFiles();
            renderContextFiles();
            setContextModalOpen(false);
        });
    }
    if (resetButton) {
        resetButton.addEventListener('click', () => {
            fileCheckboxes.forEach((checkbox) => { checkbox.checked = false; });
            selectedFiles = [];
            updateSelectedFilesCount();
            renderContextFiles();
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') setContextModalOpen(false);
    });
    updateSelectedFilesCount();
    renderContextFiles();

    if (!form) return;

    // A query initiated from the dashboard is consumed once after navigation.
    const pendingQuery = sessionStorage.getItem('pending_ai_query');
    if (pendingQuery && input) {
        sessionStorage.removeItem('pending_ai_query');
        input.value = pendingQuery;
        setTimeout(() => form.dispatchEvent(new Event('submit', { cancelable: true })), 300);
    }

    let sending = false;
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = input.value.trim();
        if (!message || sending) return;
        sending = true;

        appendMessage('user', message);
        input.value = '';
        resizeInput();
        const loadingId = appendMessage('ai', null);

        try {
            const response = await fetch('/api/send-message/', {
                method: 'POST',
                headers: window.jsonHeaders(),
                body: JSON.stringify({
                    message: message,
                    selected_files: selectedFiles,
                    smart: Boolean(smartToggle && smartToggle.checked)
                })
            });
            const data = await response.json();
            // Show the server's error text instead of throwing on a missing reply (B-18).
            const text = data.reply || data.message || `⚠️ ${data.msg || 'The AI request was rejected.'}`;
            updateMessage(loadingId, text, data.model);
            if (data.model) {
                document.querySelectorAll('[data-last-model]').forEach((el) => { el.textContent = data.model; });
            }
        } catch (error) {
            updateMessage(loadingId, '❌ Connection to the AI failed. Check your network and try again.');
            console.error(error);
        } finally {
            sending = false;
        }
    });

    function isNotice(text) {
        return /^(System |⚠️|❌)/.test(String(text || ''));
    }

    // Create a chat bubble; text === null renders the "typing" indicator.
    function appendMessage(sender, text) {
        const id = 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 11);
        const isAI = sender === 'ai';
        const article = document.createElement('article');
        article.id = id;
        article.className = `flex gap-2 sm:gap-4 w-full ${isAI ? 'self-start' : 'self-end flex-row-reverse'}`;

        const avatar = document.createElement('div');
        avatar.className = 'text-xl sm:text-2xl mt-1';
        avatar.setAttribute('aria-hidden', 'true');
        avatar.textContent = isAI ? '✨' : '👤';

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble glass-card rounded-2xl p-3 sm:p-4 max-w-[85%] ' + (isAI
            ? 'rounded-tl-none border-accent shadow-[var(--glow-active)]'
            : 'rounded-tr-none bg-accent/10 border border-accent');
        const p = document.createElement('p');
        p.className = 'text-fg leading-relaxed';
        if (text === null) {
            p.innerHTML = '<span class="typing-dots" role="status" aria-label="The AI is thinking"><span></span><span></span><span></span></span>';
        } else {
            p.innerHTML = window.escapeHtml(text).replace(/\n/g, '<br>');
        }
        bubble.appendChild(p);
        article.append(avatar, bubble);
        chatFeed.appendChild(article);
        scrollToBottom(true);
        return id;
    }

    // Replace the content of an existing bubble identified by its generated DOM id.
    function updateMessage(id, text, model) {
        const msgEl = document.getElementById(id);
        if (!msgEl) return;
        const bubble = msgEl.querySelector('.chat-bubble');
        // Escape before inserting: replies may contain HTML from notes or the LLM (B-09).
        msgEl.querySelector('p').innerHTML = window.escapeHtml(text).replace(/\n/g, '<br>');
        bubble.classList.toggle('is-notice', isNotice(text));
        if (model && !isNotice(text)) {
            const meta = document.createElement('p');
            meta.className = 'mt-2 text-xs text-muted';
            meta.textContent = model;
            bubble.appendChild(meta);
        }
        scrollToBottom(true);
    }

    function resizeInput() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 160) + 'px';
        if (input.value === '') input.style.height = '';
    }

    if (input) {
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                form.requestSubmit();
            }
        });
        input.addEventListener('input', resizeInput);
        // When the on-screen keyboard opens, keep the newest message visible.
        input.addEventListener('focus', () => setTimeout(() => scrollToBottom(false), 300));
    }
});
