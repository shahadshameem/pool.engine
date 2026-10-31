import { initializeApp } from "firebase/app"
import { getAuth, connectAuthEmulator } from "firebase/auth"
import {
  getFirestore,
  initializeFirestore,
  connectFirestoreEmulator,
  persistentLocalCache,
  persistentMultipleTabManager
} from "firebase/firestore"
import { getAnalytics, isSupported as isAnalyticsSupported } from "firebase/analytics"
import { getMessaging, isSupported as isMessagingSupported } from "firebase/messaging"
import { getFunctions } from "firebase/functions"

const apiKey = (import.meta.env?.VITE_FIREBASE_API_KEY as string) || ""
const projectId = (import.meta.env?.VITE_FIREBASE_PROJECT_ID as string) || "waymate-v3"

if (!apiKey) {
  throw new Error("[Firebase] Missing VITE_FIREBASE_API_KEY environment variable. Please configure it in your .env file or hosting environment.")
}

const firebaseConfig = {
  apiKey,
  authDomain: (import.meta.env?.VITE_FIREBASE_AUTH_DOMAIN as string) || `${projectId}.firebaseapp.com`,
  projectId,
  storageBucket: (import.meta.env?.VITE_FIREBASE_STORAGE_BUCKET as string) || `${projectId}.firebasestorage.app`,
  messagingSenderId: (import.meta.env?.VITE_FIREBASE_MESSAGING_SENDER_ID as string) || "",
  appId: (import.meta.env?.VITE_FIREBASE_APP_ID as string) || "",
  measurementId: (import.meta.env?.VITE_FIREBASE_MEASUREMENT_ID as string) || ""
}

// Initialize Firebase App exactly once
const app = initializeApp(firebaseConfig)

// Export reusable services with persistent local caching fallback
export const auth = getAuth(app)

let dbInstance: ReturnType<typeof getFirestore>
try {
  dbInstance = initializeFirestore(app, {
    localCache: persistentLocalCache({
      tabManager: persistentMultipleTabManager()
    })
  })
} catch (err) {
  console.warn("[Firebase] Local cache init failed, falling back to standard Firestore:", err)
  dbInstance = getFirestore(app)
}
export const db = dbInstance
export const functions = getFunctions(app)

const useEmulator = !import.meta.env?.PROD && (import.meta.env?.VITE_USE_EMULATOR === "true")

if (useEmulator) {
  const host = (import.meta.env?.VITE_EMULATOR_HOST as string) || "127.0.0.1"
  const authEmulatorHost = `http://${host}:9099`
  const firestoreEmulatorPort = 8080
  const firestoreEmulatorHost = host

  connectAuthEmulator(auth, authEmulatorHost, { disableWarnings: true })
  connectFirestoreEmulator(db, firestoreEmulatorHost, firestoreEmulatorPort)
}

// Initialize Messaging conditionally (supported in HTTPS/PWA environments)
export const messagingPromise = isMessagingSupported().then(yes => yes ? getMessaging(app) : null)

/**
 * DPDP Compliance: Analytics is gated behind explicit user consent.
 * Call initAnalyticsIfConsented() only after confirming the user has granted
 * the "analytics" consent purpose. Never auto-initialize without consent.
 *
 * ⚠️ SECURITY: Firebase Analytics measurement ID is baked into the bundle.
 *    Ensure your Firebase project's App Check or domain restrictions prevent
 *    unauthorized use.
 */
let _analyticsInstance: ReturnType<typeof getAnalytics> | null = null

export async function initAnalyticsIfConsented(): Promise<ReturnType<typeof getAnalytics> | null> {
  if (_analyticsInstance) return _analyticsInstance
  const supported = await isAnalyticsSupported()
  if (!supported) return null
  _analyticsInstance = getAnalytics(app)
  return _analyticsInstance
}

/** @deprecated Use initAnalyticsIfConsented() — analytics must be consent-gated per DPDP §6 */
export const analytics = Promise.resolve(null)

export default app
