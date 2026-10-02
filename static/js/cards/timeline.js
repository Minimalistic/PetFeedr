// Today's Schedule card: dots on a time bar, a "now" line, the daily total.
// Dots are keyed by their set time and updated in place, so a slot going
// from upcoming to fed transitions its color instead of being redrawn.

import { $, $$, html, setHTML, animate } from '../dom.js';
import { onTick, minutesOfDay } from '../ticker.js';

let range = null;  // { start, end } minutes of day covered by the bar

function dotClass(slot, active) {
    return ['timeline-dot', `status-${slot.status}`, slot.is_past && 'is-past',
            slot.is_next && 'is-next', `portion-${slot.portion}`, active && 'active']
        .filter(Boolean).join(' ');
}

function dotContent(slot) {
    return html`${slot.badge ? html`<span class="dot-badge" aria-hidden="true">${slot.badge}</span>` : ''}
        <div class="timeline-tooltip">
            ${slot.time}<br>
            <span class="portion-${slot.portion}">${slot.portion}</span>${slot.is_fixed ? ' 🔒' : ''}<br>
            <span class="tooltip-status">${slot.status_text}</span>
        </div>`;
}

function renderHours(container, hours) {
    setHTML(container, html`${hours.map(h => html`
        <span class="timeline-hour-tick ${h.label ? 'has-label' : ''}" style="left: ${h.pct}%;"></span>
        ${h.label ? html`<span class="timeline-hour-label" style="left: ${h.pct}%;">${h.label}</span>` : ''}`)}`);
}

function ensureTimeline(body) {
    let timeline = $('.timeline', body);
    if (!timeline) {
        setHTML(body, html`<div class="timeline">
            <div class="timeline-bar"><div class="timeline-now" id="timeline-now" aria-hidden="true"></div></div>
            <div class="timeline-hours"></div>
        </div>`);
        timeline = $('.timeline', body);
    }
    return timeline;
}

function renderDots(bar, slots) {
    const existing = new Map($$('.timeline-dot', bar).map(el => [el.dataset.key, el]));
    for (const slot of slots) {
        let dot = existing.get(slot.key);
        const isNew = !dot;
        if (isNew) {
            dot = document.createElement('div');
            dot.dataset.key = slot.key;
            dot.setAttribute('role', 'button');
            dot.tabIndex = 0;
            bar.appendChild(dot);
        }
        const wasStatus = dot.dataset.status;
        dot.className = dotClass(slot, dot.classList.contains('active'));
        dot.dataset.status = slot.status;
        dot.style.setProperty('--dot-pos', `${slot.pct}%`);
        dot.setAttribute('aria-label', `${slot.time}, ${slot.portion} portion, ${slot.status_text}`);
        setHTML(dot, dotContent(slot));
        if (isNew) {
            animate(dot, [{ opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1 }], { duration: 300 });
        } else if (wasStatus !== slot.status) {
            // A slot just got fed (or missed): a small pop so the change registers
            animate(dot, [{ scale: 1 }, { scale: 1.5 }, { scale: 1 }], { duration: 450 });
        }
        existing.delete(slot.key);
    }
    for (const stale of existing.values()) {
        animate(stale, [{ opacity: 1 }, { opacity: 0, scale: 0.4 }], { duration: 200 })
            .then(() => stale.remove());
    }
}

function placeNow(now) {
    const nowEl = document.getElementById('timeline-now');
    if (!nowEl || !range) return;
    const pct = (minutesOfDay(now) - range.start) / (range.end - range.start) * 100;
    nowEl.hidden = pct < 0 || pct > 100;
    nowEl.style.left = `${pct}%`;
}

export function renderTimeline({ timeline, dailyTotal }) {
    const body = $('#timeline-body');
    const hasSlots = timeline.slots.length > 0;
    $('#edit-schedule-btn').hidden = !hasSlots;
    $('#daily-total').textContent = dailyTotal;

    if (!hasSlots) {
        range = null;
        setHTML(body, html`<div class="empty-onboarding">
            <svg class="empty-icon" width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <ellipse cx="24" cy="36" rx="18" ry="8"/>
                <path d="M6 36v-4c0-4.4 8.1-8 18-8s18 3.6 18 8v4"/>
                <circle cx="16" cy="12" r="4"/><circle cx="32" cy="12" r="4"/>
                <path d="M16 8c-1-3-4-5-4-5"/><path d="M32 8c1-3 4-5 4-5"/>
            </svg>
            <h3>No feedings scheduled yet</h3>
            <p>Set up your pet's feeding times to get started.</p>
            <button type="button" class="btn btn-secondary" data-action="add-first">Add First Feeding</button>
        </div>`);
        return;
    }

    const el = ensureTimeline(body);
    const hoursKey = JSON.stringify([timeline.start, timeline.end, timeline.hours]);
    if (el.dataset.hoursKey !== hoursKey) {
        renderHours($('.timeline-hours', el), timeline.hours);
        el.dataset.hoursKey = hoursKey;
    }
    range = { start: timeline.start, end: timeline.end };
    renderDots($('.timeline-bar', el), timeline.slots);
    placeNow(new Date());
}

export function initTimeline() {
    onTick(placeNow);
    // Tap a dot to toggle its tooltip (hover covers desktop)
    const body = $('#timeline-body');
    const toggle = dot => {
        $$('.timeline-dot.active', body).forEach(d => { if (d !== dot) d.classList.remove('active'); });
        dot.classList.toggle('active');
    };
    body.addEventListener('click', e => {
        const dot = e.target.closest('.timeline-dot');
        if (dot) toggle(dot);
    });
    body.addEventListener('keydown', e => {
        const dot = e.target.closest('.timeline-dot');
        if (dot && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            toggle(dot);
        }
    });
}
