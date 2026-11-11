/*
 * Task controller (Tasks page + Home board): status changes, completion
 * checkboxes and the "Create New Task" modal. Changes are posted to the task
 * API; the page then reloads so the server-rendered grouping stays authoritative.
 * Unchecking "done" returns a task to "To Do" (see docs/audit/DECISIONS.md);
 * any status can be chosen explicitly with the status select (Q10).
 */
document.addEventListener('DOMContentLoaded', () => {

    async function updateStatus(taskId, status) {
        const response = await fetch('/api/update-task/', {
            method: 'POST',
            headers: window.jsonHeaders(),
            body: JSON.stringify({ task_id: taskId, status: status })
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.msg || `HTTP ${response.status}`);
        }
    }

    function showError(message) {
        let toast = document.getElementById('task-error-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'task-error-toast';
            toast.setAttribute('role', 'alert');
            toast.className = 'alert alert-danger fixed z-[70] left-1/2 -translate-x-1/2 shadow-lg max-w-[90vw]';
            toast.style.bottom = 'max(1rem, env(safe-area-inset-bottom))';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => toast.remove(), 5000);
    }

    // Checkbox: checked → done, unchecked → todo; reverted when the server refuses.
    document.querySelectorAll('.task-checkbox').forEach((box) => {
        box.addEventListener('change', async (e) => {
            const target = e.target;
            const newStatus = target.checked ? 'done' : 'todo';
            target.disabled = true;
            try {
                await updateStatus(target.getAttribute('data-id'), newStatus);
                window.location.reload();
            } catch (error) {
                // Restore the checkbox when the server rejects the change (B-18).
                target.checked = !target.checked;
                target.disabled = false;
                console.error('Task update rejected:', error);
                showError(`Could not update the task: ${error.message}`);
            }
        });
    });

    // Status select: To Do / In Progress / Done.
    document.querySelectorAll('.task-status-select').forEach((select) => {
        select.addEventListener('change', async () => {
            const previous = select.dataset.current;
            select.disabled = true;
            try {
                await updateStatus(select.dataset.id, select.value);
                select.dataset.current = select.value;
                window.location.reload();
            } catch (error) {
                select.value = previous;
                select.disabled = false;
                console.error('Task status update rejected:', error);
                showError(`Could not change the status: ${error.message}`);
            }
        });
    });

    // --- "Create New Task" modal ---------------------------------------------
    const modal = document.getElementById('task-modal');
    const openButton = document.getElementById('open-task-modal');
    let lastFocus = null;

    function setModal(open) {
        if (!modal) return;
        if (open === !modal.classList.contains('hidden')) return;
        modal.classList.toggle('hidden', !open);
        window.lockScroll && window.lockScroll(open);
        if (open) {
            lastFocus = document.activeElement;
            const title = document.getElementById('task-title');
            if (title) title.focus();
        } else if (lastFocus) {
            lastFocus.focus();
        }
    }

    const fieldIds = { id: 'task-id', title: 'task-title', priority: 'task-priority', due: 'task-date', tags: 'task-tags' };
    const field = (key) => document.getElementById(fieldIds[key]);

    // Same dialog for "create" and "edit" (Round 3 / G-C7).
    function openForm(card) {
        const heading = document.getElementById('task-modal-title');
        const errorBox = document.getElementById('task-form-error');
        if (errorBox) errorBox.classList.add('hidden');
        field('id').value = card ? card.dataset.id : '';
        field('title').value = card ? card.dataset.title : '';
        field('priority').value = card ? (card.dataset.priority || 'medium') : 'medium';
        field('due').value = card ? (card.dataset.due || '') : '';
        field('tags').value = card ? (card.dataset.tags || '') : '';
        if (heading) heading.textContent = card ? 'Edit Task' : 'Create New Task';
        setModal(true);
    }

    if (openButton) openButton.addEventListener('click', () => openForm(null));
    document.querySelectorAll('.task-edit').forEach((btn) => btn.addEventListener('click', () => openForm(btn.closest('.task-card'))));

    // Delete with confirmation; the line is removed from the tasks note.
    document.querySelectorAll('.task-delete').forEach((btn) => btn.addEventListener('click', async () => {
        const card = btn.closest('.task-card');
        if (!window.confirm(`Delete the task "${card.dataset.title}"? This cannot be undone.`)) return;
        btn.disabled = true;
        try {
            const response = await fetch('/api/delete-task/', {
                method: 'POST', headers: window.jsonHeaders(), body: JSON.stringify({ task_id: card.dataset.id })
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.msg || `HTTP ${response.status}`);
            }
            window.location.reload();
        } catch (error) {
            btn.disabled = false;
            showError(`Could not delete the task: ${error.message}`);
        }
    }));

    // "Refresh": pull the tasks note now.
    const refresh = document.getElementById('tasks-refresh');
    if (refresh) refresh.addEventListener('click', async () => {
        refresh.disabled = true;
        refresh.textContent = 'Syncing…';
        try {
            const response = await fetch('/api/tasks/sync/', { method: 'POST', headers: window.jsonHeaders() });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
            window.location.reload();
        } catch (error) {
            refresh.disabled = false;
            refresh.textContent = '↻ Refresh';
            showError(`Sync failed: ${error.message}`);
        }
    });
    document.querySelectorAll('[data-close-task-modal]').forEach((el) => el.addEventListener('click', () => setModal(false)));
    if (modal) {
        modal.addEventListener('click', (e) => { if (e.target === modal) setModal(false); });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !modal.classList.contains('hidden')) setModal(false);
        });
    }

    const addTaskForm = document.getElementById('add-task-form');
    if (addTaskForm) {
        addTaskForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submit = addTaskForm.querySelector('button[type=submit]');
            const errorBox = document.getElementById('task-form-error');
            const editingId = field('id') ? field('id').value : '';
            const payload = {
                title: document.getElementById('task-title').value,
                priority: document.getElementById('task-priority').value,
                due_date: document.getElementById('task-date').value,
                tags: document.getElementById('task-tags').value
            };
            if (editingId) payload.task_id = editingId;
            if (submit) submit.disabled = true;
            try {
                const response = await fetch(editingId ? '/api/update-task/' : '/api/add-task/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify(payload)
                });
                if (response.ok) {
                    setModal(false);
                    window.location.reload();
                    return;
                }
                // Report validation errors instead of silently keeping the modal open (B-18).
                const data = await response.json().catch(() => ({}));
                const message = `Failed to ${editingId ? 'save' : 'create'} task: ${data.msg || response.status}`;
                if (errorBox) { errorBox.textContent = message; errorBox.classList.remove('hidden'); }
            } catch (error) {
                console.error('Error creating task:', error);
                if (errorBox) { errorBox.textContent = 'Failed to create task (connection error).'; errorBox.classList.remove('hidden'); }
            } finally {
                if (submit) submit.disabled = false;
            }
        });
    }
});
