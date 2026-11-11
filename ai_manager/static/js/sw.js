/*
 * Second Brain service worker (Round 5, F4). Served from /sw.js (scope "/").
 *  - static assets: stale-while-revalidate (fast, works offline);
 *  - recently opened notes (/api/get-note/) and the main pages: network first, the last good
 *    copy is kept for offline READING only (POST/PUT/… are never intercepted or cached);
 *  - redirects (expired session → /login/) and errors are never cached;
 *  - message "sb-clear-cache" (sent after logout) deletes every sb-* cache.
 */
const STATIC_PREFIX = '__STATIC__';
const VERSION = 'r5-1';
const STATIC_CACHE = 'sb-static-' + VERSION;
const NOTES_CACHE = 'sb-notes-' + VERSION;
const PAGES_CACHE = 'sb-pages-' + VERSION;
const MAX_NOTES = 40;
const PAGES = ['/', '/notes/', '/weekly/', '/tasks/'];
const SHELL = ['css/styles.css', 'js/csrf.js', 'js/layout.js', 'js/pwa.js', 'js/vault_nav.js', 'js/notes.js',
               'js/home.js', 'js/tasks.js', 'icons/icon-192.png'].map(p => STATIC_PREFIX + p);

self.addEventListener('install', event => {
    event.waitUntil(caches.open(STATIC_CACHE).then(c => c.addAll(SHELL)).catch(() => null).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
    event.waitUntil(caches.keys().then(keys => Promise.all(
        keys.filter(k => k.startsWith('sb-') && !k.endsWith(VERSION)).map(k => caches.delete(k))
    )).then(() => self.clients.claim()));
});

self.addEventListener('message', event => {
    if (event.data === 'sb-clear-cache') {
        event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('sb-')).map(k => caches.delete(k)))));
    }
});

function cacheable(response) {
    return response && response.ok && !response.redirected && response.type === 'basic';
}

async function trim(cacheName, max) {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();
    for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
}

async function networkFirst(request, cacheName, fallback) {
    const cache = await caches.open(cacheName);
    try {
        const response = await fetch(request);
        if (cacheable(response)) {
            await cache.delete(request);
            await cache.put(request, response.clone());
            if (cacheName === NOTES_CACHE) trim(NOTES_CACHE, MAX_NOTES);
        }
        return response;
    } catch (error) {
        const hit = await cache.match(request);
        if (hit) return hit;
        return fallback ? fallback() : Response.error();
    }
}

async function staleWhileRevalidate(request) {
    const cache = await caches.open(STATIC_CACHE);
    const hit = await cache.match(request);
    const network = fetch(request).then(response => {
        if (cacheable(response)) cache.put(request, response.clone());
        return response;
    }).catch(() => hit || Response.error());
    return hit || network;
}

function offlineJson() {
    return new Response(JSON.stringify({ status: 'error', offline: true,
        msg: 'Нет сети, а эта заметка ещё не открывалась на этом устройстве.' }),
        { status: 503, headers: { 'Content-Type': 'application/json' } });
}

function offlinePage() {
    return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
        '<title>Нет сети</title><body style="font-family:system-ui;background:#0D0D12;color:#E5E7EB;padding:2rem">' +
        '<h1>📡 Нет сети</h1><p>Эта страница ещё не сохранена для офлайн-чтения. Откройте заметки, которые уже ' +
        'открывали, или подождите появления сети.</p><p><a style="color:#00F0FF" href="/notes/">Заметки</a></p></body>',
        { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET') return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;
    if (url.pathname.startsWith(STATIC_PREFIX)) {
        event.respondWith(staleWhileRevalidate(request));
    } else if (url.pathname === '/api/get-note/') {
        event.respondWith(networkFirst(request, NOTES_CACHE, offlineJson));
    } else if (request.mode === 'navigate' && PAGES.includes(url.pathname)) {
        event.respondWith(networkFirst(request, PAGES_CACHE, offlinePage));
    }
});
