/**
 * Service Worker Registration Helper for WayMate PWA & FCM
 */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
    console.log("[SW] Service Workers are not supported in this environment.")
    return null
  }

  // In development mode, skip service worker registration to prevent cache locking
  if (import.meta.env.DEV) {
    return null
  }

  try {
    const registration = await navigator.serviceWorker.register("/firebase-messaging-sw.js", {
      scope: "/"
    })

    // Force check for service worker updates on page load
    registration.update().catch(console.warn)

    // Listen for new service worker installation and reload page to apply updates
    registration.onupdatefound = () => {
      const installingWorker = registration.installing
      if (installingWorker) {
        installingWorker.onstatechange = () => {
          if (installingWorker.state === "installed" && navigator.serviceWorker.controller) {
            console.log("[SW] New version installed! Activating and reloading to apply update...")
            installingWorker.postMessage({ type: "SKIP_WAITING" })
            window.location.reload()
          }
        }
      }
    }

    console.log("[SW] Service Worker registered successfully with scope:", registration.scope)
    return registration
  } catch (error) {
    console.error("[SW] Service Worker registration failed:", error)
    return null
  }
}
