/*
 * CSRF helper shared by all page controllers (B-01).
 * Django renders the token into <meta name="csrf-token">; JSON POSTs send it in
 * the X-CSRFToken header so the API endpoints no longer need @csrf_exempt.
 */
window.getCsrfToken = function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
};

// Headers for JSON POST requests to Django endpoints.
window.jsonHeaders = function () {
    return { 'Content-Type': 'application/json', 'X-CSRFToken': window.getCsrfToken() };
};

// Escape text before inserting it with innerHTML (B-09).
window.escapeHtml = function (text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
};
