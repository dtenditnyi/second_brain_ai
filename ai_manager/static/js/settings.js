/*
 * Settings-page controller for live appearance previews and preference persistence.
 * It gathers profile, theme, accent, AI strategy, temperature, and vault credentials,
 * then sends them to the authenticated save-settings JSON endpoint.
 */
document.addEventListener('DOMContentLoaded', () => {
    const tempSlider = document.getElementById('ai-temperature');
    const tempValue = document.getElementById('temp-value');
    const themeSelect = document.getElementById('theme-select');
    const accentRadios = document.querySelectorAll('input[name="accent-color"]');

    // Mirror the range input immediately so users can see the chosen sampling value.
    if (tempSlider && tempValue) {
        tempSlider.addEventListener('input', (e) => {
            tempValue.textContent = e.target.value;
        });
    }

    // Preview the theme on the root element before the server persists it.
    if (themeSelect) {
        themeSelect.addEventListener('change', (e) => {
            document.documentElement.setAttribute('data-theme', e.target.value);
        });
    }

    // Preview the selected accent token before the next page load.
    accentRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            document.documentElement.setAttribute('data-accent', e.target.value);
        });
    });

    // Add one page-level save action after the settings sections are rendered.
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn-primary w-full py-3 mt-8 rounded-lg font-bold uppercase tracking-wider text-sm';
    saveBtn.textContent = 'Save System Configuration';
    
    const container = document.querySelector('.settings-container');
    if (container) container.appendChild(saveBtn);

    saveBtn.addEventListener('click', async () => {
        saveBtn.textContent = 'Saving Cores...';
        
        // Read the checked radio because multiple accent choices share one control name.
        let selectedAccent = 'cyan';
        accentRadios.forEach(radio => {
            if (radio.checked) selectedAccent = radio.value;
        });

        // Preserve the API's expected field names in a single JSON request payload.
        const displayName = document.getElementById('display-name')?.value || '';
        const email = document.getElementById('email-address')?.value || '';
        const config = {
            username: displayName,
            display_name: displayName,
            email,
            theme: document.getElementById('theme-select')?.value || 'cyberpunk',
            accent_color: selectedAccent,
            ai_strategy: document.getElementById('ai-strategy')?.value || 'auto',
            temperature: tempSlider?.value || 0.7,
            github_repo_url: document.getElementById('github-repo')?.value || '',
            github_token: document.getElementById('github-token')?.value || ''
        };

        try {
            const response = await fetch('/api/save-settings/', {
                method: 'POST',
                headers: window.jsonHeaders(),
                body: JSON.stringify(config)
            });
            
            const data = await response.json();
            if (data.status === 'ok') {
                saveBtn.textContent = 'Configuration Saved Successfully';
                
                // Show transient success feedback without changing the saved settings.
                saveBtn.style.backgroundColor = 'var(--neon-green)';
                saveBtn.style.color = '#000';
                saveBtn.style.borderColor = 'var(--neon-green)';
                
                setTimeout(() => {
                    saveBtn.textContent = 'Save System Configuration';
                    saveBtn.style.backgroundColor = 'transparent';
                    saveBtn.style.color = 'var(--active-accent)';
                    saveBtn.style.borderColor = 'var(--active-accent)';
                }, 3000);
            }
        } catch (error) {
            saveBtn.textContent = 'Error Saving Configuration';
            console.error(error);
        }
    });
});