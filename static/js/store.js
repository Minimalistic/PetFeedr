// The one copy of dashboard state, and the rules for changing it.
//
// Cards register a selector + render function. apply() hands each card its
// slice only when that slice actually changed, so a poll that brings
// nothing new touches nothing on screen.

import { post, fetchState } from './api.js';
import { showToast } from './toast.js';

let current = null;
const cards = [];

// Mutations in flight, and a counter that ticks on every mutation start —
// a poll that began before a change must not paint over its result
let inFlight = 0;
let mutationSeq = 0;
let holdBusy = false;

export function register(select, render) {
    cards.push({ select, render, lastKey: undefined });
}

export function getState() {
    return current;
}

export function apply(state) {
    current = state;
    for (const card of cards) {
        // One card failing to draw must not stop the others (or the poller)
        try {
            const slice = card.select(state);
            const key = JSON.stringify(slice);
            if (key === card.lastKey) continue;
            card.lastKey = key;
            card.render(slice, state);
        } catch (err) {
            card.lastKey = undefined;  // try again on the next state
            console.error('[petfeedr] card render failed:', err);
        }
    }
}

// Throw away optimistic edits: re-render every card from the last state
// the server confirmed
export function revert() {
    for (const card of cards) card.lastKey = undefined;
    if (current) apply(current);
}

// The feed button holds this while a press is in progress, so a background
// refresh can't re-render the card under the user's thumb
export function setHoldBusy(flag) {
    holdBusy = flag;
}

export function isBusy() {
    return inFlight > 0 || holdBusy;
}

// POST a change. Success applies the server's state (the UI update);
// failure reverts any optimistic edit and explains in a toast.
export async function mutate(url, fields, { successToast = true } = {}) {
    inFlight++;
    mutationSeq++;
    let result;
    try {
        result = await post(url, fields);
    } finally {
        inFlight--;
    }
    if (result.ok) {
        if (result.state) apply(result.state);
        else refresh();  // change landed but the server couldn't snapshot; ask again
        if (successToast && result.message) showToast(result.message, 'success');
    } else {
        revert();
        showToast(result.message || 'Something went wrong', 'error');
        // A timed-out request may still have landed — fetch the truth now
        refresh();
    }
    return result;
}

// Background refresh. Resolves true when the server answered (even if
// the answer was discarded as stale), false when it couldn't be reached.
export async function refresh() {
    if (isBusy()) return true;
    const seqAtStart = mutationSeq;
    let state;
    try {
        state = await fetchState();
    } catch {
        return false;
    }
    if (seqAtStart === mutationSeq && !isBusy()) apply(state);
    return true;
}
