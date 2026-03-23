const CACHE_NAME = 'petfeedr-v11';
const STATIC_ASSETS = [
    '/',
    '/static/styles.css',
    '/static/main.js',
];

// Cache static assets on install
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Clean up old caches on activate
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Network-first for navigation, cache-first for static assets
self.addEventListener('fetch', event => {
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => caches.match('/'))
        );
        return;
    }
    event.respondWith(
        caches.match(event.request).then(cached => cached || fetch(event.request))
    );
});
