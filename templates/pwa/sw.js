// Faso ISP Manager — Service Worker
// Strategy: network-only for HTML (CSRF safety) + cache-first for static assets

const CACHE = 'faso-isp-v1';

const STATIC_ASSETS = [
  '/static/css/main.css',
  '/static/img/icons/icon-192.png',
  '/static/img/icons/icon-512.png',
];

const OFFLINE_URL = '/offline/';

// ── Install: pre-cache static assets + offline page ──────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache =>
      cache.addAll([OFFLINE_URL, ...STATIC_ASSETS].filter(Boolean))
        .catch(() => {})
    )
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  const isStatic = url.pathname.startsWith('/static/');

  if (isStatic) {
    // Cache-first for static assets
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE).then(c => c.put(request, clone));
          }
          return response;
        });
      })
    );
  } else {
    // Network-only for HTML/API — fall back to offline page on failure
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(OFFLINE_URL).then(r => r || new Response('Hors ligne', { status: 503 }))
      )
    );
  }
});
