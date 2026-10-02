// Hopper card: a drawing of the hopper whose kibble level glides to its new
// height, the forecast lines, and the "I refilled it" form.

import { $, html, setHTML, tweenNumber, pulse } from '../dom.js';
import { mutate } from '../store.js';

// The fill is drawn full height and slid down by (1 - level) of the 50-unit
// interior, so the level can animate as a CSS transform (and the kibble
// pattern moves with it, like food settling)
const INTERIOR = 50;

const HOPPER_SVG = html`
    <div class="hopper-visual">
        <svg class="hopper-svg" viewBox="0 0 64 84" role="img">
            <defs>
                <clipPath id="hopper-clip"><path d="M6 4 H58 L45 54 H19 Z"/></clipPath>
                <pattern id="kibble-pattern" width="9" height="7" patternUnits="userSpaceOnUse">
                    <ellipse cx="2.5" cy="2" rx="2" ry="1.5" class="kibble-dot"/>
                    <ellipse cx="7" cy="5.5" rx="2" ry="1.5" class="kibble-dot"/>
                </pattern>
            </defs>
            <g clip-path="url(#hopper-clip)">
                <rect class="hopper-svg-empty" x="0" y="0" width="64" height="60"/>
                <g class="hopper-fill">
                    <rect class="hopper-svg-fill" x="0" y="4" width="64" height="${INTERIOR + 1}"/>
                    <rect x="0" y="4" width="64" height="${INTERIOR + 1}" fill="url(#kibble-pattern)"/>
                </g>
            </g>
            <path class="hopper-svg-outline" d="M6 4 H58 L45 54 H19 Z"/>
            <rect class="hopper-svg-spout" x="27" y="54" width="10" height="9" rx="2"/>
            <path class="hopper-svg-bowl" d="M14 72 H50 Q48 81 32 81 Q16 81 14 72 Z"/>
        </svg>
        <div class="hopper-info">
            <div class="hopper-headline"><span class="hopper-pct"></span> <span class="hopper-lbs"></span></div>
            <div class="hopper-refill-by"></div>
            <div class="hopper-sub hopper-days"></div>
            <div class="hopper-sub hopper-capacity"></div>
        </div>
    </div>`;

let shownPct = null;

function renderLearning(body, hopper) {
    shownPct = null;
    setHTML(body, html`
        <div class="hopper-learning">
            <span class="hopper-amount">${hopper.learning_amount}</span>
            dispensed since refill on ${hopper.last_refill_label}
        </div>
        <p class="setting-description">Capacity is learned from refills — when you top it up, tap "I refilled it" and give a rough guess of what was left.</p>`);
}

function renderLevel(body, hopper) {
    if (!$('.hopper-visual', body)) {
        setHTML(body, HOPPER_SVG);
        // Start empty so the first level glides up into place
        $('.hopper-fill', body).style.transform = `translateY(${INTERIOR}px)`;
    }
    const svg = $('.hopper-svg', body);
    svg.classList.toggle('is-low', hopper.low);
    svg.setAttribute('aria-label', `Hopper about ${hopper.pct} percent full`);
    // Next frame, so a freshly built drawing transitions from its empty start
    requestAnimationFrame(() => {
        $('.hopper-fill', body).style.transform = `translateY(${INTERIOR * (1 - hopper.level)}px)`;
    });

    tweenNumber($('.hopper-pct', body), shownPct ?? hopper.pct, hopper.pct, n => `~${n}% full`);
    shownPct = hopper.pct;

    const lbs = $('.hopper-lbs', body);
    lbs.textContent = hopper.lbs_label || '';
    lbs.hidden = !hopper.lbs_label;
    const refillBy = $('.hopper-refill-by', body);
    refillBy.textContent = hopper.refill_by || '';
    refillBy.hidden = !hopper.refill_by;
    refillBy.classList.toggle('is-urgent', hopper.refill_urgent);
    const days = $('.hopper-days', body);
    days.textContent = hopper.days_label || '';
    days.hidden = !hopper.days_label;
    $('.hopper-capacity', body).textContent = hopper.capacity_label;
}

export function renderHopper(hopper) {
    const body = $('#hopper-body');
    if (hopper.learning) renderLearning(body, hopper);
    else renderLevel(body, hopper);

    // Preselect the app's own level guess — but never under an open form
    const form = $('.refill-form');
    if (form.hidden) $('#remaining_pct').value = String(hopper.refill_default);
}

export function initHopper() {
    const toggle = $('#refill-toggle');
    const form = $('.refill-form');
    const showForm = open => {
        toggle.hidden = open;
        form.hidden = !open;
        if (open) pulse(form);
    };
    toggle.addEventListener('click', () => showForm(true));
    $('#refill-cancel').addEventListener('click', () => showForm(false));
    form.addEventListener('submit', async e => {
        e.preventDefault();
        const submit = $('button[type="submit"]', form);
        submit.disabled = true;
        const result = await mutate('/refill', {
            remaining_pct: $('#remaining_pct').value,
            lbs_added: $('#lbs_added').value,
        });
        submit.disabled = false;
        if (result.ok) {
            $('#lbs_added').value = '';
            showForm(false);
        }
    });
}
