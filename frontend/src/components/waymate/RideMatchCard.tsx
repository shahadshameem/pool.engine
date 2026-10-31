import { useState } from "react"
import { Clock, Users, Calendar, CheckCircle2 } from "lucide-react"
import type { RideMatchCandidate } from "../../services/rideMatch/rideMatchService"
import { formatDate, formatTime12h, formatBranchYear } from "../../utils/formatters"
import { useRideRequestStatus } from "../../hooks/useRideRequestStatus"
import { useAuth } from "../../hooks/useAuth"
import { useToast } from "../feedback/ToastContext"
import { rideRequestService } from "../../services/rideRequest/rideRequestService"

interface RideMatchCardProps {
  candidate: RideMatchCandidate
  onJoinClick?: (candidate: RideMatchCandidate) => void
  onViewClick: (rideId: string) => void
}

export function RideMatchCard({ candidate, onJoinClick, onViewClick }: RideMatchCardProps) {
  const { ride, hostProfile } = candidate
  const { status: requestStatus } = useRideRequestStatus(ride.id, ride.ownerId)
  const { user } = useAuth()
  const { showToast } = useToast()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleQuickRequest = async () => {
    if (!user || !ride.id) return
    setIsSubmitting(true)
    try {
      const result = await rideRequestService.createRideRequest(
        {
          id: ride.id,
          ownerId: ride.ownerId,
          status: ride.status || "active",
          availableSeats: ride.availableSeats || 1,
          from: ride.from,
          to: ride.to,
          date: ride.date,
          departureTime: ride.departureTime,
          genderPolicy: ride.genderPolicy
        },
        user.uid,
        1
      )
      if (result.success) {
        showToast("Seat request sent to host!", "success")
      } else {
        showToast(result.message, "error")
      }
    } catch (err: any) {
      showToast(err?.message || "Failed to send request.", "error")
    } finally {
      setIsSubmitting(false)
    }
  }

  const initial = hostProfile?.name ? hostProfile.name.trim().charAt(0).toUpperCase() : "U"
  const formattedTime = formatTime12h(ride.departureTime)
  const formattedDate = formatDate(ride.date)

  return (
    <div className="rounded-[24px] border border-border/60 bg-card p-4 space-y-3.5 shadow-xs">
      {/* Top Row: Avatar, Host Name & Subtitle, Time Pill */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          {/* Avatar Circle */}
          <div className="h-12 w-12 rounded-full bg-muted border border-border/40 text-foreground text-[17px] font-bold flex items-center justify-center uppercase shrink-0">
            {initial}
          </div>
          <div>
            <span className="font-bold text-[17px] text-foreground leading-tight block">
              {hostProfile?.name?.toLowerCase() || "usman"}
            </span>
            <span className="text-[13px] font-normal text-muted-foreground leading-tight block mt-0.5">
              {formatBranchYear(hostProfile?.department, hostProfile?.year, hostProfile?.college || "CET")}
            </span>
          </div>
        </div>

        {/* Time Pill */}
        <span className="px-3.5 py-1.5 rounded-full bg-muted border border-border/40 text-foreground font-medium text-[13px] flex items-center space-x-1.5 shrink-0">
          <Clock className="h-4 w-4 text-foreground" />
          <span>{formattedTime}</span>
        </span>
      </div>

      {/* Inner Route Card Box */}
      <div className="bg-muted/60 rounded-[20px] p-4 border border-border/40 space-y-3">
        {/* Route Details */}
        <div className="flex items-stretch space-x-3 py-0.5">
          <div className="relative flex flex-col items-center shrink-0 w-3.5 my-1">
            <div className="w-3.5 h-3.5 rounded-full bg-[#3B82F6] ring-2 ring-[#3B82F6]/30 shrink-0 z-10" />
            <div className="w-[2px] flex-1 border-l-2 border-dashed border-foreground/30 dark:border-white/40 my-1" />
            <div className="w-3.5 h-3.5 rounded-full bg-[#25D366] ring-2 ring-[#25D366]/30 shrink-0 z-10" />
          </div>

          <div className="flex flex-col justify-between space-y-3 min-w-0 flex-1">
            <span className="font-bold text-[16px] text-foreground leading-tight truncate">
              {ride.from}
            </span>
            <span className="font-bold text-[16px] text-foreground leading-tight truncate">
              {ride.to}
            </span>
          </div>
        </div>

        {/* Divider Line */}
        <div className="border-t border-border/40 pt-3">
          {/* Metadata Row */}
          <div className="flex items-center text-[13px] font-medium text-muted-foreground">
            <div className="flex items-center space-x-1.5">
              <Calendar className="h-4.5 w-4.5 text-muted-foreground shrink-0" />
              <span>{formattedDate}</span>
            </div>

            <div className="h-4 w-[1px] bg-border/60 mx-3.5" />

            <div className="flex items-center space-x-1.5">
              <Users className="h-4.5 w-4.5 text-muted-foreground shrink-0" />
              <span>{ride.availableSeats} {ride.availableSeats === 1 ? "seat left" : "seats left"}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Action Buttons Row */}
      <div className="flex space-x-3 pt-1">
        {/* Outlined View Details */}
        <button
          type="button"
          onClick={() => ride.id && onViewClick(ride.id)}
          className="flex-1 h-12 rounded-[18px] bg-card border border-border/60 text-foreground font-bold text-[15px] hover:bg-muted active:scale-[0.98] transition-all cursor-pointer flex items-center justify-center shadow-2xs"
        >
          View Details
        </button>

        {requestStatus === "accepted" ? (
          <div className="flex-1 h-12 rounded-[18px] bg-emerald-600 text-white font-bold text-[15px] flex items-center justify-center space-x-2 shadow-xs">
            <CheckCircle2 className="h-5 w-5 text-white stroke-[2.2]" />
            <span>Joined</span>
          </div>
        ) : requestStatus === "pending" ? (
          <div className="flex-1 h-12 rounded-[18px] bg-muted text-foreground border border-border/60 font-bold text-[15px] flex items-center justify-center space-x-2">
            <Clock className="h-4.5 w-4.5 text-foreground" />
            <span>Request Sent</span>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => onJoinClick ? onJoinClick(candidate) : handleQuickRequest()}
            disabled={isSubmitting}
            className="flex-1 h-12 rounded-[18px] bg-[#C5FF00] text-black font-extrabold text-[15px] flex items-center justify-center hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 shadow-xs"
          >
            {isSubmitting ? "Sending..." : "Send Request"}
          </button>
        )}
      </div>
    </div>
  )
}
