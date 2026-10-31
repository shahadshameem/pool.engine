import { useState, useEffect, useContext } from "react"
import { collection, query, where, onSnapshot } from "firebase/firestore"
import { db } from "../config/firebase"
import { useAuth } from "./useAuth"
import type { RideRequest, RideRequestStatus } from "../services/rideRequest/rideRequestService"
import { NotificationContext } from "../contexts/NotificationContext"

export interface UserRideRequestState {
  status: RideRequestStatus | "none"
  request: RideRequest | null
  loading: boolean
}

/**
 * Custom hook to get all real-time ride requests involving the specified user (both sent & received).
 * Returns a dictionary mapping keys (rideId, requesterId, rideOwnerId, composite) -> RideRequest.
 */
export function useUserRideRequests(userIdOverride?: string) {
  const { user } = useAuth()
  const userId = userIdOverride || user?.uid
  const globalNotifContext = useContext(NotificationContext)

  const isSelfUser = !userIdOverride || userIdOverride === user?.uid

  const [requestsMap, setRequestsMap] = useState<Record<string, RideRequest>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // If global NotificationContext is available and querying self user, shared state is used
    if (globalNotifContext && isSelfUser) {
      return
    }

    if (!userId) {
      setRequestsMap({})
      setLoading(false)
      return
    }

    setLoading(true)

    // 1. Sent requests (where user is requester)
    const qSent = query(
      collection(db, "rideRequests"),
      where("requesterId", "==", userId)
    )

    // 2. Received requests (where user is host/rideOwner)
    const qReceived = query(
      collection(db, "rideRequests"),
      where("rideOwnerId", "==", userId)
    )

    let sentDocs: RideRequest[] = []
    let receivedDocs: RideRequest[] = []
    let hasSentLoaded = false
    let hasReceivedLoaded = false

    const updateCombinedMap = () => {
      if (!hasSentLoaded || !hasReceivedLoaded) return

      const map: Record<string, RideRequest> = {}
      const allDocs = [...sentDocs, ...receivedDocs]

      const statusPriority: Record<string, number> = {
        accepted: 4,
        pending: 3,
        rejected: 2,
        cancelled: 1,
      }

      const addKey = (key: string, req: RideRequest) => {
        if (!key) return
        const existing = map[key]
        if (!existing) {
          map[key] = req
        } else {
          const currentPriority = statusPriority[req.status] || 0
          const existingPriority = statusPriority[existing.status] || 0
          if (currentPriority > existingPriority) {
            map[key] = req
          }
        }
      }

      allDocs.forEach((req) => {
        // Map by rideId (for outgoing requests to a specific ride)
        addKey(req.rideId, req)

        // Map by requesterId (for incoming requests from a specific passenger)
        addKey(req.requesterId, req)

        // Map by rideOwnerId (for outgoing requests to a host)
        addKey(req.rideOwnerId, req)

        // Composite key rideId_requesterId & rideId_rideOwnerId
        addKey(`${req.rideId}_${req.requesterId}`, req)
        addKey(`${req.rideId}_${req.rideOwnerId}`, req)
      })

      setRequestsMap(map)
      setLoading(false)
    }

    const unsubSent = onSnapshot(
      qSent,
      (snap) => {
        sentDocs = snap.docs.map((d) => ({ id: d.id, ...d.data() } as RideRequest))
        hasSentLoaded = true
        updateCombinedMap()
      },
      (err) => {
        console.error("Error listening to sent ride requests:", err)
        hasSentLoaded = true
        updateCombinedMap()
      }
    )

    const unsubReceived = onSnapshot(
      qReceived,
      (snap) => {
        receivedDocs = snap.docs.map((d) => ({ id: d.id, ...d.data() } as RideRequest))
        hasReceivedLoaded = true
        updateCombinedMap()
      },
      (err) => {
        console.error("Error listening to received ride requests:", err)
        hasReceivedLoaded = true
        updateCombinedMap()
      }
    )

    return () => {
      unsubSent()
      unsubReceived()
    }
  }, [userId, globalNotifContext, isSelfUser])

  if (globalNotifContext && isSelfUser) {
    return { requestsMap: globalNotifContext.requestsMap, loading: globalNotifContext.requestsLoading }
  }

  return { requestsMap, loading }
}

export function getRequestDetailsFromMap(
  requestsMap: Record<string, RideRequest>,
  rideId?: string | (string | undefined)[],
  actorOrHostId?: string
): { status: RideRequestStatus | "none"; request: RideRequest | null } {
  if (!requestsMap) {
    return { status: "none", request: null }
  }

  const idsToCheck: string[] = Array.isArray(rideId)
    ? rideId.filter((id): id is string => !!id && typeof id === "string")
    : (rideId ? [rideId] : [])

  if (idsToCheck.length === 0 && !actorOrHostId) {
    return { status: "none", request: null }
  }

  // 1. Check composite keys first (highest precision)
  if (actorOrHostId) {
    for (const id of idsToCheck) {
      const compositeKey = `${id}_${actorOrHostId}`
      if (requestsMap[compositeKey]) {
        return {
          status: requestsMap[compositeKey].status || "none",
          request: requestsMap[compositeKey]
        }
      }
    }
  }

  // 2. Direct match by rideId or requestId across provided candidate IDs
  for (const id of idsToCheck) {
    if (requestsMap[id]) {
      return {
        status: requestsMap[id].status || "none",
        request: requestsMap[id]
      }
    }
  }

  // 3. Fallback direct match by actorOrHostId only if no rideId was specified
  if (idsToCheck.length === 0 && actorOrHostId && requestsMap[actorOrHostId]) {
    return {
      status: requestsMap[actorOrHostId].status || "none",
      request: requestsMap[actorOrHostId]
    }
  }

  return { status: "none", request: null }
}

/**
 * Custom hook to get real-time request status for a specific rideId & optional hostId / userId.
 */
export function useRideRequestStatus(
  rideId?: string | (string | undefined)[],
  hostId?: string,
  userIdOverride?: string
): UserRideRequestState {
  const { requestsMap, loading } = useUserRideRequests(userIdOverride)

  if (loading) {
    return { status: "none", request: null, loading: true }
  }

  const { status, request } = getRequestDetailsFromMap(requestsMap, rideId, hostId)

  return {
    status,
    request,
    loading: false,
  }
}
