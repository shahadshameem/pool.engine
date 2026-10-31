import { useRideRequestStatus } from "../../hooks/useRideRequestStatus"
import { useAuth } from "../../hooks/useAuth"
import { formatTime12h, formatBranchYear } from "../../utils/formatters"

export interface HomeRideCardData {
  id: string
  ownerId: string
  from: string
  to: string
  date: string
  departureTime: string
  availableSeats: number
  totalSeats?: number
  hostName?: string
  college?: string
  department?: string
  year?: string
  hostVerified?: boolean
  meetingPoint?: string
  status?: string
}

interface HomeRideCardProps {
  ride: HomeRideCardData
  onRequest: (ride: HomeRideCardData) => void
  onCardClick?: (ride: HomeRideCardData) => void
}

export function HomeRideCard({ ride, onRequest, onCardClick }: HomeRideCardProps) {
  const { user } = useAuth()
  const { status: reqStatus, loading: statusLoading } = useRideRequestStatus(ride.id, ride.ownerId)

  const isHost = user?.uid === ride.ownerId
  const initial = (ride.hostName || "H").charAt(0).toUpperCase()
  const formattedTime = formatTime12h(ride.departureTime)

  // Determine button state based on useRideRequestStatus
  let buttonLabel = "Request"
  let buttonStyle = "bg-[#E52E3D] text-white hover:bg-[#D02533] cursor-pointer"
  let isDisabled = false

  if (isHost) {
    buttonLabel = "Host"
    buttonStyle = "bg-[#262626] text-[#A0A0A0] border border-[#3A3A3A]"
    isDisabled = true
  } else if (statusLoading) {
    buttonLabel = "..."
    buttonStyle = "bg-[#262626] text-[#A0A0A0]"
    isDisabled = true
  } else if (reqStatus === "pending") {
    buttonLabel = "Requested"
    buttonStyle = "bg-[#2A2A2A] text-[#888888] border border-[#3A3A3A]"
    isDisabled = true
  } else if (reqStatus === "accepted") {
    buttonLabel = "Joined"
    buttonStyle = "bg-[#1B382B] text-[#4ADE80] border border-[#22543D]"
    isDisabled = true
  }

  return (
    <div
      className="bg-[#18181B] border border-[#27272A] rounded-[22px] p-4 shadow-sm text-white transition-all hover:border-[#3F3F46]"
    >
      <div className="flex items-start justify-between gap-3">

        {/* Left Column: Ride Details & Host Info */}
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={() => onCardClick?.(ride)}
        >
          {/* Time */}
          <p className="text-[13px] font-bold text-[#E52E3D] tracking-tight mb-0.5">
            {formattedTime}
          </p>

          {/* Route */}
          <h3 className="text-[16px] font-extrabold text-white truncate leading-tight">
            {ride.from} → {ride.to}
          </h3>

          {/* Seats & Location */}
          <p className="text-[12px] font-medium text-[#A1A1AA] mt-1 truncate">
            {ride.availableSeats} {ride.availableSeats === 1 ? "seat" : "seats"} {ride.meetingPoint ? `• ${ride.meetingPoint}` : ""}
          </p>

          {/* Host Info Row */}
          <div className="flex items-center space-x-2.5 mt-3 pt-2.5 border-t border-[#27272A]">
            <div className="h-8 w-8 rounded-full bg-[#27272A] border border-[#3F3F46] flex items-center justify-center text-[13px] font-bold text-white shrink-0">
              {initial}
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-[13px] font-bold text-white truncate leading-tight">
                {ride.hostName || "Host"}
              </span>
              <span className="text-[11px] font-medium text-[#A1A1AA] truncate">
                {formatBranchYear(ride.department, ride.year, ride.college || "CET")}
              </span>
            </div>
          </div>
        </div>

        {/* Right Column: Request Button */}
        <div className="flex flex-col items-end justify-center self-center shrink-0">
          <button
            type="button"
            disabled={isDisabled}
            onClick={(e) => {
              e.stopPropagation()
              if (!isDisabled) onRequest(ride)
            }}
            className={`px-5 py-2.5 rounded-full text-[13.5px] font-extrabold shadow-sm transition-all active:scale-95 ${buttonStyle}`}
          >
            {buttonLabel}
          </button>
        </div>

      </div>
    </div>
  )
}
