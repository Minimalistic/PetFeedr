// Feed card: press-and-hold to dispense, portion picker, extras left.

import { $, $$, html, setHTML, reducedMotion, pulse } from '../dom.js';
import { mutate, setHoldBusy } from '../store.js';

// Press-and-hold instead of tap-to-confirm: one deliberate gesture, and an
// accidental brush can't dispense. The ring fills in CSS over HOLD_MS.
const HOLD_MS = 700;
// How long the green check stays up after a dispense before the button resets
const CELEBRATE_MS = 1500;
const KIBBLE_COUNT = 14;

let descriptions = {};
// The hint under the button: what the state says it should read at rest,
// and whether a feed sequence currently owns it ("Dispensing…", "Fed!")
let restingHint = 'Hold to feed';
let sequenceActive = false;

function portionRadios(portions, defaultPortion, name) {
    return html`${portions.map(p => html`
        <label class="portion-segment" title="${p.label} (${p.desc})">
            <input type="radio" name="${name}" value="${p.name}" ${p.name === defaultPortion ? 'checked' : ''}>
            <span class="portion-segment-label portion-${p.name}">${p.letter}</span>
        </label>`)}`;
}

export { portionRadios };

function selectedPortion() {
    return $('#feed-portions input:checked')?.value;
}

function showDescription() {
    $('#portion-desc').textContent = descriptions[selectedPortion()] || '';
}

function setHint(text, kind = '') {
    const hint = $('.hold-hint');
    hint.textContent = text;
    hint.classList.toggle('is-active', kind === 'active');
    hint.classList.toggle('is-done', kind === 'done');
}

const vibrate = pattern => navigator.vibrate?.(pattern);  // Android only; iOS has no web vibration

// A dispense: kibble pops out of the bottom of the button (where the real
// chute is), arcs, and falls with gravity. Web Animations with per-keyframe easing: decelerate on the way
// up, accelerate on the way down
function dropKibble(btn) {
    if (reducedMotion()) return;
    const card = btn.closest('.feed-card');
    let layer = card.querySelector('.kibble-layer');
    if (!layer) {
        layer = document.createElement('div');
        layer.className = 'kibble-layer';
        card.appendChild(layer);
    }
    const cardBox = card.getBoundingClientRect();
    const btnBox = btn.getBoundingClientRect();
    const originX = btnBox.left - cardBox.left + btnBox.width / 2;
    const originY = btnBox.bottom - cardBox.top - 4;
    const spread = (Math.random() - 0.5);

    for (let i = 0; i < KIBBLE_COUNT; i++) {
        const k = document.createElement('span');
        k.className = Math.random() < 0.35 ? 'kibble is-dark' : 'kibble';
        k.style.setProperty('--size', `${6 + Math.random() * 5}px`);
        k.style.left = `${originX + (Math.random() - 0.5) * 24}px`;
        k.style.top = `${originY}px`;
        layer.appendChild(k);

        const dx = (Math.random() - 0.5 + spread * 0.3) * 190;
        const peak = -(6 + Math.random() * 18);  // a low hop, so the checkmark stays clear
        const fall = 110 + Math.random() * 70;
        const rot = (Math.random() - 0.5) * 720;
        k.animate([
            { transform: 'translate(0, 0) rotate(0deg) scale(0.5)', opacity: 0,
              easing: 'cubic-bezier(0.15, 0.6, 0.35, 1)' },
            { transform: `translate(${dx * 0.4}px, ${peak}px) rotate(${rot * 0.35}deg) scale(1)`, opacity: 1,
              offset: 0.32, easing: 'cubic-bezier(0.55, 0, 0.85, 0.4)' },
            { transform: `translate(${dx * 0.85}px, ${fall * 0.8}px) rotate(${rot * 0.85}deg) scale(1)`, opacity: 1,
              offset: 0.85 },
            { transform: `translate(${dx}px, ${fall}px) rotate(${rot}deg) scale(0.9)`, opacity: 0 },
        ], { duration: 950 + Math.random() * 350, delay: i * 26, fill: 'backwards' })
            .finished.then(() => k.remove(), () => k.remove());
    }
}

// The expanding ring when a dispense lands
function shockwave(wrap) {
    if (reducedMotion()) return;
    const ring = document.createElement('span');
    ring.className = 'feed-shockwave';
    ring.addEventListener('animationend', () => ring.remove());
    wrap.appendChild(ring);
}

function initHold() {
    const form = $('.feed-form');
    const btn = $('.feed-circle-btn', form);
    const wrap = $('.feed-hold', form);
    const hint = $('.hold-hint', form);

    let timer = null;
    let ticks = [];
    let pressedAt = 0;
    let busy = false;

    const clearTicks = () => { ticks.forEach(clearTimeout); ticks = []; };

    // Only a completed hold feeds — Enter or a no-JS submit is ignored here
    form.addEventListener('submit', e => e.preventDefault());
    // Long-press on mobile would otherwise open the context menu mid-hold
    btn.addEventListener('contextmenu', e => e.preventDefault());

    function start(e) {
        if (btn.disabled || busy || timer) return;
        e.preventDefault();
        pressedAt = Date.now();
        setHoldBusy(true);
        wrap.classList.add('holding');
        timer = setTimeout(fire, HOLD_MS);
        // Two light ticks as the ring passes a third and two thirds
        ticks = [setTimeout(() => vibrate(8), HOLD_MS / 3), setTimeout(() => vibrate(8), HOLD_MS * 2 / 3)];
    }

    function cancel() {
        if (!timer) return;
        clearTimeout(timer);
        timer = null;
        clearTicks();
        setHoldBusy(false);
        wrap.classList.remove('holding');
        // A quick tap gets a nudge instead of silently doing nothing
        if (Date.now() - pressedAt < HOLD_MS) {
            hint.classList.remove('nudge');
            void hint.offsetWidth;  // restart the animation
            hint.classList.add('nudge');
        }
    }

    async function fire() {
        timer = null;
        clearTicks();
        busy = true;
        sequenceActive = true;
        wrap.classList.remove('holding');
        wrap.classList.add('dispensing');
        setHint('Dispensing…', 'active');
        vibrate(15);
        const portion = selectedPortion();
        setHoldBusy(false);  // mutate() tracks the request from here
        const result = await mutate('/feed', portion ? { portion } : {});
        wrap.classList.remove('dispensing');

        if (result.ok) {
            wrap.classList.add('done');
            setHint('Fed!', 'done');
            shockwave(wrap);
            dropKibble(btn);
            vibrate([20, 50, 30]);
            setTimeout(() => {
                wrap.classList.remove('done');
                finish();
            }, CELEBRATE_MS);
        } else {
            wrap.classList.add('failed');
            setTimeout(() => {
                wrap.classList.remove('failed');
                finish();
            }, 450);
        }
    }

    // Hand the hint back to the state (it may now say "Extras reset at midnight")
    function finish() {
        sequenceActive = false;
        busy = false;
        setHint(restingHint);
    }

    btn.addEventListener('pointerdown', start);
    ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => btn.addEventListener(ev, cancel));
    btn.addEventListener('keydown', e => {
        if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) start(e);
    });
    btn.addEventListener('keyup', e => {
        if (e.key === ' ' || e.key === 'Enter') cancel();
    });
}

export function renderFeed(feed) {
    const btn = $('.feed-circle-btn');
    btn.disabled = feed.no_extras;
    btn.setAttribute('aria-label', feed.no_extras ? 'No extra feeds left today'
                                                   : 'Press and hold to dispense food now');
    restingHint = feed.no_extras ? 'Extras reset at midnight' : 'Hold to feed';
    if (!sequenceActive) setHint(restingHint);

    for (const input of $$('#feed-portions input')) {
        const fits = feed.fits[input.value];
        input.disabled = !fits;
        input.closest('label').title = fits ? '' : "More than today's extras allow";
    }
    // If the chosen portion no longer fits, fall back to the biggest one that does
    if ($('#feed-portions input:checked')?.disabled) {
        const fitting = $$('#feed-portions input:not(:disabled)');
        if (fitting.length) fitting[fitting.length - 1].checked = true;
    }
    showDescription();

    const chip = $('#extras-chip');
    const changed = chip.textContent && chip.textContent !== feed.extras_label;
    chip.textContent = feed.extras_label;
    chip.title = feed.allowance_title;
    chip.classList.toggle('is-empty', feed.no_extras);
    if (changed) pulse(chip);
}

export function initFeed(state) {
    descriptions = Object.fromEntries(state.portions.map(p => [p.name, p.desc]));
    setHTML($('#feed-portions'), portionRadios(state.portions, state.default_portion, 'portion'));
    $('#feed-portions').addEventListener('change', showDescription);
    initHold();
}
