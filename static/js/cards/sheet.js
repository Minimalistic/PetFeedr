// Schedule editor sheet. Edits are optimistic: the row changes the moment
// you tap, the server confirms in the background, and a failure snaps the
// row back (store.revert) with a toast. Rows are keyed by their set time and
// animate in and out instead of the list being redrawn.

import { $, $$, html, setHTML, expandIn, collapseOut, animate } from '../dom.js';
import { mutate } from '../store.js';
import { portionRadios } from './feed.js';

const CONFIRM_MS = 3000;
let portions = [];

function chipLabel(row) {
    return row.is_fixed
        ? `Fixed time. Tap to vary ${row.time} by 30 minutes`
        : `Varies by 30 minutes. Tap to fix ${row.time}`;
}

function rowMarkup(row) {
    return html`
        <span class="sched-time">${row.time}</span>
        <div class="portion-segmented is-compact" role="radiogroup" aria-label="Portion for ${row.time}">
            ${portionRadios(portions, row.portion, `portion-${row.base_time}`)}
        </div>
        <button type="button" class="sched-chip ${row.is_fixed ? 'is-fixed' : ''}" data-action="toggle"
                aria-label="${chipLabel(row)}">${row.is_fixed ? 'Fixed' : '±30m'}</button>
        <button type="button" class="btn-icon btn-delete" data-action="delete"
                aria-label="Delete ${row.time} feeding">✕</button>`;
}

function setChip(chip, row) {
    chip.classList.toggle('is-fixed', row.is_fixed);
    chip.textContent = row.is_fixed ? 'Fixed' : '±30m';
    chip.setAttribute('aria-label', chipLabel(row));
}

// Bring an existing row in line with state without rebuilding it, so focus
// and any running animation survive
function updateRow(li, row) {
    const radio = $(`input[value="${row.portion}"]`, li);
    if (radio && !radio.checked) radio.checked = true;
    setChip($('.sched-chip', li), row);
    if (li.dataset.removing) {
        // A delete that failed: bring the row back
        delete li.dataset.removing;
        li.getAnimations().forEach(a => a.cancel());
    }
}

export function renderSheet(rows) {
    const list = $('#sched-list');
    $('#sched-legend').hidden = rows.length === 0;
    const existing = new Map($$('.sched-row', list).map(li => [li.dataset.key, li]));

    let previous = null;
    for (const row of rows) {
        let li = existing.get(row.base_time);
        if (li) {
            updateRow(li, row);
            existing.delete(row.base_time);
        } else {
            li = document.createElement('li');
            li.className = 'sched-row';
            li.dataset.key = row.base_time;
            setHTML(li, rowMarkup(row));
            // Keep the list in time order as rows arrive
            if (previous) previous.after(li);
            else list.prepend(li);
            if (list.dataset.ready) {
                expandIn(li);
                animate(li, [{ background: 'color-mix(in srgb, var(--color-primary) 22%, var(--color-bg))' },
                             { background: 'var(--color-bg)' }], { duration: 1400, delay: 250 });
            }
        }
        previous = li;
    }
    for (const gone of existing.values()) {
        collapseOut(gone).then(() => gone.remove());
    }
    list.dataset.ready = 'true';
}

// Two taps to delete: the first arms the button for a few seconds
function armOrConfirm(btn) {
    if (btn.dataset.armed) {
        clearTimeout(Number(btn.dataset.armed));
        delete btn.dataset.armed;
        btn.classList.remove('confirming');
        btn.textContent = '✕';
        return true;
    }
    btn.textContent = 'Sure?';
    btn.classList.add('confirming');
    btn.dataset.armed = String(setTimeout(() => {
        delete btn.dataset.armed;
        btn.classList.remove('confirming');
        btn.textContent = '✕';
    }, CONFIRM_MS));
    return false;
}

function initList() {
    const list = $('#sched-list');

    list.addEventListener('change', e => {
        const radio = e.target.closest('input[type="radio"]');
        if (!radio) return;
        const li = radio.closest('.sched-row');
        // The radio is already showing the new choice — that's the optimistic part
        mutate('/update_portion', { base_time: li.dataset.key, portion: radio.value });
    });

    list.addEventListener('click', e => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const li = btn.closest('.sched-row');
        const baseTime = li.dataset.key;

        if (btn.dataset.action === 'toggle') {
            const nowFixed = !btn.classList.contains('is-fixed');
            setChip(btn, { is_fixed: nowFixed, time: $('.sched-time', li).textContent });
            mutate('/toggle_fixed', { base_time: baseTime });
        } else if (btn.dataset.action === 'delete' && armOrConfirm(btn)) {
            li.dataset.removing = 'true';
            collapseOut(li);
            mutate('/delete', { base_time: baseTime });
        }
    });
}

function initAddForm() {
    const form = $('.add-form');
    setHTML($('#add-portions'), portionRadios(portions, null, 'portion'));
    $('#add-portions input').checked = true;  // smallest by default

    form.addEventListener('submit', async e => {
        e.preventDefault();
        const submit = $('button[type="submit"]', form);
        submit.disabled = true;
        submit.textContent = 'Adding…';
        const fields = {
            feeding_time: $('#feeding_time').value,
            portion: $('#add-portions input:checked')?.value || '',
        };
        if ($('input[name="randomize"]', form).checked) fields.randomize = 'on';
        const result = await mutate('/add', fields);
        submit.disabled = false;
        submit.textContent = 'Add Feeding';
        if (result.ok) $('#feeding_time').value = '';
    });
}

export function openSheet({ focusAdd = false } = {}) {
    const sheet = $('#schedule-sheet');
    if (sheet.open) return;
    sheet.showModal();
    if (focusAdd) {
        $('#sheet-add').scrollIntoView({ block: 'nearest' });
        $('#feeding_time').focus();
    } else {
        // showModal() focuses the first control (a portion radio); park focus
        // on the close button so nothing looks pre-selected
        $('[data-close-sheet]', sheet).focus();
    }
}

export function initSheet(state) {
    portions = state.portions;
    const sheet = $('#schedule-sheet');
    $('[data-close-sheet]', sheet).addEventListener('click', () => sheet.close());
    // A click that lands on the <dialog> itself (not its contents) is the backdrop
    sheet.addEventListener('click', e => { if (e.target === sheet) sheet.close(); });

    $('#edit-schedule-btn').addEventListener('click', () => openSheet());
    $('#timeline-body').addEventListener('click', e => {
        if (e.target.closest('[data-action="add-first"]')) openSheet({ focusAdd: true });
    });

    initList();
    initAddForm();
}
