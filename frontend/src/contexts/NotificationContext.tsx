import { createContext, useContext, useEffect, useState, useRef } from "react"
import type { ReactNode } from "react"
import { collection, query, where, onSnapshot, limit } from "firebase/firestore"
import { db } from "../config/firebase"
import { useAuth } from "../hooks/useAuth"
import { notificationService } from "../services/notification/notificationService"
import type { AppNotification } from "../services/notification/notificationService"
import { NotificationPopup } from "../components/waymate/NotificationPopup"
import { useNavigate } from "react-router-dom"
import { useToast } from "../components/feedback/ToastContext"
import { isRideExpired } from "../config/matchingConfig"
import { useUserRideRequests, getRequestDetailsFromMap } from "../hooks/useRideRequestStatus"

import type { RideRequest } from "../services/rideRequest/rideRequestService"
import { notificationFeedback } from "../utils/notificationSound"
import { fcmService } from "../services/messaging/fcmService"

interface NotificationContextType {
  unreadCount: number
  notifications: AppNotification[]
  markAsRead: (id: string) => Promise<void>
  markAllAsRead: () => Promise<void>
  requestsMap: Record<string, RideRequest>
  requestsLoading: boolean
}

export const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

// Notification types that display as blocking modals
const MODAL_NOTIFICATION_TYPES = ["ride_request", "ride_match_found"]

// Notification types that display as non-blocking toasts via ToastContext
const TOAST_NOTIFICATION_TYPES = [
  "ride_match_found",
  "request_accepted",
  "request_rejected",
  "request_cancelled",
  "ride_cancelled"
]

export function NotificationProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const { user, profile } = useAuth()
  const { requestsMap, loading: requestsLoading } = useUserRideRequests()
  const requestsMapRef = useRef(requestsMap)
  const requestsLoadingRef = useRef(requestsLoading)
  useEffect(() => {
    requestsMapRef.current = requestsMap
    requestsLoadingRef.current = requestsLoading
  }, [requestsMap, requestsLoading])

  // Live listener for requester's outgoing requests to trigger instant redirect when accepted
  const prevReqStatusesRef = useRef<Record<string, string>>({})
  const isReqInitialLoadRef = useRef(true)

  useEffect(() => {
    if (!user) {
      prevReqStatusesRef.current = {}
      isReqInitialLoadRef.current = true
      return
    }

    Object.entries(requestsMap).forEach(([key, req]) => {
      if (!req || req.requesterId !== user.uid) return
      const reqId = req.id || key
      const currentStatus = req.status
      const prevStatus = prevReqStatusesRef.current[reqId]

      // Detect real-time transition from "pending" to "accepted"
      if (!isReqInitialLoadRef.current && prevStatus === "pending" && currentStatus === "accepted") {
        const deterministicNotifId = `request_accepted_${user.uid}_${reqId}`
        if (!seenNotifIdsRef.current.has(deterministicNotifId)) {
          seenNotifIdsRef.current.add(deterministicNotifId)
          notificationFeedback.playNotificationSound("accepted")
          if (req.rideId) {
            const targetPath = `/rides/${req.rideId}`
            if (typeof window !== "undefined" && window.location.pathname === targetPath) {
              showToast("Your ride request was accepted!", "success")
            } else {
              showToast("Ride request accepted!", "success")
              navigate(targetPath)
            }
          }
        }
      }

      prevReqStatusesRef.current[reqId] = currentStatus
    })

    if (Object.keys(requestsMap).length > 0 || isReqInitialLoadRef.current) {
      isReqInitialLoadRef.current = false
    }
  }, [user, requestsMap, navigate, showToast])

  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [unreadCount, setUnreadCount] = useState(0)

  // Queue for modal popups (e.g. Compatible Ride Offer Found)
  const [popupQueue, setPopupQueue] = useState<AppNotification[]>([])
  const [currentPopup, setCurrentPopup] = useState<AppNotification | null>(null)

  // Track notifications we've already shown in a ref
  const seenNotifIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!user) {
      setNotifications([])
      setUnreadCount(0)
      setPopupQueue([])
      setCurrentPopup(null)
      seenNotifIdsRef.current.clear()
      return
    }

    const q = query(
      collection(db, "notifications"),
      where("userId", "==", user.uid),
      limit(50)
    )

    const unsubscribe = onSnapshot(q, (snapshot) => {
      const allNotifs: AppNotification[] = []
      let newUnreadCount = 0
      const newModals: AppNotification[] = []

      const prefs = profile?.notificationPreferences || {
        enabled: true,
        rideRequests: true,
        requestUpdates: true,
        rideCancellations: true,
        requestCancellations: true
      }

      console.log(`[NOTIF-DEBUG] onSnapshot fired. docs=${snapshot.docs.length}, seenIds=${seenNotifIdsRef.current.size}, currentPopup=${currentPopup?.id || 'null'}`)

      snapshot.docs.forEach(doc => {
        const data = { id: doc.id, ...doc.data() } as AppNotification;

        if (data.type === "ride_request") {
          console.log(`[NOTIF-DEBUG] Processing ride_request notif id=${data.id} read=${data.read} actorId=${data.actorId} rideId=${data.rideId}`)
        }

        // Auto-resolve stale notifications if state changed
        const candidateIds = [data.matchedRideId, data.rideId].filter(Boolean) as string[]
        const activeReqStatus = getRequestDetailsFromMap(requestsMapRef.current, candidateIds, data.actorId).status

        if (data.type === "ride_request") {
          console.log(`[NOTIF-DEBUG]   activeReqStatus=${activeReqStatus}`)
        }

        if (!data.read && data.id) {
          const isCurrentlyMountedPopup = currentPopup?.id === data.id
          if (data.type === "ride_match_found" && (activeReqStatus === "pending" || activeReqStatus === "accepted")) {
            // Only auto-resolve in background if an active pending/accepted request exists
            if (!isCurrentlyMountedPopup) {
              notificationService.markNotificationAsRead(data.id).catch(() => {})
              data.read = true
            }
          } else if ((data.type === "ride_request" || data.type === "ride_request_sent") && (activeReqStatus === "accepted" || activeReqStatus === "rejected" || activeReqStatus === "cancelled")) {
            if (!isCurrentlyMountedPopup) {
              console.log(`[NOTIF-DEBUG]   AUTO-RESOLVING ride_request notif id=${data.id} because activeReqStatus=${activeReqStatus}`)
              notificationService.markNotificationAsRead(data.id).catch(() => {})
              data.read = true
            }
          }
        }

        allNotifs.push(data)
        if (!data.read) {
          newUnreadCount++
        }
      })

      // Check all unread notifications for real-time popups & toasts
      if (prefs.enabled !== false) {
        allNotifs.forEach(data => {
          if (!data.read && data.id && !seenNotifIdsRef.current.has(data.id)) {
            let allowedByType = true
            if (data.type === "ride_request" && prefs.rideRequests === false) allowedByType = false
            if ((data.type === "request_accepted" || data.type === "request_rejected") && prefs.requestUpdates === false) allowedByType = false
            if (data.type === "ride_cancelled" && prefs.rideCancellations === false) allowedByType = false
            if (data.type === "request_cancelled" && prefs.requestCancellations === false) allowedByType = false

            if (data.type === "ride_request") {
              console.log(`[NOTIF-DEBUG] Popup check: id=${data.id} read=${data.read} seen=${seenNotifIdsRef.current.has(data.id)} allowedByType=${allowedByType}`)
            }

            if (allowedByType) {
              const isMatchExpired = data.type === "ride_match_found"
                ? isRideExpired(data.rideSnapshot?.date, data.rideSnapshot?.time)
                : false

              if (!isMatchExpired) {
                if (MODAL_NOTIFICATION_TYPES.includes(data.type)) {
                  if (data.type === "ride_match_found") {
                    // CRITICAL: Do not evaluate or push match modal while requests are still loading to prevent race condition
                    if (requestsLoadingRef.current) {
                      console.log(`[NOTIF-DEBUG] Postponing match modal check for id=${data.id} until requestsMap loads`)
                      return
                    }

                    const candidateIds = [data.matchedRideId, data.rideId].filter(Boolean) as string[]
                    const reqDetails = getRequestDetailsFromMap(requestsMapRef.current, candidateIds, data.actorId)
                    const currentReqStatus = reqDetails.status
                    const isOwnActor = data.actorId === user.uid
                    const hasValidRoute = !!(data.rideSnapshot?.from?.trim() && data.rideSnapshot?.to?.trim())

                    if (currentReqStatus === "pending" || currentReqStatus === "accepted") {
                      // Already requested - auto-resolve and suppress from modals
                      notificationService.markNotificationAsRead(data.id).catch(() => {})
                      data.read = true
                    } else if (data.subType === "active_creator_match" && (currentReqStatus === "none" || currentReqStatus === "rejected" || currentReqStatus === "cancelled") && !isOwnActor && hasValidRoute) {
                      newModals.push(data)
                    }
                  } else if (data.type === "ride_request") {
                    const reqDetails = getRequestDetailsFromMap(requestsMapRef.current, data.rideId, data.actorId)
                    const reqStatus = reqDetails.status

                    console.log(`[NOTIF-DEBUG]   Modal decision: reqStatus=${reqStatus} → ${reqStatus === "pending" || reqStatus === "none" ? "PUSH TO MODALS" : "MARK AS READ"}`)

                    if (reqStatus === "pending" || reqStatus === "none") {
                      newModals.push(data)
                    } else {
                      // Auto-resolve stale or non-pending request notification
                      notificationService.markNotificationAsRead(data.id).catch(() => {})
                      data.read = true
                    }
                  }
                } else if (TOAST_NOTIFICATION_TYPES.includes(data.type)) {
                  let notifTime = Date.now()
                  if (data.createdAt) {
                    if (typeof data.createdAt.toMillis === "function") {
                      notifTime = data.createdAt.toMillis()
                    } else if (typeof data.createdAt.seconds === "number") {
                      notifTime = data.createdAt.seconds * 1000
                    }
                  }
                  const now = Date.now()
                  // Trigger toast via unified ToastContext ONLY for fresh notifications (created within 2 mins)
                  if (now - notifTime < 120000) {
                    const toastType = data.type === "request_accepted" ? "success"
                      : data.type === "request_rejected" ? "error"
                      : data.type === "ride_cancelled" ? "warning" : "info"

                    if (data.type === "request_accepted") {
                      notificationFeedback.playNotificationSound("accepted")
                    } else {
                      notificationFeedback.playNotificationSound("default")
                    }
                    showToast(data.message || data.title || "New update", toastType)
                    seenNotifIdsRef.current.add(data.id)
                    notificationService.markNotificationAsRead(data.id).catch(() => {})
                  }
                }
              }
            }
          } else if (data.type === "ride_request" && data.id) {
            console.log(`[NOTIF-DEBUG] SKIPPED ride_request id=${data.id}: read=${data.read} seen=${seenNotifIdsRef.current.has(data.id)}`)
          }
        })
      }

      console.log(`[NOTIF-DEBUG] newModals count=${newModals.length}, types=[${newModals.map(m => m.type + ':' + m.id).join(', ')}]`)

      // Client-side sort by createdAt desc
      allNotifs.sort((a, b) => {
        const timeA = a.createdAt?.toMillis ? a.createdAt.toMillis() : 0;
        const timeB = b.createdAt?.toMillis ? b.createdAt.toMillis() : 0;
        return timeB - timeA;
      });
      setNotifications(allNotifs)
      setUnreadCount(newUnreadCount)

      // Add to modal queue with hard interrupt takeover for incoming ride_request
      if (newModals.length > 0) {
        const incomingReqNotif = newModals.find(m => m.type === "ride_request")

        if (incomingReqNotif) {
          console.log(`[NOTIF-DEBUG] SETTING currentPopup to ride_request id=${incomingReqNotif.id}`)
          notificationFeedback.playNotificationSound("request")
          setCurrentPopup(incomingReqNotif)
          setPopupQueue([])
          newModals.forEach(p => {
            if (p.id) seenNotifIdsRef.current.add(p.id)
          })
        } else {
          notificationFeedback.playNotificationSound("match")
          setPopupQueue(prev => {
            const newQueue = [...prev]
            newModals.forEach(p => {
              if (!newQueue.find(existing => existing.id === p.id)) {
                newQueue.push(p)
              }
            })
            return newQueue
          })
          newModals.forEach(p => {
            if (p.id) seenNotifIdsRef.current.add(p.id)
          })
        }
      }
    }, (error) => {
      console.error("Notification listener error:", error)
    })

    return () => unsubscribe()
  }, [user, profile, showToast])

  // Process modal queue
  useEffect(() => {
    if (!currentPopup && popupQueue.length > 0) {
      setCurrentPopup(popupQueue[0])
      setPopupQueue(prev => prev.slice(1))
    }
  }, [popupQueue, currentPopup])

  // Foreground FCM push message listener for vibration & audio chime
  useEffect(() => {
    let unsubscribe: (() => void) | undefined
    fcmService.listenForegroundMessages().then(unsub => {
      unsubscribe = unsub
    }).catch(err => {
      console.warn("[NotificationContext] Foreground FCM listener error:", err)
    })
    return () => {
      if (unsubscribe) unsubscribe()
    }
  }, [])

  // Auto-dismiss currentPopup when underlying request status transitions
  useEffect(() => {
    if (!currentPopup) return

    if (currentPopup.type === "ride_request") {
      const popupTargetId = currentPopup.matchedRideId || currentPopup.rideId
      const popupReqDetails = getRequestDetailsFromMap(requestsMap, popupTargetId, currentPopup.actorId)
      if (popupReqDetails.status === "cancelled" || popupReqDetails.status === "rejected" || popupReqDetails.status === "accepted") {
        setCurrentPopup(null)
      }
    } else if (currentPopup.type === "ride_match_found") {
      const candidateIds = [currentPopup.matchedRideId, currentPopup.rideId].filter(Boolean) as string[]
      const popupReqDetails = getRequestDetailsFromMap(requestsMap, candidateIds, currentPopup.actorId)
      if (popupReqDetails.status === "pending" || popupReqDetails.status === "accepted") {
        if (currentPopup.id) {
          notificationService.markNotificationAsRead(currentPopup.id).catch(() => {})
        }
        setCurrentPopup(null)
      }
    }
  }, [currentPopup, requestsMap])

  // Synchronize unread notifications and filter popup queue whenever requestsMap is loaded or updated
  useEffect(() => {
    if (requestsLoading || !user) return

    // 1. Auto-resolve unread ride_match_found notifications that have pending/accepted requests
    notifications.forEach(notif => {
      if (!notif.read && notif.id && notif.type === "ride_match_found") {
        const candidateIds = [notif.matchedRideId, notif.rideId].filter(Boolean) as string[]
        const reqDetails = getRequestDetailsFromMap(requestsMap, candidateIds, notif.actorId)
        if (reqDetails.status === "pending" || reqDetails.status === "accepted") {
          notificationService.markNotificationAsRead(notif.id).catch(() => {})
        }
      }
    })

    // 2. Remove any already-requested items from the modal queue
    setPopupQueue(prev => prev.filter(popup => {
      if (popup.type !== "ride_match_found") return true
      const candidateIds = [popup.matchedRideId, popup.rideId].filter(Boolean) as string[]
      const reqDetails = getRequestDetailsFromMap(requestsMap, candidateIds, popup.actorId)
      return reqDetails.status !== "pending" && reqDetails.status !== "accepted"
    }))
  }, [requestsLoading, requestsMap, user, notifications])

  const handleDismissPopup = async () => {
    if (currentPopup && currentPopup.id) {
      await notificationService.markNotificationAsRead(currentPopup.id).catch(() => {})
    }
    setCurrentPopup(null)
  }

  const handleCloseOnlyPopup = () => {
    if (currentPopup && currentPopup.id) {
      notificationService.markNotificationAsRead(currentPopup.id).catch(() => {})
    }
    setCurrentPopup(null)
  }

  const markAsRead = async (id: string) => {
    await notificationService.markNotificationAsRead(id)
  }

  const markAllAsRead = async () => {
    if (user) {
      await notificationService.markAllNotificationsAsRead(user.uid)
    }
  }

  return (
    <NotificationContext.Provider value={{ unreadCount, notifications, markAsRead, markAllAsRead, requestsMap, requestsLoading }}>
      {children}
      {currentPopup && (
        <NotificationPopup
          notification={currentPopup}
          onDismiss={handleDismissPopup}
          onCloseOnly={handleCloseOnlyPopup}
        />
      )}
    </NotificationContext.Provider>
  )
}

export function useNotifications() {
  const context = useContext(NotificationContext)
  if (context === undefined) {
    throw new Error("useNotifications must be used within a NotificationProvider")
  }
  return context
}
