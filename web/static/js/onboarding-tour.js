/**
 * Lightweight, dependency-free spotlight tour.
 * Usage: TenderSentinelTour.start([{selector, title, text}, ...], {storageKey});
 * The dim backdrop is a single element's box-shadow cast around a rounded
 * cutout at the target's rect, so the highlight itself stays a clean rounded
 * rectangle (no square corners breaking the rounded design language) and,
 * since that element has pointer-events:none, the highlighted element below
 * it stays genuinely clickable — "click here" steps send the user straight
 * into the real action. Skip/Next are the only way to dismiss (there's no
 * backdrop to intercept a click). Skips gracefully if a step's selector
 * isn't on the page, and never re-shows once storageKey is set in
 * localStorage.
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
        var ring, tooltip;

        function markSeen() {
            if (storageKey) localStorage.setItem(storageKey, '1');
        }

        function cleanup() {
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

            if (!ring) {
                ring = document.createElement('div');
                ring.style.cssText = 'position:fixed;z-index:9998;pointer-events:none;' +
                    'border-radius:12px;border:2px solid #fc7218;' +
                    'transition:top .2s ease,left .2s ease,width .2s ease,height .2s ease;';
                document.body.appendChild(ring);
            }
            ring.style.top = hTop + 'px'; ring.style.left = hLeft + 'px';
            ring.style.width = hW + 'px'; ring.style.height = hH + 'px';
            // Box-shadow spotlight: a huge shadow cast from the (rounded)
            // ring itself dims the rest of the page, so the cutout follows
            // the same border-radius as the ring — no square corners.
            ring.style.boxShadow = '0 0 0 9999px rgba(15,23,42,.6), 0 0 0 3px rgba(252,114,24,.25) inset';

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
