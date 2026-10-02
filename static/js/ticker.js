// One shared clock for everything that moves with time (countdown, "now"
// markers), so a dozen cards don't each run their own setInterval.

const listeners = new Set();

export function onTick(fn) {
    listeners.add(fn);
    fn(new Date());
}

export function startTicker() {
    setInterval(() => {
        const now = new Date();
        for (const fn of listeners) fn(now);
    }, 1000);
}

export function minutesOfDay(date) {
    return date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60;
}
