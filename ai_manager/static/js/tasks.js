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

    if (openButton) openButton.addEventListener('click', () => setModal(true));
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
            const payload = {
                title: document.getElementById('task-title').value,
                priority: document.getElementById('task-priority').value,
                due_date: document.getElementById('task-date').value,
                tags: document.getElementById('task-tags').value
            };
            if (submit) submit.disabled = true;
            try {
                const response = await fetch('/api/add-task/', {
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
                const message = `Failed to create task: ${data.msg || response.status}`;
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
