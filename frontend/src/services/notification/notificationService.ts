import {
  collection,
  query,
  where,
  getDocs,
  addDoc,
  setDoc,
  serverTimestamp,
  doc,
  updateDoc,
  writeBatch,
  limit
} from "firebase/firestore"
import { db, auth } from "../../config/firebase"

export type NotificationType = "ride_request" | "ride_request_sent" | "request_accepted" | "request_rejected" | "ride_cancelled" | "request_cancelled" | "ride_match_found" | "cab_pool_invite" | "ride_started" | "ride_completed"

export interface AppNotification {
  id?: string
  userId: string
  type: NotificationType
  subType?: string
  title: string
  message: string
  rideId?: string
  matchedRideId?: string
  rideRequestId?: string
  cabPoolId?: string
  actorId?: string
  actorSnapshot?: {
    name: string
    college?: string
    department?: string
    year?: string
    verified?: boolean
  }
  rideSnapshot?: {
    from: string
    to: string
    date: string
    time: string
    seats?: number
  }
  read: boolean
  createdAt?: any
}

export const notificationService = {
  async createNotification(notification: Omit<AppNotification, "id" | "createdAt" | "read">): Promise<boolean> {
    try {
      // Ensure actorId reflects the current user if not explicitly provided
      const actorId = notification.actorId || auth.currentUser?.uid || undefined
      // Strip undefined values to prevent Firestore setDoc/addDoc invalid data error
      const sanitized = JSON.parse(JSON.stringify({
        ...notification,
        ...(actorId ? { actorId } : {})
      }))

      // Make write idempotent: use deterministic document ID when rideRequestId and type are present
      if (notification.rideRequestId && notification.type && notification.userId) {
        const customDocId = `${notification.type}_${notification.userId}_${notification.rideRequestId}`
        const docRef = doc(db, "notifications", customDocId)
        await setDoc(docRef, {
          ...sanitized,
          read: false,
          createdAt: serverTimestamp()
        }, { merge: true })
      } else {
        await addDoc(collection(db, "notifications"), {
          ...sanitized,
          read: false,
          createdAt: serverTimestamp()
        })
      }
      return true
    } catch (error) {
      console.error("Failed to create notification:", error)
      return false
    }
  },

  async getUserNotifications(userId: string): Promise<AppNotification[]> {
    try {
      const q = query(
        collection(db, "notifications"),
        where("userId", "==", userId),
        limit(50)
      )
      const snap = await getDocs(q)
      const notifs = snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as AppNotification))
      return notifs.sort((a, b) => {
        const timeA = a.createdAt?.toMillis ? a.createdAt.toMillis() : (a.createdAt?.seconds ? a.createdAt.seconds * 1000 : 0)
        const timeB = b.createdAt?.toMillis ? b.createdAt.toMillis() : (b.createdAt?.seconds ? b.createdAt.seconds * 1000 : 0)
        return timeB - timeA
      })
    } catch (error) {
      console.error("Failed to get notifications:", error)
      return []
    }
  },

  async markNotificationAsRead(notificationId: string): Promise<boolean> {
    try {
      const docRef = doc(db, "notifications", notificationId)
      await updateDoc(docRef, { read: true })
      return true
    } catch (error) {
      console.error("Failed to mark notification as read:", error)
      return false
    }
  },

  async markAllNotificationsAsRead(userId: string): Promise<boolean> {
    try {
      const q = query(
        collection(db, "notifications"),
        where("userId", "==", userId),
        where("read", "==", false),
        limit(50)
      )
      const snap = await getDocs(q)
      if (snap.empty) return true

      const batch = writeBatch(db)
      snap.docs.forEach(d => {
        batch.update(d.ref, { read: true })
      })
      await batch.commit()
      return true
    } catch (error) {
      console.error("Failed to mark all notifications as read:", error)
      return false
    }
  },

  /**
   * Resolves (marks read) any unread ride_match_found notifications for a user regarding a target ride.
   */
  async resolveUserMatchNotifications(userId: string, targetRideId: string): Promise<boolean> {
    try {
      const q = query(
        collection(db, "notifications"),
        where("userId", "==", userId),
        where("read", "==", false),
        limit(50)
      )
      const snap = await getDocs(q)
      if (snap.empty) return true

      const batch = writeBatch(db)
      let count = 0
      snap.docs.forEach(d => {
        const notif = d.data() as AppNotification
        if (
          notif.type === "ride_match_found" &&
          (notif.rideId === targetRideId || notif.matchedRideId === targetRideId)
        ) {
          batch.update(d.ref, { read: true })
          count++
        }
      })
      if (count > 0) {
        await batch.commit()
      }
      return true
    } catch (error) {
      console.error("Failed to resolve match notifications:", error)
      return false
    }
  },

  /**
   * Resolves (marks read) prior match & request notifications for a user when a request status changes.
   */
  async resolveUserRequestNotifications(userId: string, requestId?: string, rideId?: string): Promise<boolean> {
    try {
      const q = query(
        collection(db, "notifications"),
        where("userId", "==", userId),
        where("read", "==", false),
        limit(50)
      )
      const snap = await getDocs(q)
      if (snap.empty) return true

      const batch = writeBatch(db)
      let count = 0
      snap.docs.forEach(d => {
        const notif = d.data() as AppNotification
        const matchesRequest = requestId && notif.rideRequestId === requestId
        const matchesRide = rideId && (notif.rideId === rideId || notif.matchedRideId === rideId)
        const isResolvableType = ["ride_match_found", "ride_request", "ride_request_sent"].includes(notif.type)

        if (isResolvableType && (matchesRequest || matchesRide)) {
          batch.update(d.ref, { read: true })
          count++
        }
      })
      if (count > 0) {
        await batch.commit()
      }
      return true
    } catch (error) {
      console.error("Failed to resolve request notifications:", error)
      return false
    }
  }
}
