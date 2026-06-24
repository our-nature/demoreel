"""The in-page overlay toolkit, injected on every document.

Everything that has to track a live element — the animated cursor, click ripples, the
keycast, and annotations (highlight / spotlight / callout / arrow / chapter / banner) —
is drawn *in the page* so it (a) follows the real element rect via requestAnimationFrame
and (b) is captured naturally by the video recording. Python calls these through
``page.evaluate("window.__demoreel.<fn>(...)")``.

Exposed API (window.__demoreel):
  configure({accent, cursorStyle, cursorSize, cursorColor, cursorShow, keycast})
  highlight(sel) · spotlight(sel) · callout(sel, text, placement)
  arrow(sel, dir, text) · banner(text) · chapter(title, sub)
  clearAnnotations() · clearChapter()
"""

OVERLAY_JS = r"""
(() => {
  if (window.__demoreel) return;
  const NS = {
    cfg: { accent: '108,92,231', cursorStyle: 'pointer', cursorSize: 22,
           cursorColor: '108,92,231', cursorShow: true, keycast: true },
    overlays: [],
    cursorEl: null, keycastEl: null, chapterEl: null,
  };

  function hexToRgb(h) {
    if (!h) return null;
    h = h.replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const n = parseInt(h, 16);
    return ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255);
  }

  function root() {
    let r = document.getElementById('__demoreel_root__');
    if (!r) {
      r = document.createElement('div');
      r.id = '__demoreel_root__';
      Object.assign(r.style, {
        position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: '2147483647',
      });
      (document.body || document.documentElement).appendChild(r);
    }
    return r;
  }

  // ----- cursor -----
  function cursor() {
    if (NS.cursorEl && document.body && document.body.contains(NS.cursorEl)) return NS.cursorEl;
    const c = document.createElement('div');
    c.id = '__demoreel_cursor__';
    Object.assign(c.style, {
      position: 'fixed', left: '50%', top: '50%', pointerEvents: 'none',
      zIndex: '2147483647', transition: 'left .34s cubic-bezier(.22,.61,.36,1), ' +
        'top .34s cubic-bezier(.22,.61,.36,1), width .09s ease, height .09s ease',
    });
    root().appendChild(c);
    NS.cursorEl = c;
    renderCursor();
    return c;
  }
  function renderCursor() {
    const c = NS.cursorEl; if (!c) return;
    c.style.display = NS.cfg.cursorShow ? 'block' : 'none';
    const col = NS.cfg.cursorColor, s = NS.cfg.cursorSize;
    if (NS.cfg.cursorStyle === 'dot') {
      c.innerHTML = '';
      Object.assign(c.style, {
        width: s + 'px', height: s + 'px', borderRadius: '50%',
        background: 'rgba(' + col + ',0.30)', border: '2px solid rgba(' + col + ',0.95)',
        boxShadow: '0 0 0 3px rgba(255,255,255,.25), 0 2px 8px rgba(0,0,0,.35)',
        transform: 'translate(-50%,-50%)',
      });
    } else {
      // macOS-style arrow pointer (SVG), hotspot top-left.
      c.style.width = s + 'px'; c.style.height = 'auto'; c.style.transform = 'translate(-3px,-2px)';
      c.style.background = 'none'; c.style.border = '0'; c.style.boxShadow = 'none';
      c.innerHTML =
        '<svg width="' + s + '" height="' + Math.round(s * 1.4) + '" viewBox="0 0 24 34" ' +
        'style="filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))">' +
        '<path d="M2 2 L2 26 L8.5 20 L12.5 30 L16.5 28 L12.5 18.5 L21 18 Z" ' +
        'fill="white" stroke="rgba(' + col + ',1)" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    }
  }
  function moveCursor(x, y) { const c = cursor(); c.style.left = x + 'px'; c.style.top = y + 'px'; }
  function pressCursor(down) {
    const c = cursor();
    if (NS.cfg.cursorStyle === 'dot') {
      c.style.width = (down ? NS.cfg.cursorSize * 0.6 : NS.cfg.cursorSize) + 'px';
      c.style.height = c.style.width;
    } else {
      c.style.transform = down ? 'translate(-3px,-2px) scale(.84)' : 'translate(-3px,-2px)';
    }
  }
  function ripple(x, y) {
    const r = document.createElement('div');
    Object.assign(r.style, {
      position: 'fixed', left: x + 'px', top: y + 'px', width: '12px', height: '12px',
      borderRadius: '50%', border: '2px solid rgba(' + NS.cfg.cursorColor + ',.9)',
      transform: 'translate(-50%,-50%)', pointerEvents: 'none', zIndex: '2147483646',
    });
    root().appendChild(r);
    const t0 = performance.now();
    (function a(now) {
      const t = Math.min((now - t0) / 480, 1), s = 12 + t * 70;
      r.style.width = s + 'px'; r.style.height = s + 'px'; r.style.opacity = String(1 - t);
      if (t < 1) requestAnimationFrame(a); else r.remove();
    })(t0);
  }

  // ----- keycast -----
  function keycast() {
    if (NS.keycastEl && document.body.contains(NS.keycastEl)) return NS.keycastEl;
    const k = document.createElement('div');
    Object.assign(k.style, {
      position: 'fixed', left: '50%', bottom: '12%', transform: 'translateX(-50%)',
      display: 'flex', gap: '6px', pointerEvents: 'none', zIndex: '2147483647',
    });
    root().appendChild(k); NS.keycastEl = k; return k;
  }
  const PRETTY = { ' ': 'space', Enter: '⏎', Tab: '⇥', Backspace: '⌫',
    ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→',
    Meta: '⌘', Control: '⌃', Alt: '⌥', Shift: '⇧', Escape: 'esc' };
  function showKey(label) {
    if (!NS.cfg.keycast) return;
    const k = keycast();
    const cap = document.createElement('div');
    cap.textContent = label;
    Object.assign(cap.style, {
      font: '600 22px -apple-system,system-ui,sans-serif', color: '#fff',
      padding: '8px 14px', borderRadius: '10px', background: 'rgba(20,20,28,.92)',
      border: '1px solid rgba(255,255,255,.16)', boxShadow: '0 6px 18px rgba(0,0,0,.4)',
      opacity: '0', transition: 'opacity .12s', minWidth: '20px', textAlign: 'center',
    });
    k.appendChild(cap);
    requestAnimationFrame(() => { cap.style.opacity = '1'; });
    setTimeout(() => { cap.style.opacity = '0'; setTimeout(() => cap.remove(), 200); }, 900);
  }

  // ----- annotation bookkeeping (rAF rect tracking) -----
  function track(el, sel, fn) {
    const o = { el, sel, fn, dead: false };
    NS.overlays.push(o);
    return o;
  }
  function tick() {
    for (const o of NS.overlays) {
      if (o.dead) continue;
      const t = document.querySelector(o.sel);
      if (t) o.fn(t.getBoundingClientRect());
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  function clearAnnotations() {
    for (const o of NS.overlays) { o.dead = true; if (o.el) o.el.remove(); }
    NS.overlays = [];
  }

  // ----- annotations -----
  function highlight(sel) {
    const box = document.createElement('div');
    Object.assign(box.style, {
      position: 'fixed', border: '3px solid rgba(' + NS.cfg.accent + ',1)',
      borderRadius: '10px', boxShadow: '0 0 0 4px rgba(' + NS.cfg.accent + ',.25)',
      pointerEvents: 'none', zIndex: '2147483645',
      transition: 'all .25s cubic-bezier(.22,.61,.36,1)',
    });
    root().appendChild(box);
    track(box, sel, (r) => {
      const p = 6;
      box.style.left = (r.left - p) + 'px'; box.style.top = (r.top - p) + 'px';
      box.style.width = (r.width + 2 * p) + 'px'; box.style.height = (r.height + 2 * p) + 'px';
    });
  }
  function spotlight(sel) {
    const hole = document.createElement('div');
    Object.assign(hole.style, {
      position: 'fixed', borderRadius: '12px', pointerEvents: 'none', zIndex: '2147483644',
      boxShadow: '0 0 0 9999px rgba(6,6,12,.62)', transition: 'all .3s cubic-bezier(.22,.61,.36,1)',
    });
    root().appendChild(hole);
    track(hole, sel, (r) => {
      const p = 8;
      hole.style.left = (r.left - p) + 'px'; hole.style.top = (r.top - p) + 'px';
      hole.style.width = (r.width + 2 * p) + 'px'; hole.style.height = (r.height + 2 * p) + 'px';
    });
  }
  function bubble(text) {
    const b = document.createElement('div');
    b.textContent = text;
    Object.assign(b.style, {
      position: 'fixed', maxWidth: '320px', font: '600 20px -apple-system,system-ui,sans-serif',
      color: '#fff', padding: '12px 16px', borderRadius: '12px',
      background: 'rgba(' + NS.cfg.accent + ',.96)', boxShadow: '0 10px 30px rgba(0,0,0,.4)',
      pointerEvents: 'none', zIndex: '2147483646', transition: 'opacity .2s', opacity: '0',
    });
    root().appendChild(b);
    requestAnimationFrame(() => { b.style.opacity = '1'; });
    return b;
  }
  function callout(sel, text, placement) {
    const b = bubble(text);
    if (!sel) {
      Object.assign(b.style, { left: '50%', top: '12%', transform: 'translateX(-50%)' });
      track(b, '__none__', () => {});
      return;
    }
    track(b, sel, (r) => {
      const place = placement && placement !== 'auto' ? placement
        : (r.top > 140 ? 'top' : 'bottom');
      const bw = b.offsetWidth, bh = b.offsetHeight, gap = 14;
      let x = r.left + r.width / 2 - bw / 2, y;
      if (place === 'top') y = r.top - bh - gap;
      else if (place === 'bottom') y = r.bottom + gap;
      else if (place === 'left') { x = r.left - bw - gap; y = r.top + r.height / 2 - bh / 2; }
      else { x = r.right + gap; y = r.top + r.height / 2 - bh / 2; }
      b.style.left = Math.max(8, x) + 'px'; b.style.top = Math.max(8, y) + 'px';
      b.style.transform = 'none';
    });
  }
  function arrow(sel, dir, text) {
    const a = document.createElement('div');
    const rot = { up: 0, right: 90, down: 180, left: 270 }[dir || 'up'];
    a.innerHTML = '<svg width="54" height="54" viewBox="0 0 24 24" style="transform:rotate(' +
      rot + 'deg);filter:drop-shadow(0 3px 6px rgba(0,0,0,.4))">' +
      '<path d="M12 3 L12 21 M12 3 L6 9 M12 3 L18 9" stroke="rgba(' + NS.cfg.accent +
      ',1)" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    Object.assign(a.style, { position: 'fixed', pointerEvents: 'none', zIndex: '2147483646' });
    root().appendChild(a);
    if (text) { const b = bubble(text); track(b, sel, (r) => {
      b.style.left = (r.left + r.width / 2 - b.offsetWidth / 2) + 'px';
      b.style.top = (r.bottom + 56) + 'px'; b.style.transform = 'none'; }); }
    track(a, sel, (r) => {
      a.style.left = (r.left + r.width / 2 - 27) + 'px'; a.style.top = (r.bottom + 6) + 'px';
    });
  }
  function chapter(title, sub) {
    clearChapter();
    // Opaque overlay so the page never bleeds through, and a gap-spaced flex card so the
    // bar / title / subtitle can never collide regardless of length.
    const wrap = document.createElement('div');
    Object.assign(wrap.style, {
      position: 'fixed', inset: '0', display: 'flex', alignItems: 'center',
      justifyContent: 'center', pointerEvents: 'none', zIndex: '2147483646',
      background: 'rgba(7,7,12,1)', opacity: '0', transition: 'opacity .4s ease',
    });
    const card = document.createElement('div');
    Object.assign(card.style, {
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '22px',
      textAlign: 'center', maxWidth: '78%', padding: '0 6%',
    });
    card.innerHTML =
      '<div style="width:60px;height:5px;border-radius:3px;background:rgba(' + NS.cfg.accent + ',1)"></div>' +
      '<div style="font:700 56px/1.12 -apple-system,system-ui,sans-serif;color:#f3f3f8;margin:0">' +
      (title || '') + '</div>' +
      (sub ? '<div style="font:400 26px/1.35 -apple-system,system-ui,sans-serif;color:#a9a9be;margin:0">' +
        sub + '</div>' : '');
    wrap.appendChild(card);
    root().appendChild(wrap); NS.chapterEl = wrap;
    requestAnimationFrame(() => { wrap.style.opacity = '1'; });
  }
  function clearChapter() {
    if (NS.chapterEl) { NS.chapterEl.remove(); NS.chapterEl = null; }
  }

  // ----- input wiring -----
  window.addEventListener('mousemove', (e) => moveCursor(e.clientX, e.clientY), true);
  window.addEventListener('mousedown', (e) => { pressCursor(true); ripple(e.clientX, e.clientY); }, true);
  window.addEventListener('mouseup', () => pressCursor(false), true);
  window.addEventListener('keydown', (e) => showKey(PRETTY[e.key] || (e.key.length === 1 ? e.key : e.key)), true);

  window.__demoreel = {
    configure(o) {
      if (o.accent) NS.cfg.accent = hexToRgb(o.accent) || NS.cfg.accent;
      if (o.cursorColor) NS.cfg.cursorColor = hexToRgb(o.cursorColor) || NS.cfg.cursorColor;
      if (o.cursorStyle) NS.cfg.cursorStyle = o.cursorStyle;
      if (o.cursorSize) NS.cfg.cursorSize = o.cursorSize;
      if (typeof o.cursorShow === 'boolean') NS.cfg.cursorShow = o.cursorShow;
      if (typeof o.keycast === 'boolean') NS.cfg.keycast = o.keycast;
      renderCursor();
    },
    highlight, spotlight, callout, arrow, chapter, clearChapter, clearAnnotations,
    banner: (t) => callout(null, t, 'auto'),
  };
  cursor();
})();
"""
