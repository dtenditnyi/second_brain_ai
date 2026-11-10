/*
 * Dashboard interactions for global note search and AI-generated status reports.
 * Search transfers a pending prompt to chat through sessionStorage; report requests
 * call the same authenticated chat API and render its response in the dashboard.
 */
document.addEventListener('DOMContentLoaded', () => {

    // Route a non-empty Enter-submitted query to chat without placing it in the URL.
    // --- 1. GLOBAL SEARCH TO AI CHAT PIPELINE ---
    const searchInput = document.getElementById('global-search-input');
    
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const query = searchInput.value.trim();
                if (query) {
                    // Temporarily store the query in browser session memory
                    sessionStorage.setItem('pending_ai_query', query);
                    
                    // Redirect operator to the AI Chat interface
                    window.location.href = '/chat/';
                }
            }
        });
    }

    // Request a short vault-based briefing and expose loading, success, or failure state.
    // --- 2. AI STATUS REPORT GENERATOR ---
    const reportBtn = document.getElementById('generate-report-btn');
    const reportOutput = document.getElementById('ai-report-output');

    if (reportBtn && reportOutput) {
        reportBtn.addEventListener('click', async () => {
            // Visual loading state
            reportBtn.textContent = 'Processing Matrices...';
            reportOutput.classList.remove('hidden');
            reportOutput.innerHTML = '<span class="text-[var(--active-accent)] animate-pulse font-mono uppercase tracking-widest text-[10px]">Consulting LLM Engine...</span>';
            
            try {
                // Send a silent background prompt to the AI API
                const response = await fetch('/api/send-message/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify({ 
                        message: "Based on my vault, write a very short, 2-sentence motivational daily briefing." 
                    })
                });
                
                const data = await response.json();
                if (data.status === 'ok') {
                    reportOutput.innerHTML = window.escapeHtml(data.reply).replace(/\n/g, '<br>');
                    reportBtn.textContent = 'Report Updated';
                } else {
                    throw new Error('API Rejection');
                }
            } catch (error) {
                console.error('Report Generation Error:', error);
                reportOutput.innerHTML = '<span class="text-red-400">Connection to AI Core severed.</span>';
                reportBtn.textContent = 'Retry Generation';
            }
        });
    }
});