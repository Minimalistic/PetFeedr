// Talking to the feeder. Every change route answers with the fresh
// dashboard state, so a successful call is also the UI update.

const NETWORK_ERROR = 'Network error — please try again';
const TIMEOUT_ERROR = "The feeder didn't answer — please try again";
// A request that hangs (phone network dropped mid-flight) must end: the store
// pauses background refreshes while a change is in flight
const REQUEST_TIMEOUT_MS = 15000;

// fetch() with a deadline. AbortController + setTimeout rather than
// AbortSignal.timeout(), which older iOS Safari lacks
async function fetchWithTimeout(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

// Never rejects: callers get { ok, message, state } and decide what to show
export async function post(url, fields) {
    const body = new FormData();
    for (const [key, value] of Object.entries(fields)) body.append(key, value);
    try {
        const resp = await fetchWithTimeout(url, { method: 'POST', body, headers: { Accept: 'application/json' } });
        const data = await resp.json().catch(() => ({}));
        return {
            ok: resp.ok && data.success === true,
            message: data.message || (resp.ok ? '' : 'Something went wrong'),
            state: data.state || null,
        };
    } catch (err) {
        // A timed-out POST may still have landed on the feeder; the next
        // refresh shows the truth either way
        return { ok: false, message: err.name === 'AbortError' ? TIMEOUT_ERROR : NETWORK_ERROR, state: null };
    }
}

// Rejects on any failure — the poller counts failures to show "offline"
export async function fetchState() {
    const resp = await fetchWithTimeout('/api/state', { headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error('Bad state payload');
    return data.data;
}

export async function fetchDayDetail(date) {
    const resp = await fetchWithTimeout(`/api/day-detail/${encodeURIComponent(date)}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'Bad day detail');
    return data;
}
