// Service Worker for WayMate PWA & Firebase Cloud Messaging (FCM)
importScripts('https://www.gstatic.com/firebasejs/9.23.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.23.0/firebase-messaging-compat.js');

// Initialize Firebase app in service worker using standard project configuration
const firebaseConfig = {
  apiKey: "AIzaSyA6brHQy7IYaFTBy9Q7Qe2SsKSOS9lHTJ4",
  authDomain: "waymate-v3.firebaseapp.com",
  projectId: "waymate-v3",
  storageBucket: "waymate-v3.firebasestorage.app",
  messagingSenderId: "221510673406",
  appId: "1:221510673406:web:64a07fe58dcf89a5a756af"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

// Handle background FCM push notifications
messaging.onBackgroundMessage((payload) => {
  console.log('[firebase-messaging-sw.js] Received background message:', payload);

  const notificationTitle = payload.notification?.title || payload.data?.title || 'WayMate Alert';
  const notificationOptions = {
    body: payload.notification?.body || payload.data?.body || 'You have a new update in WayMate.',
    icon: payload.notification?.icon || payload.data?.icon || '/pwa-192x192.png',
    badge: '/pwa-192x192.png',
    data: payload.data || {},
    tag: payload.data?.type || 'waymate-notification',
    vibrate: [250, 100, 250, 100, 250],
    silent: false,
    renotify: true,
    requireInteraction: true,
    actions: [
      { action: 'view', title: 'Open WayMate' },
      { action: 'dismiss', title: 'Dismiss' }
    ]
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});

// Network-First strategy for HTML navigation & PWA shell to ensure deployed updates load immediately
const CACHE_NAME = 'waymate-pwa-shell-v5';
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/pwa-192x192.png',
  '/pwa-512x512.png',
  '/logo.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch((err) => {
        console.warn('[SW] Cache addAll warning:', err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  // Do not attempt caching for localhost in dev mode, third-party or Firebase API endpoints
  if (url.origin !== self.location.origin || url.hostname === 'localhost' || url.hostname === '127.0.0.1' || url.pathname.includes('/__/') || url.pathname.includes('firestore')) {
    return;
  }

  // Network-First for HTML navigation so deployed UI updates load instantly
  if (event.request.mode === 'navigate' || url.pathname === '/' || url.pathname === '/index.html') {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
          }
          return networkResponse;
        })
        .catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Stale-While-Revalidate for static assets
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      const fetchPromise = fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
        }
        return networkResponse;
      }).catch(() => null);

      return cachedResponse || fetchPromise;
    })
  );
});

// Click action on system notification
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.action === 'dismiss') {
    return;
  }
  const targetUrl = event.notification.data?.url || '/activity';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          if ('navigate' in client && targetUrl) {
            client.navigate(targetUrl);
          }
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
