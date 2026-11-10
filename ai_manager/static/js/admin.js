/*
 * Administrative dashboard controller for the Core Matrix interface.
 * It switches between model tables and sends row-level create-free updates or
 * deletions to the superuser API endpoints; the server remains authoritative.
 */
document.addEventListener('DOMContentLoaded', () => {
    
    // Initialize table navigation only after the page DOM is ready. Tab buttons
    // identify their target table through data-tab attributes.
    // --- PART 1: DATATABLE NAVIGATOR ROUTING (TAB SWITCHING) ---
    const tabButtons = document.querySelectorAll('.tab-btn');
    const sections = document.querySelectorAll('.table-section');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');

            // Reset navigation layouts
            tabButtons.forEach(b => b.classList.remove('bg-purple-500', 'bg-opacity-10', 'text-white', 'text-purple-400', 'shadow-[0_0_15px_rgba(176,38,255,0.1)]', 'border', 'border-purple-500', 'border-opacity-20'));
            tabButtons.forEach(b => b.classList.add('text-gray-400', 'hover:bg-[var(--bg-glass)]', 'hover:text-white'));
            sections.forEach(s => s.classList.replace('block', 'hidden'));

            // Toggle active tracking view
            btn.classList.replace('text-gray-400', 'text-white');
            btn.classList.add('bg-purple-500', 'bg-opacity-10', 'shadow-[0_0_15px_rgba(176,38,255,0.1)]', 'border', 'border-purple-500', 'border-opacity-20');
            document.getElementById(targetTab)?.classList.replace('hidden', 'block');
        });
    });

    // Row actions serialize named controls and delegate persistence to the admin API.
    // --- PART 2: DYNAMIC AJAX DATABASE TRANSACTIONS ---
    
    // Commit edits from the clicked table row and reflect the server outcome inline.
    document.querySelectorAll('.save-row-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const row = btn.closest('tr');
            const tableElement = btn.closest('table');
            
            const tableModelName = tableElement.getAttribute('data-model');
            const rowId = row.getAttribute('data-id');
            
            // Use input names as JSON keys so the backend can map them to model fields.
            const inputs = row.querySelectorAll('input, select, textarea');
            const fieldsPayload = {};
            
            inputs.forEach(input => {
                fieldsPayload[input.name] = input.value;
            });

            btn.textContent = 'Syncing...';
            btn.style.backgroundColor = '#9333ea';

            try {
                const response = await fetch('/api/admin/update-row/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify({
                        table: tableModelName,
                        id: rowId,
                        fields: fieldsPayload
                    })
                });
                
                const data = await response.json();
                if (data.status === 'ok') {
                    btn.textContent = 'Success';
                    btn.style.backgroundColor = '#22c55e'; // Highlight green
                    setTimeout(() => {
                        btn.textContent = 'Commit';
                        btn.style.backgroundColor = '#a855f7'; // Reset purple
                    }, 2000);
                } else {
                    alert('Transaction failure: ' + data.msg);
                    btn.textContent = 'Error';
                    btn.style.backgroundColor = '#ef4444';
                }
            } catch (error) {
                console.error('Data transmission lost:', error);
                btn.textContent = 'Retry';
                btn.style.backgroundColor = '#ef4444';
            }
        });
    });

    // Confirm destructive actions before requesting deletion from the allowlisted API.
    document.querySelectorAll('.delete-row-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Are you absolutely sure you want to completely erase this row vector?')) return;
            
            const row = btn.closest('tr');
            const tableElement = btn.closest('table');
            
            const tableModelName = tableElement.getAttribute('data-model');
            const rowId = row.getAttribute('data-id');

            try {
                const response = await fetch('/api/admin/delete-row/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify({
                        table: tableModelName,
                        id: rowId
                    })
                });
                
                const data = await response.json();
                if (data.status === 'ok') {
                    // Remove row with collapse fade execution effect
                    row.style.opacity = '0';
                    setTimeout(() => row.remove(), 400);
                } else {
                    alert('System aborted transaction: ' + data.msg);
                }
            } catch (error) {
                console.error('Critical database execution loss:', error);
            }
        });
    });
});