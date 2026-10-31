import { useState, useEffect } from "react"
import { Check, X, User, ShieldCheck, MapPin, Calendar, Users, UserPlus, ChevronRight, Minus, Plus, SendHorizontal } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { doc, onSnapshot, collection, query, where, getDocs } from "firebase/firestore"
import { db } from "../../config/firebase"
import { notificationService, type AppNotification } from "../../services/notification/notificationService"
import { rideRequestService } from "../../services/rideRequest/rideRequestService"
import { rideService } from "../../services/ride/rideService"
import { userService } from "../../services/user/userService"
import { useAuth } from "../../hooks/useAuth"
import { useRideRequestStatus } from "../../hooks/useRideRequestStatus"
import { useToast } from "../feedback/ToastContext"
import { Button } from "../ui/button"
import { formatBranchYear } from "../../utils/formatters"

interface NotificationPopupProps {
  notification: AppNotification
  onDismiss: () => void
  onCloseOnly?: () => void
}

export function NotificationPopup({ notification, onDismiss, onCloseOnly }: NotificationPopupProps) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { showToast } = useToast()
  const [isProcessing, setIsProcessing] = useState(false)
  const [resolvedActor, setResolvedActor] = useState(notification.actorSnapshot)
  const [requestSeats, setRequestSeats] = useState(1)

  useEffect(() => {
    let isMounted = true
    if (!notification.actorSnapshot && notification.actorId) {
      userService.getUserProfile(notification.actorId).then(p => {
        if (p && isMounted) {
          setResolvedActor({
            name: p.name || "Host",
            college: p.college || "",
            department: p.department || "",
            verified: !!p.collegeVerified
          })
        }
      }).catch(() => {})
    } else {
      setResolvedActor(notification.actorSnapshot)
    }
    return () => { isMounted = false }
  }, [notification])

  const candidateRideIds = [notification.matchedRideId, notification.rideId].filter(Boolean) as string[]
  const { status: liveRequestStatus, loading: requestStatusLoading } = useRideRequestStatus(candidateRideIds, notification.actorId)
  const [directRequestStatus, setDirectRequestStatus] = useState<string | null>(null)

  // Direct authoritative Firestore check on mount / notification change
  useEffect(() => {
    if (!user || candidateRideIds.length === 0) return
    let isSubscribed = true

    const qReq = query(
      collection(db, "rideRequests"),
      where("requesterId", "==", user.uid),
      where("rideId", "in", candidateRideIds.slice(0, 10))
    )

    getDocs(qReq).then(snap => {
      if (!isSubscribed) return
      const activeReq = snap.docs.map(d => d.data()).find(r => r.status === "pending" || r.status === "accepted")
      if (activeReq) {
        setDirectRequestStatus(activeReq.status)
        // If already requested, auto-dismiss match modal and mark notification read
        if (notification.type === "ride_match_found") {
          if (notification.id) {
            notificationService.markNotificationAsRead(notification.id).catch(() => {})
          }
          onDismiss()
        }
      }
    }).catch(err => {
      console.warn("Direct request status check error:", err)
    })

    return () => { isSubscribed = false }
  }, [user, notification.id, notification.type, onDismiss, candidateRideIds.join(",")])

  const matchRequestStatus = directRequestStatus || liveRequestStatus

  // B1: Listen to single request document and close modal when request is no longer pending
  useEffect(() => {
    if (notification.type !== "ride_request" || !notification.rideRequestId) return
    const unsub = onSnapshot(
      doc(db, "rideRequests", notification.rideRequestId),
      (snap) => {
        if (!snap.exists() || snap.data().status !== "pending") {
          onDismiss()
        }
      },
      (err) => {
        console.error("Error listening to ride request status:", err)
      }
    )
    return () => unsub()
  }, [notification.type, notification.rideRequestId, onDismiss])

  const handleCloseOnly = () => {
    if (onCloseOnly) {
      onCloseOnly()
    } else {
      onDismiss()
    }
  }

  const handleAccept = async () => {
    if (isProcessing) return
    if (!notification.rideRequestId || !user) return
    if (notification.type === "ride_request" && matchRequestStatus !== "pending" && matchRequestStatus !== "none") {
      showToast("Request is no longer pending.", "info")
      onDismiss()
      return
    }
    setIsProcessing(true)
    try {
      const result = await rideRequestService.acceptRideRequest(notification.rideRequestId, user.uid)
      if (result.success) {
        showToast("Request accepted", "success")
        onDismiss()
        const targetRideId = notification.rideId || notification.matchedRideId
        if (targetRideId) {
          const targetPath = `/rides/${targetRideId}`
          if (typeof window === "undefined" || window.location.pathname !== targetPath) {
            navigate(targetPath)
          }
        }
      } else {
        showToast(result.message || "Request is no longer pending.", "error")
        onDismiss()
      }
    } catch (err: any) {
      showToast(err?.message || "Failed to accept request.", "error")
      onDismiss()
    } finally {
      setIsProcessing(false)
    }
  }

  const handleReject = async () => {
    if (isProcessing) return
    if (!notification.rideRequestId || !user) return
    setIsProcessing(true)
    try {
      const result = await rideRequestService.rejectRideRequest(notification.rideRequestId, user.uid)
      if (result.success) {
        showToast("Request rejected", "success")
      } else {
        showToast(result.message || "Request is no longer pending.", "error")
      }
      onDismiss()
    } catch (err: any) {
      showToast(err?.message || "Failed to reject request.", "error")
      onDismiss()
    } finally {
      setIsProcessing(false)
    }
  }

  const handleViewRide = () => {
    onDismiss()
    const target = notification.matchedRideId || notification.rideId
    if (target) {
      const targetPath = `/rides/${target}`
      if (typeof window === "undefined" || window.location.pathname !== targetPath) {
        navigate(targetPath)
      }
    }
  }

  const handleDirectSendRequest = async () => {
    if (!user) return
    setIsProcessing(true)

    try {
      let targetId = notification.matchedRideId
      let targetOwnerId = notification.actorId
      let rideData: any = null

      // 1. Try fetching the ride doc directly using matchedRideId
      if (targetId) {
        rideData = await rideService.getRideById(targetId)
      }

      // 2. If rideData belongs to current user or wasn't found, query candidate host's active rides
      if ((!rideData || rideData.ownerId === user.uid) && targetOwnerId) {
        const actorRides = await rideService.getMyRides(targetOwnerId)
        const activeRide = actorRides.find(r => r.status === "active" || (r.status as string) === "available")
        if (activeRide) {
          rideData = activeRide
          targetId = activeRide.id
        }
      }

      // 3. Fallback: if getRideById was null but rideSnapshot and actorId exist
      if (!rideData && notification.rideSnapshot && targetOwnerId) {
        targetId = notification.matchedRideId || notification.rideId
        rideData = {
          id: targetId,
          ownerId: targetOwnerId,
          from: notification.rideSnapshot.from,
          to: notification.rideSnapshot.to,
          date: notification.rideSnapshot.date,
          departureTime: notification.rideSnapshot.time,
          availableSeats: notification.rideSnapshot.seats || 1,
          totalSeats: notification.rideSnapshot.seats || 1,
          status: "active"
        }
      }

      if (!rideData || !rideData.id) {
        showToast("Ride is no longer available.", "error")
        setIsProcessing(false)
        return
      }

      const result = await rideRequestService.createRideRequest(
        {
          id: rideData.id,
          ownerId: rideData.ownerId,
          status: rideData.status === "available" ? "active" : (rideData.status || "active"),
          availableSeats: rideData.availableSeats ?? 1,
          from: rideData.from || notification.rideSnapshot?.from || "",
          to: rideData.to || notification.rideSnapshot?.to || "",
          date: rideData.date || notification.rideSnapshot?.date || "",
          departureTime: rideData.departureTime || notification.rideSnapshot?.time || "",
          genderPolicy: rideData.genderPolicy
        },
        user.uid,
        requestSeats
      )

      if (!result.success) {
        showToast(result.message, "error")
        setIsProcessing(false)
        return
      }

      // If current user created a duplicate draft/host ride for this match offer, cancel the ghost ride
      if (notification.rideId && notification.rideId !== rideData.id) {
        rideService.cancelRide(notification.rideId, user.uid).catch(console.error)
      }

      if (notification.id) {
        await notificationService.markNotificationAsRead(notification.id).catch(() => {})
      }

      showToast("Request sent! Waiting for host.", "success")
      if (rideData && rideData.id) {
        navigate(`/rides/${rideData.id}`)
      }
      onDismiss()
    } catch (error: any) {
      console.error("Failed to send ride request from match popup:", error)
      showToast(error?.message || "Failed to send request. Please try again.", "error")
    } finally {
      setIsProcessing(false)
    }
  }

  const { type, rideSnapshot } = notification
  const actorSnapshot = resolvedActor || notification.actorSnapshot
  const validTypes = ["ride_request", "request_accepted", "request_rejected", "ride_cancelled", "ride_match_found"]
  if (!type || !validTypes.includes(type)) {
    return null
  }

  const isMatchFoundPopup = type === "ride_match_found"

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-md px-4 pt-[calc(1rem+env(safe-area-inset-top,0px))] pb-[calc(1rem+env(safe-area-inset-bottom,0px))] overflow-y-auto">
      <div className={`w-full ${isMatchFoundPopup ? "max-w-[410px] bg-card text-foreground border border-border rounded-[32px] p-5 sm:p-6" : "max-w-sm bg-card rounded-[28px] p-6 border border-border"} shadow-[0_20px_50px_rgba(0,0,0,0.18)] animate-in zoom-in-95 duration-200 relative max-h-[calc(100dvh-env(safe-area-inset-top,0px)-env(safe-area-inset-bottom,0px)-2rem)] overflow-y-auto`}>

        {/* Top Close X Button */}
        <button
          onClick={handleCloseOnly}
          className="absolute top-4 right-4 h-8 w-8 rounded-full bg-muted/60 text-muted-foreground hover:text-foreground hover:bg-muted flex items-center justify-center transition-colors z-20"
          aria-label="Close"
        >
          <X className="h-4 w-4 stroke-[2.5]" />
        </button>

        {/* NEW RIDE REQUEST (Host's View) */}
        {type === "ride_request" && (
          <div className="space-y-5">
            <h3 className="text-[20px] font-bold text-center text-foreground">New ride request</h3>

            {actorSnapshot && (
              <div className="flex items-center space-x-3 bg-muted/50 dark:bg-zinc-800/60 border border-border/50 p-3.5 rounded-[18px]">
                <div className="h-12 w-12 rounded-full bg-foreground text-background flex items-center justify-center font-bold text-[18px] shrink-0 shadow-xs">
                  {actorSnapshot.name ? actorSnapshot.name.trim().charAt(0).toUpperCase() : <User className="h-6 w-6 text-background" />}
                </div>
                <div>
                  <div className="font-bold text-[16px] text-foreground">{actorSnapshot.name}</div>
                  <div className="text-[13px] text-muted-foreground">
                    {formatBranchYear(actorSnapshot.department, actorSnapshot.year, actorSnapshot.college || "CET")}
                  </div>
                  <div className="text-[12px] text-foreground/80 font-medium flex items-center space-x-1 mt-0.5">
                    <Users className="w-3.5 h-3.5 text-muted-foreground" />
                    <span>{rideSnapshot?.seats || 1} seat{(rideSnapshot?.seats || 1) > 1 ? "s" : ""} requested</span>
                  </div>
                </div>
              </div>
            )}

            {rideSnapshot && (
              <div className="bg-card border border-border/60 rounded-[18px] p-4 space-y-3">
                <div className="relative pl-7 py-0.5 space-y-3.5">
                  {/* Vertical Dashed Line connecting Blue and Green dots */}
                  <div className="absolute left-[10px] top-[14px] bottom-[14px] w-[2px] border-l-2 border-dashed border-foreground/40 dark:border-white/50 pointer-events-none" />

                  {/* Origin Row */}
                  <div className="relative flex items-center justify-between text-left">
                    <div className="absolute -left-[24px] top-1/2 -translate-y-1/2 w-[14px] h-[14px] rounded-full bg-[#3B82F6] ring-4 ring-background shrink-0 z-10" />
                    <span className="font-bold text-[15px] text-foreground leading-snug">
                      {rideSnapshot.from}
                    </span>
                  </div>

                  {/* Destination Row */}
                  <div className="relative flex items-center justify-between text-left">
                    <div className="absolute -left-[24px] top-1/2 -translate-y-1/2 w-[14px] h-[14px] rounded-full bg-[#25D366] ring-4 ring-background shrink-0 z-10" />
                    <span className="font-bold text-[15px] text-foreground leading-snug">
                      {rideSnapshot.to}
                    </span>
                  </div>
                </div>

                {/* Date & Time Badges Row */}
                {(rideSnapshot.date || rideSnapshot.time) && (
                  <div className="pt-2 border-t border-border/40 flex items-center gap-2 text-[12px] text-muted-foreground font-medium">
                    {rideSnapshot.date && (
                      <div className="flex items-center space-x-1.5 bg-muted/60 dark:bg-zinc-800/60 px-2.5 py-1 rounded-md">
                        <Calendar className="w-3.5 h-3.5 text-foreground/70" />
                        <span>{rideSnapshot.date}</span>
                      </div>
                    )}
                    {rideSnapshot.time && (
                      <div className="flex items-center space-x-1.5 bg-muted/60 dark:bg-zinc-800/60 px-2.5 py-1 rounded-md">
                        <span>{rideSnapshot.time}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-3 pt-1">
              <Button
                variant="outline"
                className="flex-1 h-[50px] bg-transparent border-2 border-border text-foreground hover:bg-muted font-bold text-[16px] rounded-[980px] transition-all"
                onClick={handleReject}
                disabled={isProcessing}
              >
                Reject
              </Button>
              <Button
                className="flex-1 h-[50px] bg-[#C5FF00] hover:bg-[#b0e600] text-black font-extrabold text-[17px] rounded-[980px] shadow-sm active:scale-[0.98] transition-all cursor-pointer"
                onClick={handleAccept}
                disabled={isProcessing}
              >
                Accept
              </Button>
            </div>
          </div>
        )}

        {/* REQUEST ACCEPTED (Passenger's View) */}
        {type === "request_accepted" && (
          <div className="space-y-6 text-center">
            <div className="mx-auto h-16 w-16 bg-[#C5FF00] rounded-full flex items-center justify-center shadow-sm">
              <Check className="h-8 w-8 text-black" strokeWidth={3} />
            </div>
            <h3 className="text-[20px] font-bold text-foreground">Ride request accepted</h3>

            {actorSnapshot && (
              <div className="flex items-center justify-center space-x-3 bg-muted/50 dark:bg-zinc-800/60 border border-border/50 p-3.5 rounded-[18px]">
                <div className="h-10 w-10 rounded-full bg-foreground text-background flex items-center justify-center font-bold text-[15px] shrink-0 shadow-xs">
                  {actorSnapshot.name ? actorSnapshot.name.trim().charAt(0).toUpperCase() : <User className="h-5 w-5 text-background" />}
                </div>
                <div className="text-left">
                  <div className="font-bold text-[15px] text-foreground">{actorSnapshot.name}</div>
                  <div className="text-[12px] text-muted-foreground">
                    {formatBranchYear(actorSnapshot.department, actorSnapshot.year, actorSnapshot.college || "CET")}
                  </div>
                  {actorSnapshot.verified && (
                    <div className="flex items-center space-x-1 text-[12px] text-foreground font-medium mt-0.5">
                      <ShieldCheck className="h-3.5 w-3.5 text-foreground" />
                      <span>Verified Student</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {rideSnapshot && (
              <div className="text-[14px] font-bold space-y-1 text-foreground">
                <p>{rideSnapshot.from} → {rideSnapshot.to}</p>
                <p className="text-muted-foreground font-medium">{rideSnapshot.date} • {rideSnapshot.time}</p>
              </div>
            )}

            <Button
              className="w-full h-[50px] bg-[#C5FF00] text-black hover:bg-[#b0e600] font-extrabold text-[17px] rounded-[980px] shadow-sm"
              onClick={handleViewRide}
            >
              View Ride
            </Button>
          </div>
        )}

        {/* REQUEST REJECTED (Passenger's View) */}
        {type === "request_rejected" && (
          <div className="space-y-6 text-center">
            <div className="mx-auto h-16 w-16 bg-destructive/10 rounded-full flex items-center justify-center shadow-sm">
              <X className="h-8 w-8 text-destructive" strokeWidth={3} />
            </div>
            <h3 className="text-[20px] font-bold">Ride request declined</h3>

            <p className="text-[14px] text-muted-foreground">
              {actorSnapshot?.name || "The host"} could not accept your request.
            </p>

            <Button
              className="w-full h-[50px] bg-secondary text-foreground"
              onClick={onDismiss}
            >
              Got it
            </Button>
          </div>
        )}

        {/* RIDE CANCELLED */}
        {type === "ride_cancelled" && (
          <div className="space-y-6 text-center">
            <div className="mx-auto h-16 w-16 bg-destructive/10 rounded-full flex items-center justify-center shadow-sm">
              <X className="h-8 w-8 text-destructive" strokeWidth={3} />
            </div>
            <h3 className="text-[20px] font-bold">Ride cancelled</h3>
            <p className="text-[14px] text-muted-foreground">{notification.message}</p>
            <Button className="w-full h-[50px] bg-secondary text-foreground" onClick={onDismiss}>Got it</Button>
          </div>
        )}

        {/* RIDE MATCH FOUND (Automatic Ride Pool Popup) */}
        {type === "ride_match_found" && (
          <div className="space-y-3.5 text-center pt-1">
            {/* Header Icon & Title */}
            <div className="flex flex-col items-center justify-center text-center space-y-2 pt-1 pb-0.5">
              <div className="w-11 h-11 rounded-full bg-[#C5FF00] text-black flex items-center justify-center shadow-xs">
                <Users className="w-5 h-5 stroke-[2.5]" />
              </div>
              <h3 className="text-[20px] sm:text-[22px] font-extrabold text-foreground tracking-tight leading-tight">
                Compatible ride found
              </h3>
            </div>

            {/* Host / Actor Info Card */}
            {actorSnapshot && (
              <div
                onClick={handleViewRide}
                className="flex items-center justify-between bg-muted/40 hover:bg-muted/70 border border-border/70 p-3 sm:p-3.5 rounded-[20px] text-left cursor-pointer transition-colors"
              >
                <div className="flex items-center space-x-3 min-w-0">
                  <div className="h-11 w-11 sm:h-12 sm:w-12 rounded-full bg-foreground text-background flex items-center justify-center font-extrabold text-lg shrink-0 shadow-xs">
                    {actorSnapshot.name ? actorSnapshot.name.trim().charAt(0).toUpperCase() : <User className="h-5 w-5 text-background" />}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center space-x-1.5">
                      <span className="font-extrabold text-[15px] sm:text-[16px] text-foreground truncate">
                        {actorSnapshot.name}
                      </span>
                      {actorSnapshot.verified && (
                        <span className="inline-flex items-center justify-center w-4 h-4 bg-[#C5FF00] rounded-full shrink-0 ml-0.5" title="Verified Student">
                          <Check className="w-2.5 h-2.5 text-black stroke-[3.5]" />
                        </span>
                      )}
                    </div>
                    <span className="text-[12px] text-muted-foreground font-medium block truncate mt-0.5">
                      {formatBranchYear(actorSnapshot.department, actorSnapshot.year, actorSnapshot.college || "CET")}
                    </span>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-muted-foreground shrink-0 ml-2" />
              </div>
            )}

            {/* Route & Details Card */}
            {rideSnapshot && (
              <div className="bg-card dark:bg-muted/20 rounded-[20px] p-3.5 sm:p-4 border border-border/70 text-left space-y-3">
                {/* Route Summary Row: Side-by-side with Arrow */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center space-x-2 min-w-0 flex-1">
                    <div className="w-7 h-7 rounded-full bg-blue-500/10 flex items-center justify-center shrink-0">
                      <MapPin className="w-3.5 h-3.5 text-[#3B82F6]" fill="#3B82F6" />
                    </div>
                    <span className="font-extrabold text-[14px] sm:text-[15px] text-foreground truncate">
                      {rideSnapshot.from}
                    </span>
                  </div>

                  <span className="text-muted-foreground font-bold text-base shrink-0 px-1">→</span>

                  <div className="flex items-center space-x-2 min-w-0 flex-1 justify-end">
                    <div className="w-7 h-7 rounded-full bg-emerald-500/10 flex items-center justify-center shrink-0">
                      <MapPin className="w-3.5 h-3.5 text-[#25D366]" fill="#25D366" />
                    </div>
                    <span className="font-extrabold text-[14px] sm:text-[15px] text-foreground truncate text-right">
                      {rideSnapshot.to}
                    </span>
                  </div>
                </div>

                {/* Divider Line */}
                <div className="border-t border-border/50" />

                {/* Bottom Row: 2 Columns (Date/Time & Seats Left) */}
                <div className="grid grid-cols-2 divide-x divide-border/50 pt-0.5">
                  {/* Column 1: Date & Time */}
                  <div className="flex items-center space-x-2 pr-2">
                    <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0">
                      <Calendar className="w-3.5 h-3.5 text-foreground/80" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-extrabold text-[12px] sm:text-[13px] text-foreground leading-tight truncate">
                        {rideSnapshot.date}
                      </div>
                      <div className="text-[11px] text-muted-foreground font-normal mt-0.5 truncate">
                        {rideSnapshot.time}
                      </div>
                    </div>
                  </div>

                  {/* Column 2: Seats Left */}
                  <div className="flex items-center space-x-2 pl-3">
                    <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0">
                      <Users className="w-3.5 h-3.5 text-foreground/80" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-extrabold text-[12px] sm:text-[13px] text-foreground leading-tight truncate">
                        {rideSnapshot.seats ?? 1} {(rideSnapshot.seats ?? 1) === 1 ? "seat" : "seats"} left
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Seats Required Stepper */}
            <div className="flex items-center justify-between bg-card dark:bg-muted/20 rounded-[20px] p-3 sm:p-3.5 border border-border/70 text-left">
              <span className="font-extrabold text-[14px] text-foreground">Seats required</span>
              <div className="flex items-center space-x-3">
                <button
                  type="button"
                  onClick={() => setRequestSeats(prev => Math.max(1, prev - 1))}
                  disabled={requestSeats <= 1 || isProcessing}
                  className="w-8 h-8 rounded-full bg-muted hover:bg-muted/80 disabled:opacity-40 flex items-center justify-center font-extrabold text-base text-foreground transition-colors cursor-pointer"
                  aria-label="Decrease seats"
                >
                  <Minus className="w-4 h-4 stroke-[3]" />
                </button>
                <span className="font-extrabold text-[16px] text-foreground min-w-[16px] text-center">
                  {requestSeats}
                </span>
                <button
                  type="button"
                  onClick={() => setRequestSeats(prev => Math.min(rideSnapshot?.seats || 4, prev + 1))}
                  disabled={requestSeats >= (rideSnapshot?.seats || 4) || isProcessing}
                  className="w-8 h-8 rounded-full bg-muted hover:bg-muted/80 disabled:opacity-40 flex items-center justify-center font-extrabold text-base text-foreground transition-colors cursor-pointer"
                  aria-label="Increase seats"
                >
                  <Plus className="w-4 h-4 stroke-[3]" />
                </button>
              </div>
            </div>

            {/* Bottom Action Button */}
            <div className="pt-1">
              {matchRequestStatus === "pending" || matchRequestStatus === "accepted" ? (
                <Button
                  className="w-full h-[48px] sm:h-[50px] rounded-[980px] font-extrabold bg-[#C5FF00] text-black hover:bg-[#b0e600] active:scale-[0.98] text-xs sm:text-sm shadow-sm border-0 flex items-center justify-center gap-2 cursor-pointer transition-all"
                  onClick={handleViewRide}
                  disabled={isProcessing}
                >
                  <UserPlus className="w-4.5 h-4.5 text-black" />
                  <span>
                    {matchRequestStatus === "accepted" ? "View Ride" : "View Request"}
                  </span>
                </Button>
              ) : (
                <Button
                  className="w-full h-[48px] sm:h-[50px] rounded-[980px] font-extrabold bg-[#C5FF00] text-black hover:bg-[#b0e600] active:scale-[0.98] text-xs sm:text-sm shadow-sm border-0 flex items-center justify-center gap-2 cursor-pointer transition-all"
                  onClick={handleDirectSendRequest}
                  disabled={isProcessing || requestStatusLoading}
                >
                  <SendHorizontal className="w-4.5 h-4.5 text-black stroke-[2.5]" />
                  <span>{isProcessing ? "Sending..." : requestStatusLoading ? "Checking..." : "Send Request"}</span>
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
