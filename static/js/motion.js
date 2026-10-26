/* Office Stock - gentle motion: reveal on scroll, soft parallax, count-up numbers, scroll progress.
   Everything here is decoration. If this file fails to load, the head script in base.html turns the "js" class off again. */
(function () {
  'use strict';
  window.__motionReady = true;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var REVEAL = '.card, .tile, .page-header, main > .alert';

  // ---- staggered nav + table rows (CSS does the animating)
  $$('.nav a').forEach(function (a, i) { a.style.setProperty('--n', i); });
  $$('table.data tbody').forEach(function (tb) {
    $$('tr', tb).slice(0, 30).forEach(function (tr, i) { tr.style.setProperty('--i', i); });
  });

  // ---- count-up for dashboard numbers: "12", "1,250", "Rs. 4,500.00"
  function countUp(el) {
    if (reduce || el.getAttribute('data-counted')) return;
    var m = /^(Rs\.\s*)?(-?[\d,]+(?:\.(\d+))?)$/.exec(el.textContent.trim());
    if (!m) return;
    el.setAttribute('data-counted', '1');
    var prefix = m[1] || '', decimals = m[3] ? m[3].length : 0, target = parseFloat(m[2].replace(/,/g, ''));
    if (!isFinite(target) || target === 0) return;
    var start = null, dur = 1000, fmt = function (n) {
      return prefix + n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    };
    var step = function (t) {
      if (start === null) start = t;
      var p = Math.min((t - start) / dur, 1), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * eased);
      if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
    };
    requestAnimationFrame(step);
  }

  // ---- reveal on scroll
  function show(el) {
    if (el.classList.contains('in')) return;
    el.classList.add('in');
    $$('.value', el).forEach(countUp);
  }
  var seen = new Map();
  function stagger(el) {
    var parent = el.parentNode, n = seen.get(parent) || 0;
    seen.set(parent, n + 1);
    el.style.setProperty('--d', Math.min(n, 7) * 70 + 'ms');
  }
  var io = null;
  if ('IntersectionObserver' in window && !reduce) {
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { show(e.target); io.unobserve(e.target); } });
    }, { threshold: 0.08, rootMargin: '0px 0px -5% 0px' });
  }
  $$(REVEAL).forEach(function (el) {
    if (el.classList.contains('hero')) return;
    if (io) { stagger(el); io.observe(el); } else show(el);
  });
  // Anything added later (script-built rows and panels) simply appears.
  if ('MutationObserver' in window) {
    new MutationObserver(function (list) {
      list.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches(REVEAL)) show(n);
          $$(REVEAL, n).forEach(show);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  }
  // Safety net: nothing may stay hidden.
  setTimeout(function () { $$(REVEAL).forEach(show); }, 2500);
  if (reduce) return;

  // ---- soft parallax + progress line + top bar shadow, one frame at a time
  var layers = $$('[data-parallax]').map(function (el) { return { el: el, speed: parseFloat(el.getAttribute('data-parallax')) || 0 }; });
  var bar = document.getElementById('scroll-progress'), top = document.querySelector('.topbar'), ticking = false;
  function frame() {
    ticking = false;
    var y = window.pageYOffset || 0;
    layers.forEach(function (l) {
      // tanh keeps the drift gentle however far the page is scrolled
      var v = 150 * Math.tanh((y * l.speed) / 150);
      l.el.style.translate = '0 ' + v.toFixed(1) + 'px';
    });
    if (bar) {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.transform = 'scaleX(' + (max > 0 ? Math.min(y / max, 1) : 0).toFixed(4) + ')';
    }
    if (top) top.classList.toggle('scrolled', y > 6);
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(frame); } }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  frame();

  // ---- sign-in page: shapes follow the pointer a little
  var mouse = $$('[data-mouse]');
  if (mouse.length && window.matchMedia('(pointer: fine)').matches) {
    window.addEventListener('pointermove', function (e) {
      var x = e.clientX / window.innerWidth - 0.5, yy = e.clientY / window.innerHeight - 0.5;
      mouse.forEach(function (el) {
        var d = parseFloat(el.getAttribute('data-mouse')) || 10;
        el.style.translate = (x * d).toFixed(1) + 'px ' + (yy * d).toFixed(1) + 'px';
      });
    }, { passive: true });
  }
})();
