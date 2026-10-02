// Theme toggle: one button cycles Auto → Light → Dark. The initial theme is
// applied by an inline script in <head> so it lands before first paint.

import { showToast } from './toast.js';

const STORAGE_KEY = 'petfeedr-theme';
const MODES = ['auto', 'light', 'dark'];
const NAMES = { auto: 'Auto', light: 'Light', dark: 'Dark' };
const darkQuery = matchMedia('(prefers-color-scheme: dark)');
// Page background per theme (--color-bg) — the browser chrome / status bar
// area takes this color so it blends into the page
const CHROME_COLOR = { light: '#f0f4f4', dark: '#0d2224' };

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', CHROME_COLOR[theme]);
}

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
    applyTheme(effectiveTheme(mode));
    syncButton(btn, mode);
}

export function initTheme() {
    const btn = document.querySelector('.theme-toggle');
    if (!btn) return;
    syncButton(btn, storedMode());

    // Follow system changes while in Auto
    darkQuery.addEventListener('change', () => {
        if (storedMode() === 'auto') applyTheme(effectiveTheme('auto'));
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
