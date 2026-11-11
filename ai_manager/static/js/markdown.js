/*
 * Markdown renderer for AI answers (chat + Home status report), Round 3 / G-A1.
 *
 * marked (GFM) → DOMPurify (HTML profile only: no SVG/MathML, no scripts, no
 * event handlers, no javascript: URLs) → DOM post-processing built with DOM
 * APIs only (callouts, code highlighting + "Copy", external links, tables).
 * Raw HTML written by the model is NOT rendered: it is shown as text (it was
 * shown as text before Round 3 too), so only Markdown produces markup.
 * [[Wiki links]] open the note page. Everything runs locally (static/vendor).
 */
(function () {
    'use strict';

    const escapeHtml = (text) => String(text ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    const CALLOUT_ICONS = {
        note: '📝', info: 'ℹ️', tip: '💡', hint: '💡', important: '❗', success: '✅', check: '✅', done: '✅',
        question: '❓', help: '❓', faq: '❓', warning: '⚠️', caution: '⚠️', attention: '⚠️', failure: '❌',
        fail: '❌', missing: '❌', danger: '⛔', error: '⛔', bug: '🐞', example: '🧪', quote: '💬', cite: '💬',
        abstract: '📋', summary: '📋', tldr: '📋', todo: '☑️',
    };

    let configured = false;
    function configure() {
        if (configured || !window.marked) return;
        const wikiLink = {
            name: 'wikiLink',
            level: 'inline',
            start(src) { const i = src.indexOf('[['); return i < 0 ? undefined : i; },
            tokenizer(src) {
                const match = /^\[\[([^\[\]\n|#]+)(#[^\[\]\n|]*)?(?:\|([^\[\]\n]+))?\]\]/.exec(src);
                if (!match) return undefined;
                return { type: 'wikiLink', raw: match[0], target: match[1].trim(), alias: (match[3] || match[1]).trim() };
            },
            renderer(token) {
                return `<a class="wiki-link" href="/notes/?file=${encodeURIComponent(token.target)}">${escapeHtml(token.alias)}</a>`;
            },
        };
        window.marked.use({
            gfm: true,
            breaks: true,
            extensions: [wikiLink],
            renderer: {
                // Raw HTML from the model is displayed as text, never interpreted.
                html(token) { return escapeHtml(token.text ?? token.raw ?? ''); },
            },
        });
        configured = true;
    }

    let hookInstalled = false;
    function installImageHook() {
        if (hookInstalled || !window.DOMPurify) return;
        // External images would be fetched by the browser: a prompt injection in a note
        // could exfiltrate data through the image URL (B-40). Only same-site images
        // load; others are replaced by a plain link in decorate(). The hook runs while
        // sanitising (inert document), so no request is ever made.
        window.DOMPurify.addHook('afterSanitizeAttributes', (node) => {
            if (node.tagName !== 'IMG') return;
            const src = node.getAttribute('src') || '';
            if (!/^\/(?!\/)/.test(src)) {
                node.setAttribute('data-blocked-src', src);
                node.removeAttribute('src');
            }
        });
        hookInstalled = true;
    }

    function sanitize(html) {
        if (!window.DOMPurify) return escapeHtml(html);
        installImageHook();
        return window.DOMPurify.sanitize(html, {
            USE_PROFILES: { html: true },
            FORBID_TAGS: ['style', 'form', 'iframe', 'object', 'embed', 'button', 'textarea', 'select', 'option'],
            FORBID_ATTR: ['style', 'srcset', 'formaction'],
            ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|\/(?!\/)|#|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i,
        });
    }

    function toCallouts(root) {
        root.querySelectorAll('blockquote').forEach((quote) => {
            const first = quote.firstElementChild;
            if (!first || first.tagName !== 'P') return;
            const match = /^\[!([a-z-]+)\]([+-]?)[ \t]*(.*)$/im.exec(first.textContent.split('\n')[0]);
            if (!match || first.textContent.indexOf('[!') !== 0) return;
            const type = match[1].toLowerCase();
            const callout = document.createElement(match[2] ? 'details' : 'div');
            callout.className = `callout callout-${type.replace(/[^a-z-]/g, '')}`;
            if (match[2] === '+') callout.open = true;
            const title = document.createElement(match[2] ? 'summary' : 'div');
            title.className = 'callout-title';
            const icon = document.createElement('span');
            icon.setAttribute('aria-hidden', 'true');
            icon.textContent = CALLOUT_ICONS[type] || 'ℹ️';
            title.append(icon, ' ', match[3] || type.charAt(0).toUpperCase() + type.slice(1));
            const body = document.createElement('div');
            body.className = 'callout-body';
            // The rest of the first paragraph (after the [!type] line) stays as content.
            const firstText = first.innerHTML.split(/<br\s*\/?>|\n/);
            firstText.shift();
            if (firstText.join('').trim()) {
                const p = document.createElement('p');
                p.innerHTML = sanitize(firstText.join('<br>'));
                body.appendChild(p);
            }
            Array.from(quote.children).slice(1).forEach((child) => body.appendChild(child));
            callout.append(title, body);
            quote.replaceWith(callout);
        });
    }

    function decorate(root) {
        toCallouts(root);
        root.querySelectorAll('img[data-blocked-src]').forEach((img) => {
            const url = img.getAttribute('data-blocked-src');
            const span = document.createElement('span');
            span.className = 'blocked-image';
            span.append('🖼 ');
            if (/^https?:\/\//i.test(url)) {
                const link = document.createElement('a');
                link.href = url;
                link.textContent = img.getAttribute('alt') || 'external image';
                link.title = `External image not loaded: ${url}`;
                span.append(link);
            } else {
                span.append(img.getAttribute('alt') || 'image');
            }
            img.replaceWith(span);
        });
        root.querySelectorAll('a[href]').forEach((a) => {
            const href = a.getAttribute('href') || '';
            if (/^https?:|^mailto:/i.test(href)) {
                a.setAttribute('target', '_blank');
                a.setAttribute('rel', 'noopener noreferrer');
            }
        });
        root.querySelectorAll('table').forEach((table) => {
            if (table.parentElement && table.parentElement.classList.contains('md-table-wrap')) return;
            const wrap = document.createElement('div');
            wrap.className = 'md-table-wrap';
            wrap.tabIndex = 0;
            table.replaceWith(wrap);
            wrap.appendChild(table);
        });
        root.querySelectorAll('pre > code').forEach((code) => {
            if (window.hljs) {
                try { window.hljs.highlightElement(code); } catch (e) { /* unknown language */ }
            }
            code.classList.add('hljs');
            const pre = code.parentElement;
            if (pre.parentElement && pre.parentElement.classList.contains('code-block')) return;
            const block = document.createElement('div');
            block.className = 'code-block';
            const copy = document.createElement('button');
            copy.type = 'button';
            copy.className = 'copy-code btn btn-ghost btn-sm';
            copy.textContent = 'Copy';
            copy.setAttribute('aria-label', 'Copy code');
            copy.addEventListener('click', () => copyText(code.textContent, copy));
            pre.replaceWith(block);
            block.append(copy, pre);
        });
        root.querySelectorAll('input[type=checkbox]').forEach((box) => {
            box.disabled = true;
            box.setAttribute('aria-label', box.checked ? 'done' : 'not done');
        });
    }

    async function copyText(text, button) {
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
            } else {
                const area = document.createElement('textarea');
                area.value = text;
                area.setAttribute('readonly', '');
                area.style.position = 'fixed';
                area.style.opacity = '0';
                document.body.appendChild(area);
                area.select();
                document.execCommand('copy');
                area.remove();
            }
            button.textContent = 'Copied';
        } catch (e) {
            button.textContent = 'Copy failed';
        }
        setTimeout(() => { button.textContent = 'Copy'; }, 1500);
    }

    /** Markdown text → sanitised HTML string (no decoration). */
    window.renderMarkdown = function (text) {
        configure();
        if (!window.marked) return escapeHtml(text).replace(/\n/g, '<br>');
        return sanitize(window.marked.parse(String(text ?? '')));
    };

    /** Render into an element: sanitised Markdown + callouts, code, links, tables. */
    window.renderMarkdownInto = function (element, text) {
        element.classList.add('markdown-body');
        element.classList.remove('whitespace-pre-wrap');
        element.innerHTML = window.renderMarkdown(text);
        decorate(element);
        return element;
    };

    // Server-rendered history: <div data-markdown>raw text</div> → same renderer.
    function renderPending(root) {
        (root || document).querySelectorAll('[data-markdown]:not([data-rendered])').forEach((el) => {
            const raw = el.textContent;
            window.renderMarkdownInto(el, raw);
            el.setAttribute('data-rendered', '1');
        });
    }
    window.renderPendingMarkdown = renderPending;
    document.addEventListener('DOMContentLoaded', () => renderPending(document));
})();
