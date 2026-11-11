/* API tokens in Settings (Round 4 / G-API1): create (shown once) and revoke. */
document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('token-create-button');
    if (!createBtn) return;
    const errorBox = document.getElementById('token-error');
    const lines = (id) => document.getElementById(id).value.split('\n').map((s) => s.trim()).filter(Boolean);

    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.classList.remove('hidden');
    }

    async function post(url, payload) {
        const response = await fetch(url, { method: 'POST', headers: window.jsonHeaders(), body: JSON.stringify(payload) });
        let data = {};
        try { data = await response.json(); } catch (e) { /* not JSON */ }
        return { ok: response.ok, data };
    }

    createBtn.addEventListener('click', async () => {
        errorBox.classList.add('hidden');
        const scopes = [...document.querySelectorAll('input[name="token-scope"]:checked')].map((i) => i.value);
        const expires = document.getElementById('token-expires').value.trim();
        const result = await post('/api/tokens/create/', {
            name: document.getElementById('token-name').value.trim(),
            scopes,
            expires_days: expires ? Number(expires) : null,
            write_paths: lines('token-write-paths'),
            delete_paths: lines('token-delete-paths'),
        });
        if (!result.ok) { showError(result.data.msg || 'Не удалось создать токен.'); return; }
        document.getElementById('token-value').textContent = result.data.token;
        document.getElementById('token-created').classList.remove('hidden');
        createBtn.disabled = true;
        createBtn.textContent = 'Created — reload the page to see it in the list';
    });

    document.querySelectorAll('[data-revoke-token]').forEach((btn) => btn.addEventListener('click', async () => {
        if (!window.confirm('Отозвать токен? Клиенты с ним сразу перестанут работать.')) return;
        const result = await post('/api/tokens/revoke/', { id: Number(btn.dataset.revokeToken) });
        if (result.ok) window.location.reload();
        else showError(result.data.msg || 'Не удалось отозвать токен.');
    }));
});
