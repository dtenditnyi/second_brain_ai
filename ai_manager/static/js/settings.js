/*
 * Settings-page controller for live appearance previews and preference persistence.
 * Sends display name (not the login, Q6), email, theme, accent, AI strategy,
 * temperature, repository URL and — only when typed — a new GitHub token (Q7).
 * An empty token field keeps the saved token; "Delete the saved token" removes it.
 */
document.addEventListener('DOMContentLoaded', () => {
    const tempSlider = document.getElementById('ai-temperature');
    const tempValue = document.getElementById('temp-value');
    const themeSelect = document.getElementById('theme-select');
    const accentRadios = document.querySelectorAll('input[name="accent-color"]');
    const saveBtn = document.getElementById('save-settings-button');
    const statusBox = document.getElementById('settings-status');
    const tokenInput = document.getElementById('github-token');
    const clearToken = document.getElementById('clear-github-token');
    const idleLabel = 'Save System Configuration';

    if (tempSlider && tempValue) {
        tempSlider.addEventListener('input', (e) => { tempValue.textContent = e.target.value; });
    }
    // Preview theme/accent on the root element before the server persists them.
    if (themeSelect) {
        themeSelect.addEventListener('change', (e) => {
            document.documentElement.setAttribute('data-theme', e.target.value);
            const scheme = document.querySelector('meta[name="color-scheme"]');
            if (scheme) scheme.content = e.target.value === 'light' ? 'light' : 'dark';
        });
    }
    accentRadios.forEach((radio) => {
        radio.addEventListener('change', (e) => document.documentElement.setAttribute('data-accent', e.target.value));
    });
    // Typing a new token and deleting the old one are mutually exclusive.
    if (clearToken && tokenInput) {
        clearToken.addEventListener('change', () => {
            tokenInput.disabled = clearToken.checked;
            if (clearToken.checked) tokenInput.value = '';
        });
    }

    function showStatus(kind, text) {
        if (!statusBox) return;
        statusBox.className = `alert alert-${kind}`;
        statusBox.textContent = text;
    }

    if (!saveBtn) return;
    saveBtn.addEventListener('click', async () => {
        saveBtn.textContent = 'Saving…';
        saveBtn.disabled = true;

        let selectedAccent = 'cyan';
        accentRadios.forEach((radio) => { if (radio.checked) selectedAccent = radio.value; });

        const config = {
            display_name: document.getElementById('display-name')?.value ?? '',
            email: document.getElementById('email-address')?.value || '',
            theme: themeSelect?.value || 'cyberpunk',
            accent_color: selectedAccent,
            ai_strategy: document.getElementById('ai-strategy')?.value || 'auto',
            temperature: tempSlider?.value || 0.7,
            github_repo_url: document.getElementById('github-repo')?.value || '',
            github_token: tokenInput?.value || '',
            clear_github_token: Boolean(clearToken && clearToken.checked),
            tasks_note_path: document.getElementById('tasks-note-path')?.value ?? ''
        };

        try {
            const response = await fetch('/api/save-settings/', {
                method: 'POST',
                headers: window.jsonHeaders(),
                body: JSON.stringify(config)
            });
            const data = await response.json();
            saveBtn.disabled = false;
            if (data.status === 'ok') {
                saveBtn.textContent = 'Configuration Saved Successfully';
                showStatus('success', 'Settings saved.');
                // The token is never shown again; the field returns to empty.
                if (tokenInput && (config.github_token || config.clear_github_token)) {
                    tokenInput.value = '';
                    tokenInput.placeholder = config.clear_github_token ? 'ghp_… or github_pat_…' : 'Token saved — leave empty to keep it';
                    const tokenStatus = document.getElementById('token-status');
                    if (tokenStatus) tokenStatus.textContent = config.clear_github_token ? 'Token deleted.' : 'Token saved — leave the field empty to keep it.';
                }
                setTimeout(() => { saveBtn.textContent = idleLabel; }, 3000);
            } else {
                // Surface validation errors instead of leaving "Saving…" (B-18).
                saveBtn.textContent = `Error: ${data.msg || 'configuration rejected'}`;
                showStatus('danger', data.msg || 'The configuration was rejected.');
                setTimeout(() => { saveBtn.textContent = idleLabel; }, 4000);
            }
        } catch (error) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Error Saving Configuration';
            showStatus('danger', 'Could not reach the server. Please try again.');
            console.error(error);
        }
    });
});
