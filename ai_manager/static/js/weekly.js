/* Round 5 (F3): weekly page — "Эта неделя", carry-over with diff preview, week calendar. */
(function () {
    const weeks = JSON.parse(document.getElementById('weeks-data').textContent || '[]');
    const status = document.getElementById('weekly-status');
    const byStart = new Map(weeks.map(w => [w.week_start, w]));
    let current = weeks.find(w => w.current) || null;

    async function postJson(url, body) {
        const res = await fetch(url, { method: 'POST', headers: window.jsonHeaders(), body: JSON.stringify(body) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.msg || 'HTTP ' + res.status);
        return data;
    }
    const noteUrl = path => '/notes/?path=' + encodeURIComponent(path);

    document.getElementById('this-week-btn').addEventListener('click', async e => {
        e.currentTarget.disabled = true;
        status.textContent = 'Открываю заметку этой недели…';
        try {
            const data = await postJson('/api/weekly/this-week/', {});
            window.location.href = noteUrl(data.path);
        } catch (err) {
            status.textContent = 'Не получилось: ' + err.message;
            e.currentTarget.disabled = false;
        }
    });

    // ---------------------------------------------------------------- carry over
    const modal = document.getElementById('carry-modal');
    const close = () => modal.classList.add('hidden');
    modal.querySelectorAll('[data-carry-close]').forEach(b => b.addEventListener('click', close));
    modal.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    document.getElementById('carry-btn').addEventListener('click', async () => {
        if (!current) return;
        status.textContent = 'Готовлю предпросмотр…';
        try {
            const data = await postJson('/api/weekly/carry-over/', { to: current.path, preview: true });
            document.getElementById('carry-summary').textContent = data.count
                ? `Из «${data.from.split('/').pop().replace(/\.md$/, '')}»: ${data.count} задач(и). В старой заметке они станут [>], в новой — добавятся.`
                : 'В прошлой неделе нет незакрытых задач.';
            document.getElementById('carry-diff').textContent = data.diff || '';
            document.getElementById('carry-apply').disabled = !data.count;
            status.textContent = '';
            modal.classList.remove('hidden');
            document.getElementById('carry-apply').focus();
        } catch (err) {
            status.textContent = 'Не получилось: ' + err.message;
        }
    });
    document.getElementById('carry-apply').addEventListener('click', async e => {
        e.currentTarget.disabled = true;
        try {
            const data = await postJson('/api/weekly/carry-over/', { to: current.path });
            close();
            status.innerHTML = `Перенесено задач: ${data.count}. <a class="text-accent underline" href="${noteUrl(data.to)}">Открыть неделю</a>`;
        } catch (err) {
            status.textContent = 'Не получилось: ' + err.message;
        }
    });

    // ---------------------------------------------------------------- calendar
    const months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
    const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const today = new Date();
    let view = new Date(today.getFullYear(), today.getMonth(), 1);
    function isoWeek(d) {
        const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
        const day = t.getUTCDay() || 7;
        t.setUTCDate(t.getUTCDate() + 4 - day);
        return Math.ceil(((t - Date.UTC(t.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
    }
    function draw() {
        document.getElementById('cal-title').textContent = `${months[view.getMonth()]} ${view.getFullYear()}`;
        const first = new Date(view);
        const start = new Date(first);
        start.setDate(first.getDate() - ((first.getDay() + 6) % 7));
        let html = '';
        for (let row = 0; row < 6; row++) {
            const monday = new Date(start);
            monday.setDate(start.getDate() + row * 7);
            if (row > 3 && monday.getMonth() !== view.getMonth()) break;
            const week = byStart.get(iso(monday));
            const label = week
                ? `<a href="${noteUrl(week.path)}" class="week-cell inline-flex items-center justify-center rounded-lg bg-accent/15 text-fg font-bold" title="${window.escapeHtml(week.name)}">${isoWeek(monday)}</a>`
                : `<span class="week-cell inline-flex items-center justify-center text-muted">${isoWeek(monday)}</span>`;
            html += `<tr><th scope="row" class="py-0.5">${label}</th>`;
            for (let i = 0; i < 7; i++) {
                const d = new Date(monday);
                d.setDate(monday.getDate() + i);
                const isToday = iso(d) === iso(today);
                const other = d.getMonth() !== view.getMonth();
                html += `<td class="py-0.5"><span class="inline-flex items-center justify-center w-8 h-8 rounded-full ${isToday ? 'bg-accent text-[var(--accent-contrast)] font-bold' : other ? 'text-muted' : 'text-soft'}">${d.getDate()}</span></td>`;
            }
            html += '</tr>';
        }
        document.getElementById('cal-body').innerHTML = html;
    }
    document.getElementById('cal-prev').addEventListener('click', () => { view = new Date(view.getFullYear(), view.getMonth() - 1, 1); draw(); });
    document.getElementById('cal-next').addEventListener('click', () => { view = new Date(view.getFullYear(), view.getMonth() + 1, 1); draw(); });
    draw();
})();
