// Feed card: press-and-hold to dispense, portion picker, extras left.

import { $, $$, html, setHTML, reducedMotion, pulse } from '../dom.js';
import { mutate, setHoldBusy } from '../store.js';

// Press-and-hold instead of tap-to-confirm: one deliberate gesture, and an
// accidental brush can't dispense. The ring fills in CSS over HOLD_MS.
const HOLD_MS = 700;
// How long the ring stays full and green after a dispense before it resets
const CELEBRATE_MS = 1100;

let descriptions = {};

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

// A dispense: a handful of kibble tumbles out under the button
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
    const originY = btnBox.bottom - cardBox.top - 12;
    for (let i = 0; i < 10; i++) {
        const k = document.createElement('span');
        k.className = 'kibble';
        k.style.left = `${originX + (Math.random() - 0.5) * 30}px`;
        k.style.top = `${originY}px`;
        k.style.setProperty('--dx', `${(Math.random() - 0.5) * 90}px`);
        k.style.setProperty('--rot', `${(Math.random() - 0.5) * 540}deg`);
        k.style.setProperty('--delay', `${i * 45}ms`);
        k.style.setProperty('--size', `${7 + Math.random() * 4}px`);
        k.addEventListener('animationend', () => k.remove());
        layer.appendChild(k);
    }
}

function initHold() {
    const form = $('.feed-form');
    const btn = $('.feed-circle-btn', form);
    const wrap = $('.feed-hold', form);
    const hint = $('.hold-hint', form);

    let timer = null;
    let pressedAt = 0;
    let busy = false;

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
    }

    function cancel() {
        if (!timer) return;
        clearTimeout(timer);
        timer = null;
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
        busy = true;
        wrap.classList.remove('holding');
        wrap.classList.add('fired');
        navigator.vibrate?.(30);
        const portion = selectedPortion();
        setHoldBusy(false);  // mutate() tracks the request from here
        const result = await mutate('/feed', portion ? { portion } : {});
        if (result.ok) {
            btn.classList.add('fed');
            dropKibble(btn);
            // The page no longer reloads after a feed, so the ring resets itself
            setTimeout(() => {
                wrap.classList.remove('fired');
                btn.classList.remove('fed');
                busy = false;
            }, CELEBRATE_MS);
        } else {
            wrap.classList.remove('fired');
            busy = false;
        }
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
    $('.hold-hint').textContent = feed.no_extras ? 'Extras reset at midnight' : 'Hold to feed';

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
