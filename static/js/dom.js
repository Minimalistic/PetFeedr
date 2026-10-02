// Small DOM helpers shared by the card renderers.

// html`` escapes every interpolated value, so state strings (log-derived
// labels, times) can never become markup. A nested html`` result, or an
// array of them, passes through as-is.
class Markup {
    constructor(text) { this.text = text; }
    toString() { return this.text; }
}

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

function escapeValue(value) {
    if (value instanceof Markup) return value.text;
    if (Array.isArray(value)) return value.map(escapeValue).join('');
    if (value === null || value === undefined || value === false) return '';
    return String(value).replace(/[&<>"']/g, c => ESCAPES[c]);
}

export function html(strings, ...values) {
    let out = strings[0];
    values.forEach((value, i) => { out += escapeValue(value) + strings[i + 1]; });
    return new Markup(out);
}

// Trusted constant markup (hand-written SVG in this repo), never state
export const trusted = text => new Markup(text);

// The only innerHTML write in the app. It accepts nothing but html``/trusted
// output, so a raw string (say, a state label) can't slip in unescaped.
export function setHTML(el, markup) {
    if (!(markup instanceof Markup)) throw new TypeError('setHTML needs html`` markup');
    el.innerHTML = markup.text;
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// Web Animations API: runs without touching stylesheets and cleans up after
// itself, so one-off motion (a row arriving, a value changing) needs no CSS class
export function animate(el, keyframes, options) {
    if (reducedMotion() || !el.animate) return Promise.resolve();
    return el.animate(keyframes, { easing: 'cubic-bezier(0.2, 0.9, 0.3, 1)', ...options }).finished
        .catch(() => {});  // cancelled by a newer animation — fine
}

// Grow an element in from zero height (a list row arriving)
export function expandIn(el) {
    const height = el.offsetHeight;
    return animate(el, [
        { height: '0px', opacity: 0, transform: 'scale(0.97)', overflow: 'hidden' },
        { height: `${height}px`, opacity: 1, transform: 'none', overflow: 'hidden' },
    ], { duration: 320 });
}

// Shrink an element to zero height (a list row leaving); resolves when done
export function collapseOut(el) {
    const height = el.offsetHeight;
    return animate(el, [
        { height: `${height}px`, opacity: 1, overflow: 'hidden' },
        { height: '0px', opacity: 0, marginTop: '0px', marginBottom: '0px',
          paddingTop: '0px', paddingBottom: '0px', overflow: 'hidden' },
    ], { duration: 260, fill: 'forwards' });
}

// A quick lift when content changes in place, so an update registers
export function pulse(el) {
    return animate(el, [
        { opacity: 0.35, transform: 'translateY(4px)' },
        { opacity: 1, transform: 'none' },
    ], { duration: 380 });
}

// Count a number from one value to another, formatting each frame
export function tweenNumber(el, from, to, format, duration = 700) {
    if (from === to || reducedMotion()) {
        el.textContent = format(to);
        return;
    }
    const start = performance.now();
    const step = now => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = format(Math.round(from + (to - from) * eased));
        if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}
