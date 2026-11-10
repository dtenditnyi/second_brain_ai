/*
 * Shared responsive navigation controller loaded by the base template.
 * Below 1024px the sidebar is an off-canvas menu: it opens from the header
 * button, closes on the × button, a tap on the dimmed backdrop, Esc or a
 * navigation click, and locks background scrolling while open.
 * Also exposes window.lockScroll / window.prefersReducedMotion for page scripts.
 */
(function () {
    let locks = 0;
    window.lockScroll = function (on) {
        locks = Math.max(0, locks + (on ? 1 : -1));
        document.body.classList.toggle('scroll-locked', locks > 0);
    };
    window.prefersReducedMotion = function () {
        return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    };
})();

document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('main-sidebar');
    const openBtn = document.getElementById('mobile-menu-open');
    const closeBtn = document.getElementById('mobile-menu-close');
    const backdrop = document.getElementById('menu-backdrop');
    if (!sidebar || !openBtn) return;

    const isOpen = () => !sidebar.classList.contains('-translate-x-full');
    const isMobile = () => window.innerWidth < 1024;
    // While closed on small screens the menu is off-canvas: hide it from Tab and screen readers.
    function syncInert() {
        const hidden = isMobile() && !isOpen();
        sidebar.inert = hidden;
        if (hidden) sidebar.setAttribute('aria-hidden', 'true'); else sidebar.removeAttribute('aria-hidden');
    }
    syncInert();

    function setMenu(open) {
        if (open === isOpen()) return;
        sidebar.classList.toggle('-translate-x-full', !open);
        if (backdrop) backdrop.classList.toggle('is-open', open);
        openBtn.setAttribute('aria-expanded', String(open));
        window.lockScroll(open);
        syncInert();
        if (open) {
            (closeBtn || sidebar).focus({ preventScroll: true });
        } else {
            openBtn.focus({ preventScroll: true });
        }
    }

    openBtn.addEventListener('click', () => setMenu(true));
    if (closeBtn) closeBtn.addEventListener('click', () => setMenu(false));
    if (backdrop) backdrop.addEventListener('click', () => setMenu(false));
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isOpen() && window.innerWidth < 1024) setMenu(false);
    });
    // Following a link closes the menu (also restores scrolling on bfcache return).
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
        if (window.innerWidth < 1024) setMenu(false);
    }));
    // Growing past the breakpoint with the menu open must not leave the page locked.
    window.addEventListener('resize', () => {
        syncInert();
        if (window.innerWidth >= 1024 && isOpen() && openBtn.getAttribute('aria-expanded') === 'true') {
            sidebar.classList.add('-translate-x-full');  // lg:translate-x-0 keeps it visible on desktop
            if (backdrop) backdrop.classList.remove('is-open');
            openBtn.setAttribute('aria-expanded', 'false');
            window.lockScroll(false);
        }
    });
});
