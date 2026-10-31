import { useState, useEffect, useMemo } from "react"
import { useParams, useNavigate, useLocation } from "react-router-dom"
import { doc, onSnapshot, DocumentSnapshot, collection, query, where, getDocs } from "firebase/firestore"
import { db } from "../config/firebase"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { Modal } from "../components/ui/modal"
import { ConfirmModal } from "../components/ui/confirm-modal"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { useToast } from "../components/feedback/ToastContext"
import { EmptyState } from "../components/feedback/EmptyState"
import { rideService } from "../services/ride/rideService"
import { userService } from "../services/user/userService"
import { rideRequestService } from "../services/rideRequest/rideRequestService"
import { formatDate, formatTime12h, normalizePhoneForWhatsApp, formatBranchYear, getLocalDateString, cleanLocationDisplayName } from "../utils/formatters"
import { isRideExpired, isRidePastGracePeriod } from "../config/matchingConfig"
import { useRideRequestStatus } from "../hooks/useRideRequestStatus"
import { resolveFixedLocation } from "../config/locations"
import { ActiveRideSafetyModal } from "../components/safety/ActiveRideSafetyModal"
import { RideRouteVisualizerCard } from "../components/waymate/RideRouteVisualizerCard"
import { getCurrentLiveLocation } from "../utils/locationService"
import { useLiveLocationTracking, type ConfirmedParticipantInfo } from "../hooks/useLiveLocationTracking"
import { liveLocationService } from "../services/location/liveLocationService"
import { LiveTrackingSimControl } from "../components/waymate/LiveTrackingSimControl"
import { cn } from "../lib/utils"
import { isDevMockEnabled } from "../utils/devMock"

interface RideDetailsViewModel {
  id: string
  ownerId: string
  from: string
  to: string
  fromLocation?: any
  toLocation?: any
  date: string
  departureTime: string
  availableSeats: number
  hostName: string
  college: string
  department?: string
  year?: string
  hostVerified: boolean
  vehicle?: string
  meetingPoint: string
  notes?: string
  genderPolicy?: string
  status: string
  acceptedPassengers?: any[]
}

interface RidemateInfo {
  uid: string
  name: string
  college: string
  department?: string
  year?: string
  verified: boolean
  phone?: string | null
}

interface ProfileModalData {
  uid?: string
  name: string
  role: "host" | "passenger"
  isSelf: boolean
  department?: string
  year?: string
  college?: string
  verified?: boolean
  phone?: string | null
  relationshipStatus?: "accepted" | "pending" | "none" | "completed"
}

export function RideDetailsPage() {
  const { rideId } = useParams<{ rideId: string }>()
  const navigate = useNavigate()
  const { goBack, registerModal, registerActiveTripGuard } = useBackNavigation()
  const location = useLocation()
  const navState = location.state as {
    fromLocation?: any
    toLocation?: any
    date?: string
    departureTime?: string
    seats?: number
    pickupDistanceMeters?: number
    dropoffDistanceMeters?: number
    totalDistanceMeters?: number
    proximityBadge?: string
  } | null
  const { user, loading: authLoading, profileLoading } = useAuth()
  const { showToast } = useToast()
  const { status: liveRequestStatus, request: liveRequest, loading: requestStatusLoading } = useRideRequestStatus(rideId)

  const [isLoading, setIsLoading] = useState(true)
  const [ride, setRide] = useState<RideDetailsViewModel | null>(null)
  const [activeRequest, setActiveRequest] = useState<{ id: string; status: string } | null>(null)
  const [isCompletingRide, setIsCompletingRide] = useState(false)

  // Direct authoritative check on mount to eliminate any cache/hook delay
  useEffect(() => {
    if (!user || !rideId) return
    let isSubscribed = true

    const qReq = query(
      collection(db, "rideRequests"),
      where("requesterId", "==", user.uid),
      where("rideId", "==", rideId)
    )

    getDocs(qReq).then(snap => {
      if (!isSubscribed) return
      const active = snap.docs.map(d => ({ id: d.id, ...d.data() } as any)).find(r => r.status === "pending" || r.status === "accepted")
      if (active) {
        setActiveRequest({ id: active.id, status: active.status })
      }
    }).catch(err => {
      console.warn("Error checking direct ride request on RideDetailsPage:", err)
    })

    return () => { isSubscribed = false }
  }, [user, rideId])

  useEffect(() => {
    if (liveRequest) {
      setActiveRequest({ id: liveRequest.id!, status: liveRequest.status })
    } else if (liveRequestStatus === "none" && !requestStatusLoading) {
      setActiveRequest(null)
    }
  }, [liveRequest, liveRequestStatus, requestStatusLoading])

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [requestSeats, setRequestSeats] = useState(1)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)

  const [isCancelRideModalOpen, setIsCancelRideModalOpen] = useState(false)
  const [isConfirmStartModalOpen, setIsConfirmStartModalOpen] = useState(false)
  const [isConfirmCompleteModalOpen, setIsConfirmCompleteModalOpen] = useState(false)
  const [isCancellingRide, setIsCancellingRide] = useState(false)
  const [isStartingRide, setIsStartingRide] = useState(false)
  const [isCancelRequestModalOpen, setIsCancelRequestModalOpen] = useState(false)
  const [isSafetyModalOpen, setIsSafetyModalOpen] = useState(false)

  const [genderErrorState, setGenderErrorState] = useState<{ isOpen: boolean; code?: string; message?: string }>({ isOpen: false })
  const [cooldownErrorState, setCooldownErrorState] = useState<{ isOpen: boolean; message?: string }>({ isOpen: false })

  const [ownerRequests, setOwnerRequests] = useState<any[]>([])
  const [isProcessingRequest, setIsProcessingRequest] = useState<string | null>(null)
  const [hostPhone, setHostPhone] = useState<string | null>(null)
  const [passengers, setPassengers] = useState<RidemateInfo[]>([])
  const [profileModal, setProfileModal] = useState<ProfileModalData | null>(null)

  // Register active modal and sheet closures so Back closes them first
  useEffect(() => {
    if (isSafetyModalOpen) {
      return registerModal("safety-modal", () => setIsSafetyModalOpen(false), 10)
    }
  }, [isSafetyModalOpen, registerModal])

  useEffect(() => {
    if (isModalOpen) {
      return registerModal("request-seat-modal", () => setIsModalOpen(false), 5)
    }
  }, [isModalOpen, registerModal])

  useEffect(() => {
    if (isCancelRideModalOpen) {
      return registerModal("cancel-ride-modal", () => setIsCancelRideModalOpen(false), 5)
    }
  }, [isCancelRideModalOpen, registerModal])

  useEffect(() => {
    if (isConfirmStartModalOpen) {
      return registerModal("confirm-start-modal", () => setIsConfirmStartModalOpen(false), 5)
    }
  }, [isConfirmStartModalOpen, registerModal])

  useEffect(() => {
    if (isConfirmCompleteModalOpen) {
      return registerModal("confirm-complete-modal", () => setIsConfirmCompleteModalOpen(false), 5)
    }
  }, [isConfirmCompleteModalOpen, registerModal])

  useEffect(() => {
    if (isCancelRequestModalOpen) {
      return registerModal("cancel-request-modal", () => setIsCancelRequestModalOpen(false), 5)
    }
  }, [isCancelRequestModalOpen, registerModal])

  useEffect(() => {
    if (profileModal) {
      return registerModal("profile-modal", () => setProfileModal(null), 5)
    }
  }, [profileModal, registerModal])

  // 1. Live GPS auto-detect fallback if not navigated from search
  const [userLiveLocation, setUserLiveLocation] = useState<any>(navState?.fromLocation || null)

  useEffect(() => {
    if (navState?.fromLocation) {
      setUserLiveLocation(navState.fromLocation)
      return
    }
    let isSubscribed = true
    getCurrentLiveLocation()
      .then(loc => {
        if (isSubscribed) {
          setUserLiveLocation({
            lat: loc.lat,
            lng: loc.lng,
            name: loc.name || "Live Location"
          })
        }
      })
      .catch(() => {
        if (isSubscribed) {
          setUserLiveLocation({
            lat: 8.5459,
            lng: 76.9063,
            name: "Campus"
          })
        }
      })
    return () => { isSubscribed = false }
  }, [navState])

  // Computed status flags and Live Location Tracking hook
  const isOwner = Boolean(user && ride && user.uid === ride.ownerId)
  const isCancelled = ride?.status === "cancelled"
  const isExplicitlyCompleted = ride?.status === "completed"
  const isParticipant = Boolean(
    isOwner ||
    activeRequest?.status === "accepted" ||
    (user && Array.isArray(ride?.acceptedPassengers) && ride.acceptedPassengers.some((p: any) => (p.uid || p.requesterId) === user.uid))
  )
  const isExpired = Boolean(ride && isRideExpired(ride.date, ride.departureTime || (ride as any).time, ride.status))
  const isPastGrace = Boolean(ride && isRidePastGracePeriod(ride.date, ride.departureTime || (ride as any).time, ride.status, 60))

  // A ride is completed when:
  // 1. Explicitly completed (status === "completed")
  // 2. OR scheduled departure date/time has passed (isExpired is true)
  // 3. OR past participant grace period
  // 4. OR active request is marked completed
  const isCompleted = !isCancelled && (
    isExplicitlyCompleted ||
    isExpired ||
    isPastGrace ||
    activeRequest?.status === "completed"
  )
  const isJoined = !isCancelled && !isCompleted && Boolean(
    activeRequest?.status === "accepted" ||
    (user && Array.isArray(ride?.acceptedPassengers) && ride.acceptedPassengers.some((p: any) => (p.uid || p.requesterId) === user.uid))
  )
  const isTrackingEligible = Boolean(user && rideId && (isOwner || isJoined) && !isCancelled && !isCompleted)

  // Dynamically resolve contact number for profile modal if not already cached
  useEffect(() => {
    if (isCompleted || isCancelled) return
    if (!profileModal || profileModal.isSelf || profileModal.phone || !profileModal.uid || !rideId || !user) return
    if (profileModal.relationshipStatus !== "accepted") return

    let isCurrent = true
    userService.getContactInfo(profileModal.uid, user.uid, rideId)
      .then(contact => {
        if (isCurrent && contact?.phone) {
          setProfileModal(prev => prev && prev.uid === profileModal.uid ? { ...prev, phone: contact.phone } : prev)
        }
      })
      .catch(console.warn)

    return () => { isCurrent = false }
  }, [profileModal?.uid, profileModal?.relationshipStatus, profileModal?.phone, rideId, user, isCompleted, isCancelled])

  const isTripInProgress = isTrackingEligible && ride?.status === "started"
  useEffect(() => {
    return registerActiveTripGuard(
      "active-trip-guard",
      () => Boolean(isTripInProgress),
      "This ride has started and is currently in progress. Leaving this screen will keep your live location tracking active in the background."
    )
  }, [isTripInProgress, registerActiveTripGuard])

  const confirmedParticipants = useMemo<ConfirmedParticipantInfo[]>(() => {
    if (!ride) return []
    const list: ConfirmedParticipantInfo[] = [
      {
        uid: ride.ownerId,
        name: ride.hostName || "Trip Creator",
        isCreator: true,
        pickupLocation: ride.fromLocation
      }
    ]
    if (Array.isArray(ride.acceptedPassengers)) {
      ride.acceptedPassengers.forEach((p: any) => {
        const pUid = p.uid || p.requesterId
        if (pUid && pUid !== ride.ownerId) {
          list.push({
            uid: pUid,
            name: p.name || "Co-rider",
            isCreator: false,
            pickupLocation: p.pickupLocation
          })
        }
      })
    }
    return list
  }, [ride])

  const liveTracking = useLiveLocationTracking({
    rideId: rideId || "",
    userId: user?.uid,
    userName: user?.displayName || (isOwner ? (ride?.hostName || "Trip Creator") : "Co-rider"),
    isCreator: isOwner,
    role: isOwner ? "creator" : "co-rider",
    rideStatus: ride?.status || "active",
    confirmedParticipants,
    enabled: isTrackingEligible,
    initialCoords: userLiveLocation ? { lat: userLiveLocation.lat, lng: userLiveLocation.lng } : undefined,
    pickupCoords: ride?.fromLocation ? { lat: ride.fromLocation.latitude, lng: ride.fromLocation.longitude } : undefined
  })

  const hasMet = Boolean(
    isTrackingEligible &&
    (liveTracking.allParticipantsMet || (liveTracking.distanceBetweenUsers !== null && liveTracking.distanceBetweenUsers <= 45))
  )

  // 2. Real-time live subscription to rideRequests for this ride (Host live distance updates)
  useEffect(() => {
    if (!rideId || !user) return

    const qReqs = query(
      collection(db, "rideRequests"),
      where("rideId", "==", rideId)
    )

    const unsubscribe = onSnapshot(qReqs, async (snap) => {
      const rawReqs = snap.docs.map(d => ({ id: d.id, ...d.data() } as any))
      const reqsWithProfiles = await Promise.all(rawReqs.map(async r => {
        let requesterName = r.requesterName || "Passenger"
        let requesterCollege = r.requesterCollege || ""
        let requesterDepartment = r.requesterDepartment || ""
        let requesterYear = r.requesterYear || ""
        try {
          const p = await userService.getUserProfile(r.requesterId)
          if (p) {
            requesterName = p.name || requesterName
            requesterCollege = p.college || requesterCollege
            requesterDepartment = p.department || requesterDepartment
            requesterYear = p.year || requesterYear
          }
        } catch (e) {}
        return { ...r, requesterName, requesterCollege, requesterDepartment, requesterYear }
      }))
      setOwnerRequests(reqsWithProfiles)
    }, (err) => {
      console.warn("Requests onSnapshot error on RideDetailsPage:", err)
    })

    return () => unsubscribe()
  }, [rideId, user])

  useEffect(() => {
    const isMockMode = isDevMockEnabled()

    if (!authLoading && !user && !isMockMode) {
      const currentPath = typeof window !== "undefined" ? window.location.pathname + window.location.search : `/ride/${rideId}`
      const redirectPath = encodeURIComponent(currentPath)
      navigate(`/login?redirect=${redirectPath}`, { replace: true })
      return
    }

    if (!rideId) return

    if (isMockMode && (rideId.startsWith("mock-") || !user)) {
      setRide({
        id: rideId,
        ownerId: rideId === "mock-ride-passenger" ? "other-host-456" : "mock-user-123",
        from: rideId === "mock-ride-2" ? "CET" : "CET",
        to: rideId === "mock-ride-2" ? "Kottayam" : "TVM Central",
        date: "2026-09-28",
        departureTime: "09:00",
        availableSeats: 2,
        hostName: "Alex Student",
        college: "College of Engineering Trivandrum (CET)",
        department: "Electronics & Communication Engineering",
        year: "4th Year",
        hostVerified: true,
        vehicle: "Car",
        meetingPoint: "Main Gate",
        status: "active",
        acceptedPassengers: []
      })
      setIsLoading(false)
      return
    }

    const rideDocRef = doc(db, "rides", rideId)
    const unsubscribeRide = onSnapshot(rideDocRef, async (docSnap: DocumentSnapshot) => {
      if (!docSnap.exists()) {
        if (isMockMode) {
          setRide({
            id: rideId,
            ownerId: "mock-user-123",
            from: "CET",
            to: "TVM Central",
            date: "2026-09-28",
            departureTime: "09:00",
            availableSeats: 2,
            hostName: "Alex Student",
            college: "College of Engineering Trivandrum (CET)",
            department: "Electronics & Communication Engineering",
            year: "4th Year",
            hostVerified: true,
            vehicle: "Car",
            meetingPoint: "Main Gate",
            status: "active",
            acceptedPassengers: []
          })
          setHostPhone("+919876543210")
        } else {
          setRide(null)
          setPassengers([])
          setHostPhone(null)
        }
        setIsLoading(false)
        return
      }

      try {
        const rideData = { id: docSnap.id, ...docSnap.data() } as any

        if (rideData && rideData.ownerId) {
          const ownerProfile = await userService.getUserProfile(rideData.ownerId)
          const hostName = ownerProfile?.name || "Host"
          const college = ownerProfile?.college || "College"
          const department = ownerProfile?.department || ""
          const year = ownerProfile?.year || ""
          const hostVerified = !!ownerProfile?.collegeVerified

          setRide({
            id: rideData.id!,
            ownerId: rideData.ownerId,
            from: rideData.from,
            to: rideData.to,
            fromLocation: rideData.fromLocation,
            toLocation: rideData.toLocation,
            date: rideData.date,
            departureTime: rideData.departureTime,
            availableSeats: rideData.availableSeats,
            hostName,
            college,
            department,
            year,
            hostVerified,
            vehicle: rideData.vehicleType,
            meetingPoint: rideData.meetingPoint || "",
            notes: rideData.notes,
            genderPolicy: rideData.genderPolicy,
            status: rideData.status,
            acceptedPassengers: rideData.acceptedPassengers || []
          })

          const currentUid = user?.uid || "mock-user-123"

          const isDocCompleted = rideData.status === "completed" || rideData.status === "cancelled" || isRideExpired(rideData.date, rideData.departureTime || rideData.time, rideData.status)

          let hostContactPhone: string | null = null
          if (rideData.ownerId === currentUid) {
            hostContactPhone = ownerProfile?.phone || null
          } else if (!isDocCompleted) {
            try {
              const contact = await userService.getContactInfo(rideData.ownerId, currentUid, rideId)
              hostContactPhone = contact?.phone || null
            } catch (e) {}
          }
          setHostPhone(hostContactPhone)

          const isUserHost = rideData.ownerId === currentUid
          const acceptedList = Array.isArray(rideData.acceptedPassengers) ? rideData.acceptedPassengers : []
          const isUserAccepted = isUserHost || acceptedList.some((ap: any) => (ap.uid || ap.requesterId) === currentUid)
          let passengerEntries: RidemateInfo[] = []

          if (acceptedList.length > 0) {
            passengerEntries = await Promise.all(
              acceptedList.map(async (p: any) => {
                const passengerUid = p.uid || p.requesterId
                const isCurrent = passengerUid === currentUid
                const passengerProfile = await userService.getUserProfile(passengerUid)

                let passengerPhone: string | null = null
                if (isCurrent) {
                  passengerPhone = passengerProfile?.phone || null
                } else if (isUserAccepted && !isDocCompleted) {
                  try {
                    const contact = await userService.getContactInfo(passengerUid, currentUid, rideId)
                    passengerPhone = contact?.phone || null
                  } catch (e) {}
                }

                const name = passengerProfile?.name || p.name || "Passenger"
                return {
                  uid: passengerUid,
                  name: isCurrent ? `${name} (You)` : name,
                  college: passengerProfile?.college || p.college || "College",
                  department: passengerProfile?.department || p.department || "",
                  year: passengerProfile?.year || p.year || "",
                  verified: !!(passengerProfile?.collegeVerified ?? p.verified),
                  phone: passengerPhone,
                }
              })
            )
          }
          setPassengers(passengerEntries)

          if (isUserAccepted) {
            const reqs = await rideRequestService.getRideRequests(rideId)
            const reqsWithProfiles = await Promise.all(reqs.map(async r => {
              let requesterName = r.requesterName || "Passenger"
              let requesterCollege = r.requesterCollege || ""
              let requesterDepartment = r.requesterDepartment || ""
              let requesterYear = r.requesterYear || ""
              try {
                const p = await userService.getUserProfile(r.requesterId)
                if (p) {
                  requesterName = p.name || requesterName
                  requesterCollege = p.college || requesterCollege
                  requesterDepartment = p.department || requesterDepartment
                  requesterYear = p.year || requesterYear
                }
              } catch (e) {}
              return { ...r, requesterName, requesterCollege, requesterDepartment, requesterYear }
            }))
            setOwnerRequests(reqsWithProfiles)
          } else {
            setOwnerRequests([])
          }
        }
      } catch (err) {
        console.error("Error setting up ride details:", err)
      } finally {
        setIsLoading(false)
      }
    }, (err) => console.error("Ride details snapshot error:", err))

    return () => unsubscribeRide()
  }, [rideId, user])

  // Auto-finalize ended ride in Firestore & cleanup live locations
  useEffect(() => {
    if (!rideId || !ride || isCancelled || isExplicitlyCompleted) return
    if ((isExpired || isPastGrace) && (isOwner || isParticipant)) {
      rideService.completeRide(rideId, user?.uid || ride.ownerId).catch(console.warn)
      liveLocationService.cleanupAllLiveLocations(rideId).catch(console.warn)
    }
  }, [rideId, ride, isCancelled, isExplicitlyCompleted, isExpired, isPastGrace, isOwner, isParticipant, user])

  const handleCancelRideConfirm = async () => {
    if (!rideId || !user) return
    setIsCancellingRide(true)
    try {
      await rideService.cancelRide(rideId, user.uid)
      await liveLocationService.cleanupAllLiveLocations(rideId).catch(console.warn)
      showToast("Ride cancelled successfully", "info")
      setIsCancelRideModalOpen(false)
      navigate("/rides", { replace: true })
    } catch (err) {
      console.error("Failed to cancel ride:", err)
      showToast("Failed to cancel ride. Please try again.", "error")
    } finally {
      setIsCancellingRide(false)
    }
  }

  const handleStartRideClick = () => {
    if (passengers.length === 0) {
      setIsConfirmStartModalOpen(true)
    } else {
      handleStartRide()
    }
  }

  const handleStartRide = async () => {
    if (!rideId || !user || !ride) return
    setIsStartingRide(true)
    try {
      const res = await rideService.startRide(rideId, user.uid)
      if (res.success) {
        setRide(prev => prev ? { ...prev, status: "started" } : null)
        showToast("Ride marked as started! It will no longer appear in search.", "success")
      } else {
        showToast(res.message || "Failed to start ride.", "error")
      }
    } catch (err) {
      console.error("Failed to start ride:", err)
      showToast("Failed to start ride. Please try again.", "error")
    } finally {
      setIsStartingRide(false)
    }
  }

  const handleCompleteRide = async () => {
    if (!rideId || !user || !ride) return
    setIsCompletingRide(true)
    try {
      const res = await rideService.completeRide(rideId, user.uid)
      if (res.success) {
        await liveLocationService.cleanupAllLiveLocations(rideId).catch(console.warn)
        setRide(prev => prev ? { ...prev, status: "completed" } : null)
        showToast("Ride marked as completed!", "success")
      } else {
        showToast(res.message || "Failed to complete ride.", "error")
      }
    } catch (err) {
      console.error("Failed to complete ride:", err)
      showToast("Failed to complete ride. Please try again.", "error")
    } finally {
      setIsCompletingRide(false)
    }
  }

  const handleCancelRequestConfirm = async () => {
    if (!activeRequest || !user) return
    setIsCancelling(true)
    try {
      await rideRequestService.cancelRideRequest(activeRequest.id, user.uid)
      if (rideId && user.uid) {
        await liveLocationService.deleteLiveLocation(rideId, user.uid).catch(console.warn)
      }
      setActiveRequest(null)
      showToast("Request cancelled", "info")
      setIsCancelRequestModalOpen(false)
    } catch (error) {
      console.error("Cancel request error:", error)
      showToast("Couldn't cancel request.", "error")
    } finally {
      setIsCancelling(false)
    }
  }

  const handleAcceptRequest = async (requestId: string) => {
    if (!ride || !user) return
    setIsProcessingRequest(requestId)
    try {
      const res = await rideRequestService.acceptRideRequest(requestId, user.uid)
      if (!res.success) {
        showToast(res.message || "Failed to accept request.", "error")
        return
      }
      showToast("Request accepted!", "success")
    } catch (error: any) {
      showToast(error?.message || "Failed to accept request.", "error")
    } finally {
      setIsProcessingRequest(null)
    }
  }

  const handleRejectRequest = async (requestId: string) => {
    if (!ride || !user) return
    setIsProcessingRequest(requestId)
    try {
      const res = await rideRequestService.rejectRideRequest(requestId, user.uid)
      if (!res.success) {
        showToast(res.message || "Failed to reject request.", "error")
        return
      }
      showToast("Request rejected", "info")
    } catch (error: any) {
      showToast(error?.message || "Failed to reject request.", "error")
    } finally {
      setIsProcessingRequest(null)
    }
  }

  const handleRequestSeatSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ride || !user) return
    setIsSubmitting(true)
    try {
      const pickupLoc = navState?.fromLocation || userLiveLocation || {
        name: "Campus Pickup",
        lat: 8.5459,
        lng: 76.9063
      }
      const result = await rideRequestService.createRideRequest(
        {
          id: ride.id,
          ownerId: ride.ownerId,
          status: ride.status,
          availableSeats: ride.availableSeats,
          from: ride.from,
          to: ride.to,
          date: ride.date,
          departureTime: ride.departureTime,
          genderPolicy: ride.genderPolicy,
          fromLocation: ride.fromLocation
        },
        user.uid,
        requestSeats,
        "",
        pickupLoc
      )
      if (!result.success) {
        setIsModalOpen(false)
        if (result.code === "GENDER_VERIFICATION_REQUIRED" || result.code === "RIDE_GENDER_POLICY_RESTRICTED") {
          setGenderErrorState({ isOpen: true, code: result.code, message: result.message })
        } else if (result.code === "REQUEST_COOLDOWN") {
          setCooldownErrorState({ isOpen: true, message: result.message })
        } else {
          showToast(result.message, "error")
        }
        return
      }
      if (result.requestId) {
        setActiveRequest({ id: result.requestId, status: "pending" })
      }
      setIsModalOpen(false)
      showToast("Request sent! Waiting for host.", "success")
    } catch (error: any) {
      console.error("Request error:", error)
      showToast(error?.message || "Couldn't send request. Please try again.", "error")
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleFindAnotherRide = () => {
    if (!ride) {
      navigate("/home")
      return
    }

    const fromLoc = resolveFixedLocation(ride.from, ride.fromLocation, true)
    const toLoc = resolveFixedLocation(ride.to, ride.toLocation, false)
    const todayStr = getLocalDateString()
    const targetDate = (!ride.date || ride.date < todayStr) ? todayStr : ride.date
    const requestedSeats = liveRequest?.seatsRequested || 1

    navigate("/home", {
      state: {
        fromLocation: fromLoc,
        toLocation: toLoc,
        date: targetDate,
        departureTime: ride.departureTime || "",
        seats: requestedSeats,
      },
    })
  }

  const isRideLoading = (authLoading || profileLoading || isLoading) && !ride

  if (isRideLoading || !ride) {
    return (
      <MobileShell hideBottomNav className="flex flex-col space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <button
              onClick={goBack}
              className="p-2 -ml-2 rounded-full hover:bg-muted text-foreground transition-colors cursor-pointer"
              aria-label="Back"
            >
              <MaterialIcon name="arrow_back" className="text-[24px]" />
            </button>
            <h1 className="text-edex-heading font-bold text-foreground">Ride Details</h1>
          </div>
        </div>

        {isRideLoading ? (
          <div className="space-y-4 pt-1">
            {/* Skeleton Host Card */}
            <div className="h-[96px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4 flex items-center space-x-4">
              <div className="h-14 w-14 rounded-full bg-muted shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-5 w-36 bg-muted rounded-md" />
                <div className="h-4 w-48 bg-muted/60 rounded-md" />
              </div>
            </div>

            {/* Skeleton Route Card */}
            <div className="h-[160px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-5 space-y-3">
              <div className="h-4 w-1/3 bg-muted rounded-md" />
              <div className="h-6 w-3/4 bg-muted rounded-md" />
              <div className="h-4 w-1/2 bg-muted/60 rounded-md" />
            </div>

            {/* Skeleton Details Section */}
            <div className="h-[100px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4" />
          </div>
        ) : (
          <EmptyState
            icon={<MaterialIcon name="error_outline" className="text-[32px]" />}
            title="Ride not found"
            description="This ride may have been cancelled or deleted."
            actionLabel="Back to Home"
            onAction={() => navigate("/home")}
          />
        )}
      </MobileShell>
    )
  }

  const isCetZone = Boolean(
    (ride as any)?.matchedZoneId === "cet-front-gate" ||
    ride?.from?.toLowerCase().includes("cet") ||
    ride?.from?.toLowerCase().includes("college of engineering") ||
    ride?.meetingPoint?.toLowerCase().includes("cet")
  )
  const effectiveMeetingPoint = isCetZone
    ? "CET Front Gate"
    : (ride?.meetingPoint || null)

  return (
    <MobileShell
      hideBottomNav
      className="flex flex-col space-y-6"
      footer={
        <div className="sticky bottom-0 z-40 w-full bg-background/95 backdrop-blur border-t border-border/40 p-4 pb-[calc(1.25rem+env(safe-area-inset-bottom,16px))] mt-auto">
          {isCancelled || isCompleted ? (
            <button
              onClick={handleFindAnotherRide}
              className="w-full h-14 bg-[#C5FF00] text-black rounded-[18px] font-extrabold text-[16px] flex items-center justify-center space-x-2 shadow-sm hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer"
            >
              <MaterialIcon name="search" className="text-[22px]" />
              <span>Find Another Ride</span>
            </button>
          ) : isOwner ? (
            /* HOST (DRIVER / CREATOR) CONTROLS */
            <div className="space-y-2">
              {ride.status !== "started" ? (
                <>
                  <Button
                    variant={passengers.length === 0 && !hasMet ? "outline" : "primary"}
                    size="lg"
                    className={cn(
                      "w-full flex items-center justify-center space-x-2 font-extrabold shadow-sm active:scale-[0.98] transition-all cursor-pointer",
                      hasMet
                        ? "bg-[#C5FF00] text-black font-black hover:opacity-90 shadow-[0_0_15px_rgba(197,255,0,0.35)]"
                        : passengers.length === 0
                          ? "bg-card border border-border/80 text-foreground hover:bg-muted font-bold"
                          : "bg-[#C5FF00] text-black hover:opacity-90"
                    )}
                    onClick={handleStartRideClick}
                    disabled={isStartingRide}
                  >
                    <MaterialIcon name="play_arrow" className="text-[22px]" />
                    <span>{isStartingRide ? "Starting Ride..." : hasMet ? "Start Ride" : "Mark Ride Started"}</span>
                  </Button>

                  <Button
                    variant="danger"
                    size="lg"
                    className="w-full flex items-center justify-center space-x-2"
                    onClick={() => setIsCancelRideModalOpen(true)}
                  >
                    <MaterialIcon name="cancel" className="text-[20px]" />
                    <span>Cancel Ride</span>
                  </Button>
                </>
              ) : (
                <>
                  <div className="flex items-center justify-center space-x-2 text-[14px] text-[#3B82F6] font-bold py-2.5 bg-[#3B82F6]/10 rounded-[18px] border border-[#3B82F6]/30">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#3B82F6] animate-ping shrink-0" />
                    <span>Trip in Progress · Heading to Destination</span>
                  </div>
                  <Button
                    variant="primary"
                    size="lg"
                    className="w-full flex items-center justify-center space-x-2 bg-[#C5FF00] text-black font-extrabold shadow-sm hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer"
                    onClick={() => setIsConfirmCompleteModalOpen(true)}
                    disabled={isCompletingRide}
                  >
                    <MaterialIcon name="check_circle" className="text-[22px]" />
                    <span>{isCompletingRide ? "Completing Trip..." : "We've Arrived / End Trip"}</span>
                  </Button>
                </>
              )}
            </div>
          ) : isJoined ? (
            /* RIDEMATE (PASSENGER) CONTROLS - PASSENGER NEVER STARTS OR ENDS THE HOST'S TRIP */
            <div className="space-y-2">
              {ride.status !== "started" ? (
                <>
                  {hasMet ? (
                    <div className="flex items-center justify-center space-x-2 py-3 px-4 rounded-[16px] bg-[#C5FF00]/10 border border-[#C5FF00]/30 text-[#C5FF00] font-bold text-sm">
                      <span className="w-2 h-2 rounded-full bg-[#C5FF00] animate-pulse shrink-0" />
                      <span className="truncate">You&apos;re at pickup · Waiting for host to start ride</span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center space-x-2 py-3 px-4 rounded-[16px] bg-card border border-border/70 text-foreground font-semibold text-sm">
                      <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                      <span className="truncate">Reservation Confirmed · Meet {ride.hostName ? `${ride.hostName}` : "host"} at pickup</span>
                    </div>
                  )}

                  <Button
                    variant="danger"
                    size="lg"
                    className="w-full flex items-center justify-center space-x-2"
                    onClick={() => setIsCancelRequestModalOpen(true)}
                  >
                    <MaterialIcon name="close" className="text-[20px]" />
                    <span>Cancel Reservation</span>
                  </Button>
                </>
              ) : (
                <div className="flex items-center justify-center space-x-2 text-[14px] text-[#3B82F6] font-bold py-3 bg-[#3B82F6]/10 rounded-[18px] border border-[#3B82F6]/30">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#3B82F6] animate-ping shrink-0" />
                  <span>Trip in Progress · Travelling with {ride.hostName || "Host"}</span>
                </div>
              )}
            </div>
          ) : activeRequest?.status === "pending" ? (
            <div className="space-y-2">
              <div className="flex items-center justify-center space-x-2 text-[13px] text-muted-foreground">
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" />
                <span className="font-medium">Request Sent • Waiting for host response</span>
              </div>
              <Button
                variant="danger"
                size="lg"
                className="w-full flex items-center justify-center space-x-2"
                onClick={() => setIsCancelRequestModalOpen(true)}
              >
                <MaterialIcon name="close" className="text-[20px]" />
                <span>Cancel Request</span>
              </Button>
            </div>
          ) : (
            <Button
              variant="primary"
              size="lg"
              className="w-full h-14 bg-[#D7FF00] hover:bg-[#C5FF00] text-black font-extrabold text-[17px] rounded-full shadow-lg transition-all active:scale-[0.98] cursor-pointer"
              disabled={ride.availableSeats <= 0 || ride.status === "full" || requestStatusLoading}
              onClick={() => setIsModalOpen(true)}
            >
              {requestStatusLoading ? "Checking..." : ride.availableSeats <= 0 ? "Ride Full" : "Request Seat"}
            </Button>
          )}
        </div>
      }
    >
      {/* Navigation Header */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center space-x-3">
          <button
            onClick={goBack}
            className="h-10 w-10 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-white hover:bg-zinc-800 transition-colors cursor-pointer"
            aria-label="Back"
          >
            <MaterialIcon name="arrow_back" className="text-[20px] text-white" />
          </button>
          <h1 className="text-[22px] font-black text-white tracking-tight">Ride Details</h1>
        </div>
        <div className="flex items-center space-x-2">
          {user && (
            <button
              onClick={() => setIsSafetyModalOpen(true)}
              className="flex items-center gap-1.5 text-xs font-bold px-3.5 py-1.5 rounded-full border border-zinc-700/80 bg-zinc-900/90 text-white hover:bg-zinc-800 transition-colors cursor-pointer shadow-xs"
              title="Safety & Support"
            >
              <MaterialIcon name="shield" className="text-[16px] text-red-500" />
              <span>Safety</span>
            </button>
          )}
        </div>
      </div>

      {/* Completion Alert Banner */}
      {isCompleted && (
        <div className="bg-[#C5FF00]/10 border border-[#C5FF00]/30 rounded-[22px] p-4 flex flex-col space-y-3 text-white animate-in fade-in duration-200">
          <div className="flex items-start space-x-3">
            <MaterialIcon name="check_circle" className="text-[22px] text-[#C5FF00] shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="font-bold text-[15px] text-[#C5FF00]">This ride has ended</h3>
              <p className="text-[13px] text-zinc-300 mt-0.5 leading-snug">
                This trip has concluded. Live location sharing is deactivated and route summary is displayed below.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Cancellation Alert Banner */}
      {isCancelled && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-[22px] p-4 flex flex-col space-y-3 text-destructive animate-in fade-in duration-200">
          <div className="flex items-start space-x-3">
            <MaterialIcon name="cancel" className="text-[22px] shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="font-bold text-[15px]">This ride has been cancelled</h3>
              <p className="text-[13px] text-destructive/80 mt-0.5 leading-snug">
                {isOwner
                  ? "You have cancelled this ride. Any accepted passengers have been notified."
                  : "The host has cancelled this ride. Your reservation and requests are no longer active."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 1. First-time Consent Notice Banner (Privacy requirement) */}
      {isTrackingEligible && !liveTracking.hasConsent && (
        <div className="bg-[#0D0D0D] border border-[#C5FF00]/40 rounded-[22px] p-3.5 flex items-center justify-between gap-3 shadow-md animate-in fade-in">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-full bg-[#C5FF00]/20 flex items-center justify-center text-[#C5FF00] shrink-0">
              <MaterialIcon name="share_location" className="text-lg" />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-bold text-white leading-tight">Enable Live Location Sharing</div>
              <div className="text-[11px] text-zinc-400 truncate">Share GPS with co-riders to meet at the pickup point</div>
            </div>
          </div>
          <button
            type="button"
            onClick={liveTracking.grantConsent}
            className="bg-[#C5FF00] hover:bg-[#b2e600] text-black font-extrabold text-xs px-3.5 py-1.5 rounded-full shrink-0 shadow-sm transition-all active:scale-95 cursor-pointer"
          >
            Enable
          </button>
        </div>
      )}

      {/* 2. Proximity Met Alert Banner (Exact Match with design) */}
      {!isCompleted && hasMet && ride.status !== "started" && (
        <div className="bg-[#0e1d0f] border border-[#234226] rounded-[20px] p-4 flex items-center gap-3.5 shadow-sm animate-in fade-in duration-200">
          <div className="w-10 h-10 rounded-full bg-[#4ADE80] flex items-center justify-center text-black shrink-0 shadow-sm">
            <svg className="w-6 h-6 stroke-[3]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-bold text-[16px] text-[#4ADE80] leading-tight">
              You&apos;ve all met!
            </div>
            <div className="text-[13px] text-zinc-400 mt-1 leading-snug">
              Everyone has arrived at the pickup point. Ready to start!
            </div>
          </div>
        </div>
      )}

      {/* AUTO INTERACTIVE MAP VIEW & DISTANCE VISUALIZER */}
      <RideRouteVisualizerCard
        ride={{
          ...ride,
          pickupDistanceMeters: navState?.pickupDistanceMeters,
          dropoffDistanceMeters: navState?.dropoffDistanceMeters,
          totalDistanceMeters: navState?.totalDistanceMeters,
          proximityBadge: navState?.proximityBadge
        }}
        userPickup={navState?.fromLocation || userLiveLocation}
        userDropoff={navState?.toLocation}
        acceptedPassengers={passengers}
        pendingRequests={ownerRequests.filter(r => r.status === "pending")}
        isHost={isOwner}
        liveLocationState={isTrackingEligible ? liveTracking : undefined}
      />

      {/* People in this ride Card (Unified for live and completed/ended rides) */}
      <div className="bg-[#0d0e11] border border-zinc-800/80 rounded-[24px] p-5 shadow-sm space-y-3">
        {/* Card Header */}
        <div className="flex items-center justify-between pb-1">
          <h3 className="text-[17px] font-bold text-white tracking-tight">
            People in this ride
          </h3>
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-black/80 border border-emerald-500/40 text-[12px] font-bold text-[#4ADE80]">
            {!isCompleted && !isCancelled ? (
              <>
                <span className="w-2 h-2 rounded-full bg-[#4ADE80] animate-pulse" />
                <span>{hasMet ? `${1 + passengers.length}/${1 + passengers.length} arrived` : `${(liveTracking?.peerLocation && (liveTracking.distanceBetweenUsers ?? 999) <= 25) ? 2 : 1}/${1 + passengers.length} arrived`}</span>
              </>
            ) : isCompleted ? (
              <span>{1 + passengers.length} {1 + passengers.length === 1 ? "rider" : "riders"}</span>
            ) : (
              <span className="text-red-400">Cancelled</span>
            )}
          </div>
        </div>

        {/* Rows List */}
        <div className="divide-y divide-zinc-800/80">
          {/* 1. You */}
          <div className="flex items-center justify-between py-3.5 first:pt-2">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-3.5 h-3.5 rounded-full bg-[#3B82F6] ring-4 ring-[#3B82F6]/25 shrink-0 ml-1" />
              <span className="font-bold text-[15px] text-white truncate">
                You {isOwner ? "(Host)" : ""}
              </span>
            </div>
            <span className="text-[14px] text-zinc-400 font-medium shrink-0">
              {isCompleted ? "Completed" : isCancelled ? "Cancelled" : "Arrived"}
            </span>
          </div>

          {/* 2. Host (When current user is ridemate) */}
          {!isOwner && (
            <div
              onClick={() => {
                const relationshipStatus = isCompleted
                  ? "completed"
                  : (activeRequest?.status === "accepted" || isJoined ? "accepted" : (activeRequest?.status === "pending" ? "pending" : "none"))
                setProfileModal({
                  uid: ride.ownerId,
                  name: ride.hostName,
                  role: "host",
                  isSelf: false,
                  department: ride.department,
                  year: ride.year,
                  college: ride.college || "College of Engineering Trivandrum (CET)",
                  verified: ride.hostVerified,
                  phone: isCompleted ? null : hostPhone,
                  relationshipStatus,
                })
              }}
              className="flex items-center justify-between py-3.5 cursor-pointer hover:bg-white/[0.02] -mx-2 px-2 rounded-lg transition-colors group"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-6 h-6 rounded-full bg-[#22C55E]/15 flex items-center justify-center text-[#22C55E] shrink-0">
                  <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                    <path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"/>
                  </svg>
                </div>
                <div className="flex items-center gap-1.5 truncate">
                  <span className="font-bold text-[15px] text-white truncate group-hover:text-emerald-400 transition-colors">{ride.hostName || "Host"}</span>
                  <span className="text-[13px] text-zinc-400 font-normal shrink-0">(Host)</span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <span className="text-[14px] text-zinc-400 font-medium">
                  {isCompleted ? "Host" : isCancelled ? "Cancelled" : (hasMet || (liveTracking?.peerLocation && (liveTracking.distanceBetweenUsers ?? 999) <= 25) ? "Arrived" : "On the way")}
                </span>
                <MaterialIcon name="chevron_right" className="text-[18px] text-zinc-500 group-hover:text-white transition-colors" />
              </div>
            </div>
          )}

          {/* 3. Other Co-Riders / Passengers */}
          {passengers.filter(p => p.uid !== user?.uid).map((p) => (
            <div
              key={p.uid}
              onClick={() => {
                const relationshipStatus = isCompleted
                  ? "completed"
                  : ((isOwner || isJoined) ? "accepted" : "none")
                setProfileModal({
                  uid: p.uid,
                  name: p.name.replace(" (You)", ""),
                  role: "passenger",
                  isSelf: false,
                  department: p.department,
                  year: p.year,
                  college: p.college || "College of Engineering Trivandrum (CET)",
                  verified: p.verified,
                  phone: isCompleted ? null : p.phone,
                  relationshipStatus,
                })
              }}
              className="flex items-center justify-between py-3.5 cursor-pointer hover:bg-white/[0.02] -mx-2 px-2 rounded-lg transition-colors group"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-6 h-6 rounded-full bg-emerald-500/15 flex items-center justify-center text-emerald-400 font-bold text-[11px] shrink-0">
                  {p.name.charAt(0).toUpperCase()}
                </div>
                <div className="flex items-center gap-1.5 truncate">
                  <span className="font-bold text-[15px] text-white truncate group-hover:text-emerald-400 transition-colors">{p.name}</span>
                  <span className="text-[13px] text-zinc-400 font-normal shrink-0">(Rider)</span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <span className="text-[14px] text-zinc-400 font-medium">
                  {isCompleted ? "Completed" : isCancelled ? "Cancelled" : (hasMet ? "Arrived" : "Joined")}
                </span>
                <MaterialIcon name="chevron_right" className="text-[18px] text-zinc-500 group-hover:text-white transition-colors" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Route Timeline & Details Card */}
      <div className="bg-[#0D0D0D] border border-zinc-800/80 rounded-[22px] p-5 space-y-4 shadow-xs">
        {/* Route Vertical Timeline */}
        <div className="relative pl-7 py-1 flex flex-col justify-between space-y-3.5">
          {/* Dashed Connecting Line between Origin & Destination */}
          <div className="absolute left-[7px] top-[10px] bottom-[10px] w-[2px] border-l-2 border-dashed border-zinc-600" />

          {/* 1. Origin (From) */}
          <div className="relative flex flex-col justify-center min-w-0">
            <div className="absolute -left-[27px] top-1 h-3.5 w-3.5 rounded-full bg-[#3B82F6] ring-2 ring-[#3B82F6]/30 shrink-0" />
            <div className="font-bold text-[15px] text-white leading-snug truncate">
              {cleanLocationDisplayName(ride.from)}
            </div>
            {effectiveMeetingPoint && (
              <div className="text-[12px] text-amber-400 font-semibold mt-0.5 flex items-center gap-1">
                <span>📍 Meeting Point:</span>
                <span className="text-zinc-200">{effectiveMeetingPoint}</span>
              </div>
            )}
          </div>

          {/* 2. Departure Time - Exactly in the Center */}
          <div className="relative text-[13px] text-zinc-400 font-medium leading-tight py-0.5 select-none">
            {formatTime12h(ride.departureTime)}
          </div>

          {/* 3. Destination (To) */}
          <div className="relative flex items-center min-w-0">
            <div className="absolute -left-[27px] h-3.5 w-3.5 rounded-full bg-[#22C55E] ring-2 ring-[#22C55E]/30 shrink-0" />
            <div className="font-bold text-[15px] text-white leading-snug truncate flex-1">
              {cleanLocationDisplayName(ride.to)}
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-zinc-800/80 pt-3.5" />

        {/* Card Footer: Date & Seats Left */}
        <div className="flex items-center justify-between text-[13px]">
          <div className="flex items-center space-x-2 text-zinc-400">
            <MaterialIcon name="calendar_today" className="text-[16px] text-zinc-400" />
            <span>{formatDate(ride.date)}</span>
          </div>

          <div className="flex items-center space-x-1.5 text-white font-medium">
            <MaterialIcon name="airline_seat_recline_normal" className="text-[18px] text-white" />
            <span>{ride.availableSeats} {ride.availableSeats === 1 ? "seat left" : "seats left"}</span>
          </div>
        </div>
      </div>

      {/* Incoming Requests for Ride Pool Members */}
      {(isOwner || isJoined) && !isCompleted && ownerRequests.filter((r) => r.status === "pending").length > 0 && (
        <div className="space-y-3 pt-2">
          <h3 className="text-edex-subheading text-foreground font-bold">Ride Requests</h3>
          <div className="space-y-2">
            {ownerRequests
              .filter((r) => r.status === "pending")
              .map((req) => (
              <div key={req.id} className="bg-card border border-border/60 rounded-2xl p-4 space-y-3 shadow-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-bold text-[15px] text-foreground">{req.requesterName}</div>
                    <div className="text-[13px] text-muted-foreground">
                      {formatBranchYear(req.requesterDepartment, req.requesterYear, req.requesterCollege || "CET")} • {req.seatsRequested} seat{req.seatsRequested > 1 ? "s" : ""}
                    </div>
                  </div>
                </div>
                {req.status === "pending" && (
                  <div className="flex items-center space-x-3 pt-1">
                    <Button
                      variant="primary"
                      size="sm"
                      className="flex-1"
                      disabled={isProcessingRequest === req.id}
                      onClick={() => handleAcceptRequest(req.id)}
                    >
                      Accept
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="flex-1"
                      disabled={isProcessingRequest === req.id}
                      onClick={() => handleRejectRequest(req.id)}
                    >
                      Reject
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}



      {/* Request Seat Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Request Seat"
      >
        <form onSubmit={handleRequestSeatSubmit} className="space-y-4 pt-2">
          <div className="flex items-center justify-between bg-muted p-4 rounded-2xl border border-border/40">
            <span className="font-bold text-[15px] text-foreground">Number of seats</span>
            <div className="flex items-center space-x-3">
              <button
                type="button"
                onClick={() => setRequestSeats(Math.max(1, requestSeats - 1))}
                className="h-8 w-8 rounded-full bg-card border border-border/60 text-foreground flex items-center justify-center font-bold"
              >
                -
              </button>
              <span className="font-bold text-[16px] text-foreground">{requestSeats}</span>
              <button
                type="button"
                onClick={() => setRequestSeats(Math.min(ride.availableSeats, requestSeats + 1))}
                className="h-8 w-8 rounded-full bg-[#C5FF00] text-black flex items-center justify-center font-bold"
              >
                +
              </button>
            </div>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            className="w-full"
            disabled={isSubmitting}
          >
            {isSubmitting ? "Sending..." : "Send Request"}
          </Button>
        </form>
      </Modal>

      {/* Confirm Start Ride */}
      <ConfirmModal
        isOpen={isConfirmStartModalOpen}
        onClose={() => setIsConfirmStartModalOpen(false)}
        onConfirm={() => {
          setIsConfirmStartModalOpen(false)
          handleStartRide()
        }}
        title="Start Ride?"
        description={passengers.length === 0 ? "No accepted co-riders yet. Start anyway?" : "Mark that everyone has met and the cab trip has begun."}
        confirmText="Start Ride"
        cancelText="Cancel"
        variant="default"
        isLoading={isStartingRide}
      />

      {/* Confirm We've Arrived / Complete Trip */}
      <ConfirmModal
        isOpen={isConfirmCompleteModalOpen}
        onClose={() => setIsConfirmCompleteModalOpen(false)}
        onConfirm={() => {
          setIsConfirmCompleteModalOpen(false)
          handleCompleteRide()
        }}
        title="We've Arrived?"
        description="Mark this trip as completed. Live location tracking will stop for everyone in the pool."
        confirmText="Complete Trip"
        cancelText="Keep Travelling"
        variant="default"
        isLoading={isCompletingRide}
      />

      {/* Confirm Destructive Cancel Modals */}
      <ConfirmModal
        isOpen={isCancelRideModalOpen}
        onClose={() => setIsCancelRideModalOpen(false)}
        onConfirm={handleCancelRideConfirm}
        title="Cancel Ride"
        description="Are you sure you want to cancel this ride? All passengers will be notified."
        confirmText="Cancel Ride"
        cancelText="Keep Ride"
        variant="destructive"
        isLoading={isCancellingRide}
      />

      <ConfirmModal
        isOpen={isCancelRequestModalOpen}
        onClose={() => setIsCancelRequestModalOpen(false)}
        onConfirm={handleCancelRequestConfirm}
        title="Cancel Request"
        description="Are you sure you want to cancel your request for this ride?"
        confirmText="Cancel Request"
        cancelText="Keep Request"
        variant="destructive"
        isLoading={isCancelling}
      />

      <ActiveRideSafetyModal
        isOpen={isSafetyModalOpen}
        onClose={() => setIsSafetyModalOpen(false)}
        currentUserId={user?.uid || ""}
        targetUserId={!isOwner ? ride.ownerId : undefined}
        targetUserName={!isOwner ? ride.hostName : undefined}
        rideId={ride.id}
        rideFrom={ride.from}
        rideTo={ride.to}
        rideDate={ride.date}
        liveLocation={liveTracking.myLocation ? { lat: liveTracking.myLocation.lat, lng: liveTracking.myLocation.lng } : null}
      />

      {/* Gender Verification Required Modal */}
      <Modal
        isOpen={genderErrorState.isOpen}
        onClose={() => setGenderErrorState(prev => ({ ...prev, isOpen: false }))}
        title="Gender Verification Required"
      >
        <div className="space-y-4 pt-1">
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 flex items-start gap-3 text-xs text-amber-900 dark:text-amber-200">
            <MaterialIcon name="shield" className="text-xl text-amber-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-bold text-[13px]">
                {genderErrorState.code === "RIDE_GENDER_POLICY_RESTRICTED"
                  ? `This ride is available only to verified ${ride?.genderPolicy === "female_only" || ride?.genderPolicy === "female" ? "female" : "male"} riders.`
                  : "This ride requires verified gender status."}
              </p>
              <p className="leading-relaxed">
                Your gender has not been verified yet. You cannot request this ride until verification is completed by campus administrators.
              </p>
            </div>
          </div>

          <div className="flex flex-col space-y-2 pt-2">
            <Button
              variant="primary"
              size="default"
              className="w-full font-bold"
              onClick={() => {
                setGenderErrorState(prev => ({ ...prev, isOpen: false }))
                navigate("/verification-status")
              }}
            >
              View Verification Status
            </Button>
            <Button
              variant="outline"
              size="default"
              className="w-full text-xs"
              onClick={() => setGenderErrorState(prev => ({ ...prev, isOpen: false }))}
            >
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* Rejection Cooldown Modal */}
      <Modal
        isOpen={cooldownErrorState.isOpen}
        onClose={() => setCooldownErrorState(prev => ({ ...prev, isOpen: false }))}
        title="Request Unavailable"
      >
        <div className="space-y-4 pt-1">
          <div className="bg-muted border border-border/60 rounded-2xl p-4 flex items-start gap-3 text-xs">
            <MaterialIcon name="history" className="text-xl text-muted-foreground shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-bold text-[13px] text-foreground">Cooldown Active</p>
              <p className="text-muted-foreground leading-relaxed">
                {cooldownErrorState.message || "The host recently declined your previous request for this ride. Please wait before trying again."}
              </p>
            </div>
          </div>

          <Button
            variant="outline"
            size="default"
            className="w-full font-bold text-xs"
            onClick={() => setCooldownErrorState(prev => ({ ...prev, isOpen: false }))}
          >
            Understood
          </Button>
        </div>
      </Modal>

      {/* Student Profile Card Modal */}
      <Modal
        isOpen={!!profileModal}
        onClose={() => setProfileModal(null)}
        title={profileModal ? (profileModal.role === "host" ? "Host Profile" : "Passenger Profile") : ""}
      >
        {profileModal && (
          <div className="space-y-5 pt-2">
            {/* Header: Avatar, Name, Role & Verification */}
            <div className="flex flex-col items-center text-center space-y-2">
              <div className="h-20 w-20 rounded-full bg-muted flex items-center justify-center font-bold text-[28px] text-foreground border-2 border-border/60 shadow-xs uppercase">
                {profileModal.name.charAt(0)}
              </div>
              <div>
                <h3 className="text-[20px] font-extrabold text-foreground leading-tight">
                  {profileModal.name}
                </h3>
                <div className="flex items-center justify-center space-x-2 mt-1.5">
                  <span className="text-[12px] font-bold px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/40">
                    {profileModal.role === "host" ? (profileModal.isSelf ? "Host (You)" : "Host") : (profileModal.isSelf ? "Passenger (You)" : "Passenger")}
                  </span>
                  {profileModal.verified && (
                    <span className="inline-flex items-center px-1.5 py-[2px] rounded-full text-[10px] font-semibold leading-none bg-[#25D366]/15 text-emerald-600 dark:text-[#25D366] border border-[#25D366]/30">
                      Verified
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Academic Info Box */}
            <div className="bg-muted/50 border border-border/60 rounded-2xl p-4 space-y-2.5">
              <div className="flex items-center space-x-3 text-[14px]">
                <MaterialIcon name="school" className="text-[18px] text-muted-foreground shrink-0" />
                <span className="font-medium text-foreground">{profileModal.college || "College of Engineering Trivandrum (CET)"}</span>
              </div>
              <div className="flex items-center space-x-3 text-[14px]">
                <MaterialIcon name="badge" className="text-[18px] text-muted-foreground shrink-0" />
                <span className="text-muted-foreground">
                  {profileModal.department ? `${profileModal.department}${profileModal.year ? ` • ${profileModal.year}` : ""}` : profileModal.year || "Student"}
                </span>
              </div>
            </div>

            {/* Contact Actions (Call & WhatsApp) */}
            {!profileModal.isSelf ? (
              profileModal.relationshipStatus === "completed" ? (
                <div className="p-4 bg-muted/30 rounded-2xl border border-border/40 text-center space-y-1.5">
                  <div className="flex items-center justify-center space-x-1.5 text-zinc-400 font-bold text-[13px]">
                    <MaterialIcon name="lock" className="text-[18px] text-zinc-400" />
                    <span>Contact Details Closed</span>
                  </div>
                  <p className="text-[12px] text-muted-foreground leading-relaxed">
                    This ride has ended. Contact details are no longer accessible to protect user privacy.
                  </p>
                </div>
              ) : profileModal.relationshipStatus === "accepted" ? (
                profileModal.phone ? (
                  <div className="space-y-2 pt-2">
                    <div className="grid grid-cols-2 gap-3">
                      <a
                        href={`tel:${profileModal.phone}`}
                        className="h-12 bg-muted hover:bg-muted/80 text-foreground rounded-[18px] font-bold text-[14px] flex items-center justify-center space-x-2 border border-border/40 cursor-pointer transition-transform active:scale-95 shadow-xs"
                      >
                        <MaterialIcon name="call" className="text-[20px]" />
                        <span>Call</span>
                      </a>
                      <a
                        href={`https://wa.me/${normalizePhoneForWhatsApp(profileModal.phone)}`}
                        target="_blank"
                        rel="noreferrer"
                        className="h-12 bg-[#25D366] text-white rounded-[18px] font-bold text-[14px] flex items-center justify-center space-x-2 hover:opacity-90 cursor-pointer transition-transform active:scale-95 shadow-xs"
                      >
                        <MaterialIcon name="chat" className="text-[20px]" />
                        <span>WhatsApp</span>
                      </a>
                    </div>
                    <p className="text-[11px] text-center text-muted-foreground pt-1">
                      Direct contact shared for ride coordination.
                    </p>
                  </div>
                ) : (
                  <div className="p-3.5 bg-muted/40 rounded-2xl border border-border/30 text-center text-muted-foreground text-[13px]">
                    <span>No contact number on file for this user</span>
                  </div>
                )
              ) : profileModal.relationshipStatus === "pending" ? (
                <div className="p-4 bg-amber-500/10 rounded-2xl border border-amber-500/20 text-center space-y-1">
                  <div className="flex items-center justify-center space-x-1.5 text-amber-600 dark:text-amber-400 font-bold text-[13px]">
                    <MaterialIcon name="schedule" className="text-[18px]" />
                    <span>Request Pending</span>
                  </div>
                  <p className="text-[12px] text-muted-foreground">
                    Direct Call & WhatsApp will unlock here as soon as the host accepts your request.
                  </p>
                </div>
              ) : (
                <div className="p-4 bg-muted/30 rounded-2xl border border-border/40 text-center space-y-1.5">
                  <div className="flex items-center justify-center space-x-1.5 text-foreground font-bold text-[13px]">
                    <MaterialIcon name="lock" className="text-[18px] text-primary dark:text-[#C5FF00]" />
                    <span>Contact Protected</span>
                  </div>
                  <p className="text-[12px] text-muted-foreground leading-relaxed">
                    Click <strong>Request to Join</strong> below. Direct Call & WhatsApp buttons will unlock automatically once your request is accepted!
                  </p>
                </div>
              )
            ) : (
              <div className="p-3.5 bg-muted/40 rounded-2xl border border-border/30 text-center text-muted-foreground text-[13px]">
                <span className="font-semibold text-foreground">This is your profile</span>
                {profileModal.phone ? (
                  <p className="text-[11px] text-muted-foreground mt-0.5">Phone: {profileModal.phone}</p>
                ) : (
                  <p className="text-[11px] text-amber-500 mt-0.5">No phone number saved. Add it in Account Settings.</p>
                )}
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Dev-only Live GPS Movement Simulator Widget */}
      {isTrackingEligible && liveTracking && (
        <LiveTrackingSimControl
          rideId={rideId || ""}
          currentUserId={user?.uid}
          currentUserName={user?.displayName || (isOwner ? ride.hostName : "Co-rider")}
          role={isOwner ? "creator" : "co-rider"}
          myLocation={liveTracking.myLocation}
          peerLocation={liveTracking.peerLocation}
          destinationCoords={ride.toLocation ? { lat: ride.toLocation.latitude, lng: ride.toLocation.longitude } : undefined}
          onSimulateLocation={liveTracking.simulateLocationUpdate}
          onSimulateCoRiderLocation={liveTracking.simulateCoRiderLocation}
        />
      )}
    </MobileShell>
  )
}
