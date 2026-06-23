// VAI Service Worker — PWA offline support
// Cache-first for static assets, network-first for API calls.
const CACHE_NAME = 'vai-pwa-v1';

const STATIC_ASSETS = [
  '/',
  '/static/app.js',
  '/static/style.css',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// ----- install: pre-cache static assets -----
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ----- activate: clean old caches -----
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ----- fetch: cache-first for static, network-first for API -----
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API calls: network-first (don't cache stale LLM responses)
  if (url.pathname.startsWith('/run') || url.pathname.startsWith('/jobs/')
      || url.pathname.startsWith('/workflows')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          JSON.stringify({ error: 'You are offline. Please reconnect.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // Static assets: cache-first, then network fallback
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
      return cached || fetchPromise;
    })
  );
});
