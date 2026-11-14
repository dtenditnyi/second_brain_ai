/*
 * Round 5 (F1): a tiny local graph renderer (no external library): force layout computed once
 * (Fruchterman–Reingold), drawn as SVG, pan by drag, zoom by wheel / buttons, click opens a note.
 * Phones (narrow containers) get a simplified view: only the best-connected nodes, labels for
 * the current note and hubs only.
 */
(function () {
    const SVGNS = 'http://www.w3.org/2000/svg';
    const PALETTE = ['#00D4E0', '#C77DFF', '#4ADE80', '#FBBF24', '#60A5FA', '#F87171', '#F472B6', '#A3E635', '#94A3B8'];

    function layout(nodes, edges, w, h) {
        const n = nodes.length;
        const index = new Map(nodes.map((d, i) => [d.id, i]));
        const pos = nodes.map((d, i) => {
            const a = (i / Math.max(n, 1)) * Math.PI * 2;
            const r = Math.min(w, h) * 0.35 * (0.5 + ((i * 7919) % 100) / 200);
            return { x: w / 2 + Math.cos(a) * r, y: h / 2 + Math.sin(a) * r };
        });
        const links = edges.map(e => [index.get(e.source), index.get(e.target)]).filter(l => l[0] !== undefined && l[1] !== undefined);
        const k = Math.sqrt((w * h) / Math.max(n, 1)) * 1.1;
        let t = Math.min(w, h) / 8;
        const iterations = n > 250 ? 120 : 220;
        for (let it = 0; it < iterations; it++) {
            const disp = pos.map(() => ({ x: 0, y: 0 }));
            for (let i = 0; i < n; i++) {
                for (let j = i + 1; j < n; j++) {
                    let dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
                    let d = Math.sqrt(dx * dx + dy * dy) || 0.01;
                    const f = (k * k) / d;
                    dx /= d; dy /= d;
                    disp[i].x += dx * f; disp[i].y += dy * f;
                    disp[j].x -= dx * f; disp[j].y -= dy * f;
                }
            }
            links.forEach(([a, b]) => {
                let dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
                const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
                const f = (d * d) / k;
                dx /= d; dy /= d;
                disp[a].x -= dx * f; disp[a].y -= dy * f;
                disp[b].x += dx * f; disp[b].y += dy * f;
            });
            for (let i = 0; i < n; i++) {
                disp[i].x += (w / 2 - pos[i].x) * 0.02 * k / 10;      // gentle gravity
                disp[i].y += (h / 2 - pos[i].y) * 0.02 * k / 10;
                const d = Math.sqrt(disp[i].x ** 2 + disp[i].y ** 2) || 0.01;
                pos[i].x += (disp[i].x / d) * Math.min(d, t);
                pos[i].y += (disp[i].y / d) * Math.min(d, t);
            }
            t *= 0.97;
        }
        // Fit the drawing into the box (padding leaves room for node circles).
        const pad = 14;
        const xs = pos.map(p => p.x), ys = pos.map(p => p.y);
        const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
        const sx = (w - 2 * pad) / Math.max(maxX - minX, 1), sy = (h - 2 * pad) / Math.max(maxY - minY, 1);
        const s = Math.min(sx, sy, 3);
        const ox = (w - (maxX - minX) * s) / 2, oy = (h - (maxY - minY) * s) / 2;
        pos.forEach(p => { p.x = ox + (p.x - minX) * s; p.y = oy + (p.y - minY) * s; });
        return { pos, links };
    }

    function render(container, data, opts = {}) {
        container.innerHTML = '';
        const rect = container.getBoundingClientRect();
        const w = Math.max(rect.width, 200), h = Math.max(rect.height, 160);
        const simple = opts.simple !== undefined ? opts.simple : w < 640;
        let nodes = data.nodes || [], edges = data.edges || [];
        const degree = new Map();
        edges.forEach(e => { degree.set(e.source, (degree.get(e.source) || 0) + 1); degree.set(e.target, (degree.get(e.target) || 0) + 1); });
        const limit = simple ? 60 : 400;
        if (nodes.length > limit) {
            const keep = new Set(nodes.slice().sort((a, b) => (b.current - a.current) || ((degree.get(b.id) || 0) - (degree.get(a.id) || 0)))
                .slice(0, limit).map(d => d.id));
            nodes = nodes.filter(d => keep.has(d.id));
            edges = edges.filter(e => keep.has(e.source) && keep.has(e.target));
        }
        if (!nodes.length) {
            container.innerHTML = '<div class="empty-state">Нет связей для графа.</div>';
            return;
        }
        const folders = [...new Set(nodes.map(d => d.folder || ''))].sort();
        const colour = f => PALETTE[folders.indexOf(f || '') % PALETTE.length];
        const { pos, links } = layout(nodes, edges, w, h);

        const svg = document.createElementNS(SVGNS, 'svg');
        svg.setAttribute('class', 'graph-canvas');
        svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', `Граф: ${nodes.length} заметок, ${links.length} связей`);
        const g = document.createElementNS(SVGNS, 'g');
        svg.appendChild(g);
        links.forEach(([a, b]) => {
            const line = document.createElementNS(SVGNS, 'line');
            line.setAttribute('x1', pos[a].x); line.setAttribute('y1', pos[a].y);
            line.setAttribute('x2', pos[b].x); line.setAttribute('y2', pos[b].y);
            line.setAttribute('stroke', 'currentColor'); line.setAttribute('stroke-opacity', '0.25');
            g.appendChild(line);
        });
        const maxDeg = Math.max(1, ...nodes.map(d => degree.get(d.id) || 0));
        // B-76: labels of every node covered the whole graph. Only the current note and the
        // best-connected notes are always labelled; the rest show on hover/focus or when zoomed in.
        const hubCount = simple ? 8 : 15;
        const hubMin = nodes.map(d => degree.get(d.id) || 0).sort((a, b) => b - a)[Math.min(hubCount, nodes.length) - 1] || 0;
        const labels = [];
        nodes.forEach((d, i) => {
            const deg = degree.get(d.id) || 0;
            const node = document.createElementNS(SVGNS, 'g');
            node.setAttribute('class', 'graph-node');
            node.setAttribute('tabindex', '0');
            node.setAttribute('role', 'link');
            node.setAttribute('aria-label', d.name);
            node.style.cursor = 'pointer';
            const c = document.createElementNS(SVGNS, 'circle');
            c.setAttribute('cx', pos[i].x); c.setAttribute('cy', pos[i].y);
            c.setAttribute('r', d.current ? 9 : 4 + (deg / maxDeg) * 6);
            c.setAttribute('fill', colour(d.folder));
            if (d.current) { c.setAttribute('stroke', 'currentColor'); c.setAttribute('stroke-width', '2'); }
            const title = document.createElementNS(SVGNS, 'title');
            title.textContent = d.name;
            c.appendChild(title);
            node.appendChild(c);
            const hub = !!d.current || nodes.length <= 12 || (deg > 0 && deg >= Math.max(2, hubMin));
            const label = document.createElementNS(SVGNS, 'text');
            const right = pos[i].x > w / 2;           // labels grow towards the centre, never out of the box
            label.setAttribute('x', pos[i].x + (right ? -8 : 8)); label.setAttribute('y', pos[i].y + 4);
            label.setAttribute('text-anchor', right ? 'end' : 'start');
            label.setAttribute('font-size', simple ? '10' : '11');
            label.setAttribute('fill', 'currentColor');
            label.setAttribute('paint-order', 'stroke');
            label.setAttribute('stroke', 'var(--color-bg, #0b0b10)');
            label.setAttribute('stroke-width', '3');
            label.setAttribute('visibility', hub ? 'visible' : 'hidden');
            label.textContent = d.name.length > 28 ? d.name.slice(0, 27) + '…' : d.name;
            node.appendChild(label);
            labels.push({ el: label, hub });
            const show = () => { label.setAttribute('visibility', 'visible'); node.parentNode && node.parentNode.appendChild(node); };
            const hide = () => { if (!hub && !zoomedIn()) label.setAttribute('visibility', 'hidden'); };
            node.addEventListener('mouseenter', show); node.addEventListener('focus', show);
            node.addEventListener('mouseleave', hide); node.addEventListener('blur', hide);
            const open = () => opts.onOpen && opts.onOpen(d);
            node.addEventListener('click', open);
            node.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
            g.appendChild(node);
        });
        container.appendChild(svg);

        // Pan + zoom (viewBox).
        let vb = { x: 0, y: 0, w, h }, drag = null;
        function zoomedIn() { return vb.w < w * 0.45; }
        const apply = () => {
            svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
            const scale = vb.w / w, all = zoomedIn();          // labels keep their size on screen
            labels.forEach(l => {
                l.el.setAttribute('font-size', String(((simple ? 10 : 11) * scale).toFixed(2)));
                l.el.setAttribute('stroke-width', String((3 * scale).toFixed(2)));
                l.el.setAttribute('visibility', l.hub || all ? 'visible' : 'hidden');
            });
        };
        const zoom = (factor, cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2) => {
            const nw = Math.min(Math.max(vb.w * factor, w / 6), w * 4), nh = nw * (h / w);
            vb = { x: cx - (cx - vb.x) * (nw / vb.w), y: cy - (cy - vb.y) * (nh / vb.h), w: nw, h: nh };
            apply();
        };
        svg.addEventListener('wheel', e => {
            e.preventDefault();
            const r = svg.getBoundingClientRect();
            zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, vb.x + ((e.clientX - r.left) / r.width) * vb.w, vb.y + ((e.clientY - r.top) / r.height) * vb.h);
        }, { passive: false });
        svg.addEventListener('pointerdown', e => {
            if (e.target.closest('.graph-node')) return;
            drag = { x: e.clientX, y: e.clientY, vb: { ...vb } };
            svg.setPointerCapture(e.pointerId);
        });
        svg.addEventListener('pointermove', e => {
            if (!drag) return;
            const r = svg.getBoundingClientRect();
            vb.x = drag.vb.x - ((e.clientX - drag.x) / r.width) * vb.w;
            vb.y = drag.vb.y - ((e.clientY - drag.y) / r.height) * vb.h;
            apply();
        });
        svg.addEventListener('pointerup', () => { drag = null; });
        return { zoomIn: () => zoom(1 / 1.3), zoomOut: () => zoom(1.3), reset: () => { vb = { x: 0, y: 0, w, h }; apply(); } };
    }

    window.SBGraph = { render };
})();
