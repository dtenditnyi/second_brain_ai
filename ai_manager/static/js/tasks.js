/*
 * Task-board controller for status toggles and modal-based task creation.
 * It posts small JSON payloads to Django task endpoints, then refreshes the server-
 * rendered lists so ordering and status grouping remain authoritative.
 */
document.addEventListener('DOMContentLoaded', () => {
    
    // A checkbox maps directly to the task's done/todo state; reload after success
    // so the task moves between the server-rendered active and completed sections.
    const checkboxes = document.querySelectorAll('.task-checkbox');
    checkboxes.forEach(box => {
        box.addEventListener('change', async (e) => {
            const taskId = e.target.getAttribute('data-id');
            const newStatus = e.target.checked ? 'done' : 'todo';
            
            try {
                const response = await fetch('/api/update-task/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify({ task_id: taskId, status: newStatus })
                });
                
                if (response.ok) {
                    // Reload to reflect server-side grouping and status-dependent markup.
                    window.location.reload(); 
                }
            } catch (error) {
                console.error('Error updating task:', error);
                e.target.checked = !e.target.checked; // Restore the previous checkbox state if persistence failed.
            }
        });
    });

    // Serialize modal fields into the task-creation API and close/reload on success.
    const addTaskForm = document.getElementById('add-task-form');
    if (addTaskForm) {
        addTaskForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const payload = {
                title: document.getElementById('task-title').value,
                priority: document.getElementById('task-priority').value,
                due_date: document.getElementById('task-date').value,
                tags: document.getElementById('task-tags').value
            };

            try {
                const response = await fetch('/api/add-task/', {
                    method: 'POST',
                    headers: window.jsonHeaders(),
                    body: JSON.stringify(payload)
                });
                
                if (response.ok) {
                    // Close modal and refresh to show new task
                    document.getElementById('task-modal').classList.add('hidden');
                    window.location.reload();
                }
            } catch (error) {
                console.error('Error creating task:', error);
                alert("Failed to create task.");
            }
        });
    }
});