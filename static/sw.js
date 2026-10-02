// Served through Flask (/sw.js), which stamps the asset version in below.
// Every deploy therefore changes this file's bytes, the browser installs the
// new worker, and the old cache is dropped — no hand-bumped cache name.
const CACHE_NAME = 'petfeedr-__ASSET_VERSION__';
const PRECACHE = [
    '/',
    '/static/styles.css?v=__ASSET_VERSION__',
    '/static/js/app.js',
    '/static/js/dom.js',
    '/static/js/api.js',
    '/static/js/store.js',
    '/static/js/toast.js',
    '/static/js/theme.js',
    '/static/js/ticker.js',
    '/static/js/cards/next.js',
    '/static/js/cards/timeline.js',
    '/static/js/cards/feed.js',
    '/static/js/cards/stats.js',
    '/static/js/cards/hopper.js',
    '/static/js/cards/sheet.js',
    '/static/js/cards/footer.js',
];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE)));
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Network-first for everything: the feeder is on the LAN, so the network is
// fast, and serving cached code first is how a phone ends up running last
// week's UI. The cache is only the fallback when the feeder is unreachable.
// Live data (/api/) is never cached — stale state would read as current.
self.addEventListener('fetch', event => {
    const { request } = event;
    if (request.method !== 'GET' || new URL(request.url).pathname.startsWith('/api/')) return;
    event.respondWith(
        fetch(request)
            .then(response => {
                if (response.ok) {
                    const copy = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
                }
                return response;
            })
            // ignoreSearch: the page asks for styles.css?v=<release>; any cached copy will do offline
            .catch(() => caches.match(request, { ignoreSearch: true }).then(cached =>
                cached || (request.mode === 'navigate' ? caches.match('/') : Response.error())))
    );
});
