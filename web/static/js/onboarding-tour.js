/**
 * Lightweight, dependency-free spotlight tour.
 * Usage: TenderSentinelTour.start([{selector, title, text}, ...], {storageKey});
 * The highlighted element itself stays fully clickable (the dim overlay is
 * built as 4 panels framing it, not a single sheet on top) so "click here"
 * steps can send the user straight into the real action. Clicking outside
 * the highlight, or Skip/Got it, dismisses the tour. Skips gracefully if a
 * step's selector isn't on the page, and never re-shows once storageKey is
 * set in localStorage.
 */
(function () {
    function start(steps, opts) {
        opts = opts || {};
        var storageKey = opts.storageKey;
        if (storageKey && localStorage.getItem(storageKey)) return;

        var visibleSteps = steps.filter(function (s) {
            return document.querySelector(s.selector);
        });
        if (!visibleSteps.length) return;

        var i = 0;
        var bars = [];
        var ring, tooltip;

        function markSeen() {
            if (storageKey) localStorage.setItem(storageKey, '1');
        }

        function cleanup() {
            bars.forEach(function (el) { el.remove(); });
            if (ring) ring.remove();
            if (tooltip) tooltip.remove();
            window.removeEventListener('resize', render);
            markSeen();
        }

        function next() {
            i++;
            if (i >= visibleSteps.length) { cleanup(); return; }
            render();
        }

        function ensureBars() {
            if (bars.length) return;
            for (var n = 0; n < 4; n++) {
                var bar = document.createElement('div');
                bar.style.cssText = 'position:fixed;z-index:9998;background:rgba(15,23,42,.6);cursor:pointer;';
                bar.addEventListener('click', cleanup);
                document.body.appendChild(bar);
                bars.push(bar);
            }
        }

        function render() {
            var step = visibleSteps[i];
            var target = document.querySelector(step.selector);
            if (!target) { next(); return; }

            target.scrollIntoView({ block: 'center', behavior: 'smooth' });

            // Re-measure after the scroll settles so the frame lines up.
            requestAnimationFrame(function () {
                setTimeout(function () { paint(step, target); }, 260);
            });
        }

        function paint(step, target) {
            var rect = target.getBoundingClientRect();
            var pad = 6;
            var hTop = rect.top - pad, hLeft = rect.left - pad;
            var hW = rect.width + pad * 2, hH = rect.height + pad * 2;
            var vw = window.innerWidth, vh = window.innerHeight;

            ensureBars();
            // top
            bars[0].style.top = '0px'; bars[0].style.left = '0px';
            bars[0].style.width = vw + 'px'; bars[0].style.height = Math.max(0, hTop) + 'px';
            // bottom
            bars[1].style.top = Math.max(0, hTop + hH) + 'px'; bars[1].style.left = '0px';
            bars[1].style.width = vw + 'px'; bars[1].style.height = Math.max(0, vh - (hTop + hH)) + 'px';
            // left (middle band)
            bars[2].style.top = Math.max(0, hTop) + 'px'; bars[2].style.left = '0px';
            bars[2].style.width = Math.max(0, hLeft) + 'px'; bars[2].style.height = hH + 'px';
            // right (middle band)
            bars[3].style.top = Math.max(0, hTop) + 'px'; bars[3].style.left = Math.max(0, hLeft + hW) + 'px';
            bars[3].style.width = Math.max(0, vw - (hLeft + hW)) + 'px'; bars[3].style.height = hH + 'px';

            if (!ring) {
                ring = document.createElement('div');
                ring.style.cssText = 'position:fixed;z-index:9998;pointer-events:none;' +
                    'border-radius:10px;border:2px solid #fc7218;box-shadow:0 0 0 3px rgba(252,114,24,.25);';
                document.body.appendChild(ring);
            }
            ring.style.top = hTop + 'px'; ring.style.left = hLeft + 'px';
            ring.style.width = hW + 'px'; ring.style.height = hH + 'px';

            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.style.cssText = 'position:fixed;z-index:9999;max-width:300px;' +
                    'background:#131b2e;color:#ffffff;padding:16px 18px;border-radius:12px;' +
                    'font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;' +
                    'box-shadow:0 10px 40px rgba(0,0,0,.35);';
                document.body.appendChild(tooltip);
            }

            var isLast = i === visibleSteps.length - 1;
            tooltip.innerHTML =
                '<div style="font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#fc7218;margin-bottom:6px;">' +
                    'Step ' + (i + 1) + ' of ' + visibleSteps.length +
                '</div>' +
                '<div style="font-size:14px;font-weight:700;margin-bottom:6px;">' + step.title + '</div>' +
                '<div style="font-size:13px;line-height:1.5;color:#cbd5e1;margin-bottom:14px;">' + step.text + '</div>' +
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">' +
                    '<button type="button" data-action="skip" style="background:none;border:none;color:#94a3b8;font-size:12px;cursor:pointer;padding:0;">Skip tour</button>' +
                    '<button type="button" data-action="next" style="background:#fc7218;border:none;color:#ffffff;font-weight:700;font-size:13px;padding:8px 16px;border-radius:8px;cursor:pointer;">' +
                        (isLast ? 'Got it!' : 'Next') +
                    '</button>' +
                '</div>';

            var ttRect = tooltip.getBoundingClientRect();
            var top = hTop + hH + 16;
            if (top + ttRect.height > vh) top = Math.max(16, hTop - ttRect.height - 16);
            var left = Math.min(Math.max(hLeft, 16), vw - ttRect.width - 16);
            tooltip.style.top = top + 'px';
            tooltip.style.left = left + 'px';

            tooltip.querySelector('[data-action="next"]').onclick = function (e) { e.stopPropagation(); next(); };
            tooltip.querySelector('[data-action="skip"]').onclick = function (e) { e.stopPropagation(); cleanup(); };
        }

        window.addEventListener('resize', render);
        render();
    }

    window.TenderSentinelTour = { start: start };
})();
