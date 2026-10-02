// Last 7 Days card: a row per day of feed marks on a 24h axis, a streak
// chip, and a detail panel for the tapped day. A refresh redraws the rows
// but keeps the selected day and its open panel.

import { $, $$, html, setHTML } from '../dom.js';
import { fetchDayDetail } from '../api.js';
import { onTick, minutesOfDay } from '../ticker.js';

let selectedDate = null;

function rowMarkup(day, guides) {
    return html`
        <div class="rhythm-row ${day.is_today ? 'is-today' : ''} ${day.date === selectedDate ? 'selected' : ''}"
             data-date="${day.date}" role="button" tabindex="0" aria-label="${day.aria}">
            <span class="rhythm-day">${day.day_label}</span>
            <div class="rhythm-track" aria-hidden="true">
                ${guides.map(g => html`<span class="rhythm-guide" style="--pct: ${g.pct}; --half: ${g.half_width};"></span>`)}
                ${day.is_today ? html`<span class="rhythm-now" id="rhythm-now"></span>` : ''}
                ${day.marks.map(m => html`
                    ${m.kind === 'late' ? html`<span class="rhythm-late-tail" style="--from: ${m.from_pct}; --pct: ${m.pct};"></span>` : ''}
                    <span class="rhythm-mark mark-${m.kind} ${m.portion ? `size-${m.portion}` : ''}"
                          style="--pct: ${m.pct};" title="${m.label}"></span>`)}
            </div>
            <span class="rhythm-cups">${day.cups_short}</span>
        </div>`;
}

const LEGEND = html`
    <div class="rhythm-legend" aria-hidden="true">
        <span><i class="rhythm-mark mark-fed"></i>fed</span>
        <span><i class="rhythm-mark mark-manual"></i>manual</span>
        <span><i class="rhythm-mark mark-late"></i>late</span>
        <span><i class="rhythm-mark mark-missed"></i>missed</span>
        <span><i class="rhythm-mark mark-upcoming"></i>upcoming</span>
        <span><i class="rhythm-guide-key"></i>scheduled</span>
    </div>`;

function placeNow(now) {
    const el = document.getElementById('rhythm-now');
    if (!el) return;
    el.style.left = `${minutesOfDay(now) / 1440 * 100}%`;
    el.style.display = 'block';
}

function closePanel() {
    selectedDate = null;
    $('#day-detail').hidden = true;
    $$('.rhythm-row.selected').forEach(r => r.classList.remove('selected'));
}

async function openDay(row) {
    const date = row.dataset.date;
    if (selectedDate === date) {
        closePanel();
        return;
    }
    selectedDate = date;
    $$('.rhythm-row').forEach(r => r.classList.toggle('selected', r === row));
    const panel = $('#day-detail');
    panel.hidden = false;
    setHTML(panel, html`<div class="day-detail-message">Loading…</div>`);

    try {
        const data = await fetchDayDetail(date);
        if (selectedDate !== date) return;  // tapped another day meanwhile
        if (!data.feedings.length) {
            setHTML(panel, html`<div class="day-detail-message">No feedings recorded</div>`);
            return;
        }
        const dayName = new Date(`${date}T12:00:00`)
            .toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
        setHTML(panel, html`
            <div class="day-detail-header">
                <span>${dayName}</span>
                <span class="day-detail-total">${data.total_cups} cups · ${data.total_feedings} feedings</span>
            </div>
            <ul class="day-detail-list">
                ${data.feedings.map(f => html`
                    <li class="day-detail-item">
                        <span class="day-detail-time">${f.time}</span>
                        <span class="day-detail-portion portion-${f.portion}" title="${f.cups} cups">${f.portion}<span class="detail-cups">${f.cups} cup${f.cups !== 1 ? 's' : ''}</span></span>
                        <span class="day-detail-type">${f.type}</span>
                    </li>`)}
            </ul>`);
    } catch {
        if (selectedDate === date) setHTML(panel, html`<div class="day-detail-message">Failed to load</div>`);
    }
}

export function renderStats(stats) {
    const streak = stats.streak;
    setHTML($('#streak-slot'), streak
        ? html`<span class="streak-chip ${streak.hot ? '' : 'is-muted'}" title="${streak.title}">${streak.hot ? html`<span aria-hidden="true">🔥</span> ` : ''}${streak.text}</span>`
        : html``);

    const body = $('#stats-body');
    if (!stats.has_data) {
        setHTML(body, html`<p class="empty-state">No feeding data yet</p>`);
        setHTML($('#stats-footer'), html``);
        closePanel();
        return;
    }

    // The selected day can roll out of the 7-day window at midnight
    if (selectedDate && !stats.days.some(d => d.date === selectedDate)) closePanel();

    setHTML(body, html`
        <div class="rhythm">
            <div class="rhythm-axis" aria-hidden="true">
                <span style="left: 0%;">12a</span><span style="left: 25%;">6a</span><span style="left: 50%;">12p</span><span style="left: 75%;">6p</span><span style="left: 100%;">12a</span>
            </div>
            ${stats.days.map(day => rowMarkup(day, stats.guides))}
        </div>
        ${LEGEND}`);
    placeNow(new Date());

    setHTML($('#stats-footer'), html`
        ${stats.week_summary ? html`<span class="week-summary">${stats.week_summary}</span>` : ''}
        ${stats.consumption_label ? html`<span class="consumption-rate" title="Estimated from last 7 days">${stats.consumption_label}</span>` : ''}`);
}

export function initStats() {
    onTick(placeNow);
    const body = $('#stats-body');
    body.addEventListener('click', e => {
        const row = e.target.closest('.rhythm-row');
        if (row) openDay(row);
    });
    // role="button" promises keyboard activation, so honor Enter/Space too
    body.addEventListener('keydown', e => {
        const row = e.target.closest('.rhythm-row');
        if (row && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            openDay(row);
        }
    });
}
