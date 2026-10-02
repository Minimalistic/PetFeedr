// Theme toggle: one button cycles Auto → Light → Dark. The initial theme is
// applied by an inline script in <head> so it lands before first paint.

import { showToast } from './toast.js';

const STORAGE_KEY = 'petfeedr-theme';
const MODES = ['auto', 'light', 'dark'];
const NAMES = { auto: 'Auto', light: 'Light', dark: 'Dark' };
const darkQuery = matchMedia('(prefers-color-scheme: dark)');

function storedMode() {
    try { return localStorage.getItem(STORAGE_KEY) || 'auto'; } catch { return 'auto'; }
}

function effectiveTheme(mode) {
    if (mode === 'light' || mode === 'dark') return mode;
    return darkQuery.matches ? 'dark' : 'light';
}

function nextMode(mode) {
    return MODES[(MODES.indexOf(mode) + 1) % MODES.length];
}

function syncButton(btn, mode) {
    btn.dataset.mode = mode;
    btn.setAttribute('aria-label', `Theme: ${NAMES[mode]}. Tap for ${NAMES[nextMode(mode)]}.`);
}

function setMode(btn, mode) {
    try { localStorage.setItem(STORAGE_KEY, mode); } catch {}
    document.documentElement.setAttribute('data-theme', effectiveTheme(mode));
    syncButton(btn, mode);
}

export function initTheme() {
    const btn = document.querySelector('.theme-toggle');
    if (!btn) return;
    syncButton(btn, storedMode());

    // Follow system changes while in Auto
    darkQuery.addEventListener('change', () => {
        if (storedMode() === 'auto') {
            document.documentElement.setAttribute('data-theme', effectiveTheme('auto'));
        }
    });

    let lastToast = null;
    btn.addEventListener('click', () => {
        const mode = nextMode(btn.dataset.mode);
        setMode(btn, mode);
        // Auto can look identical to the mode you were just in, so say it —
        // replacing the previous toast so quick taps don't stack them up
        lastToast?.remove();
        lastToast = showToast(`Theme: ${NAMES[mode]}`, 'info', 1500);
    });
}
