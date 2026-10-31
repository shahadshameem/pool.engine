import { doc, updateDoc, arrayUnion, arrayRemove } from "firebase/firestore"
import { getToken, onMessage } from "firebase/messaging"
import { db, messagingPromise } from "../../config/firebase"

import { notificationFeedback } from "../../utils/notificationSound"

const getVapidKey = (): string => {
  return (import.meta.env.VITE_FIREBASE_VAPID_KEY as string) || ""
}

export const fcmService = {
  /**
   * Prompts user for notification permission, retrieves FCM token,
   * and saves it to Firestore users/{uid}.fcmTokens (appending without overwriting).
   */
  async requestPermissionAndGetToken(userId: string): Promise<string | null> {
    if (typeof window === "undefined" || !("Notification" in window)) {
      console.log("[FCM] Desktop/Mobile OS notifications not supported by this browser.")
      return null
    }

    try {
      const permission = await Notification.requestPermission()
      if (permission !== "granted") {
        console.log("[FCM] Notification permission was denied or dismissed.")
        return null
      }

      const messaging = await messagingPromise
      if (!messaging) {
        console.warn("[FCM] Messaging is not supported in current environment.")
        return null
      }

      // Wait for Service Worker registration
      let registration: ServiceWorkerRegistration | undefined
      if ("serviceWorker" in navigator) {
        registration = await navigator.serviceWorker.ready
      }

      const vapidKey = getVapidKey()
      const tokenOptions: { serviceWorkerRegistration?: ServiceWorkerRegistration; vapidKey?: string } = {}
      if (registration) tokenOptions.serviceWorkerRegistration = registration
      if (vapidKey) tokenOptions.vapidKey = vapidKey

      const token = await getToken(messaging, tokenOptions)

      if (token) {
        console.log("[FCM] Successfully fetched FCM token:", token)
        await this.saveTokenToUser(userId, token)
        return token
      } else {
        console.warn("[FCM] No registration token returned.")
        return null
      }
    } catch (error) {
      console.error("[FCM] Error requesting notification token:", error)
      return null
    }
  },

  /**
   * Appends an FCM token to user's Firestore document array (fcmTokens).
   * Uses localStorage cache to skip redundant daily Firestore Writes.
   */
  async saveTokenToUser(userId: string, token: string): Promise<void> {
    if (!userId || !token) return
    const cacheKey = `fcm_saved_${userId}_${token.slice(-16)}`
    if (localStorage.getItem(cacheKey) === "true") {
      // Token already saved to Firestore for this user, skip write
      return
    }

    try {
      const userRef = doc(db, "users", userId)
      await updateDoc(userRef, {
        fcmTokens: arrayUnion(token)
      })
      localStorage.setItem(cacheKey, "true")
      console.log("[FCM] Token appended to Firestore profile for user:", userId)
    } catch (error) {
      console.error("[FCM] Failed to append FCM token to user document:", error)
    }
  },

  /**
   * Removes a specific FCM token from user's Firestore document.
   */
  async removeTokenFromUser(userId: string, token: string): Promise<void> {
    if (!userId || !token) return
    try {
      const userRef = doc(db, "users", userId)
      await updateDoc(userRef, {
        fcmTokens: arrayRemove(token)
      })
    } catch (error) {
      console.error("[FCM] Failed to remove FCM token from user document:", error)
    }
  },

  /**
   * Listens for incoming FCM messages while app is in foreground.
   */
  async listenForegroundMessages(callback?: (payload: any) => void): Promise<() => void> {
    const messaging = await messagingPromise
    if (!messaging) return () => {}
    return onMessage(messaging, (payload) => {
      console.log("[FCM] Foreground message received:", payload)
      const notifType = payload.data?.type || ""
      if (notifType === "ride_request") {
        notificationFeedback.playNotificationSound("request")
      } else if (notifType === "request_accepted" || notifType === "accepted") {
        notificationFeedback.playNotificationSound("accepted")
      } else if (notifType === "ride_match_found") {
        notificationFeedback.playNotificationSound("match")
      } else {
        notificationFeedback.playNotificationSound("default")
      }
      if (callback) callback(payload)
    })
  }
}
