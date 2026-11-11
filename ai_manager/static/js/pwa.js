/*
 * Round 5 (F4): PWA glue shared by every page.
 *  - registers the service worker (/sw.js, offline reading of recently opened notes);
 *  - shows the "Нет сети" banner while offline;
 *  - SBCapture: quick capture to «Входящие» with an offline queue (localStorage, per user),
 *    sent automatically when the network is back. Each entry carries a client_id, so a resend
 *    after a lost response is not written twice (the server remembers client_id for a day).
 *  - on the login page (after logout) it clears the offline caches (no previous user's notes).
 */
(function () {
    const uid = document.body ? document.body.dataset.uid : '';
    const QUEUE_KEY = 'sb-capture-queue:' + (uid || 'anon');

    function clearOfflineCaches() {
        if ('caches' in window) {
            caches.keys().then(keys => keys.filter(k => k.startsWith('sb-')).forEach(k => caches.delete(k))).catch(() => {});
        }
        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
            navigator.serviceWorker.controller.postMessage('sb-clear-cache');
        }
    }
    window.SBClearOfflineCache = clearOfflineCaches;
    if (!uid && document.getElementById('sb-clear-cache')) clearOfflineCaches();

    if ('serviceWorker' in navigator && uid) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
        });
    }

    // ---------------------------------------------------------------- offline banner
    const banner = document.getElementById('offline-banner');
    function updateBanner() {
        if (banner) banner.classList.toggle('hidden', navigator.onLine);
    }
    window.addEventListener('online', updateBanner);
    window.addEventListener('offline', updateBanner);
    updateBanner();

    // ---------------------------------------------------------------- capture queue
    function readQueue() {
        try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch (e) { return []; }
    }
    function writeQueue(items) {
        try { localStorage.setItem(QUEUE_KEY, JSON.stringify(items)); } catch (e) { /* private mode */ }
    }
    function newId() {
        return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2);
    }
    const listeners = [];
    function notify(state, detail) { listeners.forEach(fn => { try { fn(state, detail); } catch (e) { /* ignore */ } }); }

    async function post(item) {
        const res = await fetch('/api/capture/', {
            method: 'POST', headers: window.jsonHeaders(), credentials: 'same-origin',
            body: JSON.stringify({ text: item.text, target: item.target || 'inbox', client_id: item.id }),
        });
        let data = {};
        try { data = await res.json(); } catch (e) { /* not JSON */ }
        if (res.ok) return { ok: true, data };
        // 4xx (bad text, no rights) will not get better by retrying; 5xx/503 (vault busy) will.
        return { ok: false, retry: res.status >= 500 || res.status === 429, msg: data.msg || ('HTTP ' + res.status) };
    }

    let flushing = false;
    async function flush() {
        if (flushing || !navigator.onLine) return;
        flushing = true;
        try {
            let queue = readQueue();
            let sent = 0;
            while (queue.length) {
                let result;
                try { result = await post(queue[0]); } catch (e) { break; }      // still offline
                if (!result.ok && result.retry) break;
                if (!result.ok) notify('error', { msg: result.msg, text: queue[0].text });
                else sent += 1;
                queue = readQueue().filter(x => x.id !== queue[0].id);
                writeQueue(queue);
            }
            if (sent) notify('sent', { count: sent, pending: readQueue().length });
        } finally {
            flushing = false;
        }
    }

    async function send(text, target) {
        const item = { id: newId(), text, target: target || 'inbox', at: Date.now() };
        if (!navigator.onLine) {
            writeQueue([...readQueue(), item]);
            notify('queued', { pending: readQueue().length });
            return { queued: true };
        }
        try {
            const result = await post(item);
            if (result.ok) { notify('sent', { count: 1, pending: readQueue().length }); return { ok: true, data: result.data }; }
            if (result.retry) { writeQueue([...readQueue(), item]); notify('queued', { pending: readQueue().length, msg: result.msg }); return { queued: true }; }
            notify('error', { msg: result.msg });
            return { ok: false, msg: result.msg };
        } catch (e) {
            writeQueue([...readQueue(), item]);
            notify('queued', { pending: readQueue().length });
            return { queued: true };
        }
    }

    window.SBCapture = { send, flush, pending: () => readQueue().length, onChange: fn => listeners.push(fn) };
    window.addEventListener('online', flush);
    if (uid) setTimeout(flush, 500);
})();
