/*
 * Dashboard interactions for global note search and AI-generated status reports.
 * Search transfers a pending prompt to chat through sessionStorage; the report
 * calls the chat API in "report" mode: the SMART model answers, nothing is
 * stored in the chat history and no memory is sent (Q3).
 */
document.addEventListener('DOMContentLoaded', () => {

    // Route a non-empty Enter-submitted query to chat without placing it in the URL.
    const searchInput = document.getElementById('global-search-input');
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const query = searchInput.value.trim();
                if (query) {
                    sessionStorage.setItem('pending_ai_query', query);
                    window.location.href = '/chat/';
                }
            }
        });
    }

    const reportBtn = document.getElementById('generate-report-btn');
    const reportOutput = document.getElementById('ai-report-output');
    const lastModel = document.querySelector('[data-last-model]');

    if (reportBtn && reportOutput) {
        reportBtn.addEventListener('click', async () => {
            reportBtn.disabled = true;
            reportBtn.textContent = 'Generating…';
            reportOutput.classList.remove('hidden', 'text-danger');
            reportOutput.replaceChildren();
            const loading = document.createElement('span');
            loading.className = 'inline-flex items-center gap-2 text-accent';
            loading.innerHTML = '<span class="spinner" aria-hidden="true"></span>';
            loading.append('Consulting the AI…');
            reportOutput.appendChild(loading);

            try {
                const response = await fetch('/api/send-message/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify({
                        message: 'Based on my vault, write a very short, 2-sentence motivational daily briefing.',
                        mode: 'report'
                    })
                });
                const data = await response.json();
                if (data.status !== 'ok') throw new Error(data.msg || 'API Rejection');
                // Escaped text: replies may contain HTML from notes or the LLM (B-09).
                reportOutput.innerHTML = window.escapeHtml(data.reply).replace(/\n/g, '<br>');
                if (String(data.reply).startsWith('System ')) reportOutput.classList.add('text-warning');
                if (lastModel && data.model) lastModel.textContent = data.model;
                reportBtn.textContent = 'Report Updated';
            } catch (error) {
                console.error('Report Generation Error:', error);
                reportOutput.textContent = 'Could not reach the AI. Please try again.';
                reportOutput.classList.add('text-danger');
                reportBtn.textContent = 'Retry Generation';
            } finally {
                reportBtn.disabled = false;
            }
        });
    }
});
