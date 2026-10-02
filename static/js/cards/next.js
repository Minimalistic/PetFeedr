// Next Feeding card: time, portion, live countdown, or the "all fed" cat.

import { $, html, trusted, setHTML, pulse } from '../dom.js';
import { onTick } from '../ticker.js';

const SLEEPING_CAT = trusted(`
    <svg class="all-fed-illustration" width="80" height="80" viewBox="0 0 100 100" fill="none" aria-hidden="true">
        <circle cx="50" cy="45" r="30" fill="white" opacity="0.9"/>
        <path d="M25,35 L32,10 L42,30" fill="white" opacity="0.9"/>
        <path d="M75,35 L68,10 L58,30" fill="white" opacity="0.9"/>
        <path d="M35,42 Q42,36 49,42" stroke="#555" stroke-width="2.5" fill="none" stroke-linecap="round"/>
        <path d="M51,42 Q58,36 65,42" stroke="#555" stroke-width="2.5" fill="none" stroke-linecap="round"/>
        <path d="M46,50 L50,53 L54,50" stroke="#f08080" stroke-width="2" fill="#f08080" stroke-linejoin="round"/>
        <text x="72" y="25" font-size="10" fill="white" opacity="0.7" font-family="sans-serif">z</text>
        <text x="80" y="18" font-size="13" fill="white" opacity="0.5" font-family="sans-serif">z</text>
        <text x="86" y="8" font-size="16" fill="white" opacity="0.3" font-family="sans-serif">z</text>
    </svg>`);

let target = null;     // 'HH:MM' of today's next feed, null when nothing is counting down
let lastText = '';

function countdownText(now) {
    const [h, m] = target.split(':').map(Number);
    const due = new Date(now);
    due.setHours(h, m, 0, 0);
    // Past due but not yet confirmed by the server: say so, rather than
    // wrapping around to "in 23h 59m" until the next refresh lands
    if (due <= now) return 'any moment now';
    const diffMin = Math.floor((due - now) / 60000);
    const hours = Math.floor(diffMin / 60);
    const mins = diffMin % 60;
    if (hours > 0) return `in ${hours}h ${mins}m`;
    if (mins > 0) return `in ${mins}m`;
    return 'any moment now';
}

function tick(now) {
    const el = document.getElementById('feeding-countdown');
    if (!el || !target) return;
    const text = countdownText(now);
    if (text === lastText) return;
    if (!lastText) {
        el.textContent = text;  // first paint: nothing to fade from
    } else {
        el.classList.add('updating');
        setTimeout(() => {
            el.textContent = text;
            el.classList.remove('updating');
        }, 150);
    }
    lastText = text;
}

let renderedOnce = false;

export function renderNext(next) {
    const card = $('#card-next');
    card.classList.toggle('all-fed', !!next?.all_fed);
    target = next && !next.all_fed ? next.time24 : null;
    lastText = '';

    let body;
    if (!next) {
        body = html`<div class="next-feeding-time">--:--</div>
                    <div class="next-feeding-none">No feedings scheduled</div>`;
    } else if (next.all_fed) {
        body = html`<div class="all-fed-content">
                        ${SLEEPING_CAT}
                        <div class="all-fed-text">All fed for today!</div>
                        <div class="all-fed-subtext">Next feeding tomorrow at ${next.time}</div>
                    </div>`;
    } else {
        body = html`<div class="next-feeding-time">${next.time}</div>
                    <div class="feeding-countdown" id="feeding-countdown"></div>
                    <div class="next-feeding-portion">
                        <span class="portion-badge portion-${next.portion}">${next.portion}</span>
                        ${next.randomized ? html`<span class="randomized-note">randomized</span>` : ''}
                    </div>`;
    }
    setHTML(card, html`<div class="card-label">Next Feeding</div>${body}`);
    tick(new Date());
    // The first render is the page appearing; later ones are real changes
    if (renderedOnce) pulse(card);
    renderedOnce = true;
}

export function initNext() {
    onTick(tick);
}
