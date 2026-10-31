import { formatTime12h, formatDate, formatBranchYear } from "../../utils/formatters"

export interface StandardRideData {
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

interface StandardRideCardProps {
  ride: StandardRideData
  role?: "host" | "requested" | "confirmed" | "none"
  requestStatus?: string
  onAction?: (ride: StandardRideData) => void
  onCardClick?: (ride: StandardRideData) => void
  actionLabel?: string
  actionDisabled?: boolean
  className?: string
}

export function StandardRideCard({
  ride,
  role: _role = "none",
  requestStatus: _requestStatus,
  onAction,
  onCardClick,
  actionLabel = "Request",
  actionDisabled = false,
  className = ""
}: StandardRideCardProps) {
  const initial = (ride.hostName || "H").charAt(0).toUpperCase()
  const formattedTime = formatTime12h(ride.departureTime)
  const formattedDateStr = formatDate(ride.date)

  return (
    <div
      className={`bg-card border border-border/60 rounded-[20px] p-4 transition-all hover:border-foreground/30 ${className}`}
    >
      <div className="flex items-start justify-between gap-3">

        {/* Left Column: Route, Date & Host Info */}
        <div
          className="flex-1 min-w-0 cursor-pointer space-y-1"
          onClick={() => onCardClick?.(ride)}
        >
          {/* Header Row: Time */}
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-semibold text-muted-foreground">
              {formattedTime} • {formattedDateStr}
            </span>
          </div>

          {/* Route */}
          <h3 className="text-[16px] font-bold text-foreground truncate leading-tight">
            {ride.from} → {ride.to}
          </h3>

          {/* Seats */}
          <p className="text-[12px] font-medium text-muted-foreground truncate">
            {ride.availableSeats} {ride.availableSeats === 1 ? "seat" : "seats"} left {ride.meetingPoint ? `• ${ride.meetingPoint}` : ""}
          </p>

          {/* Host Info Row */}
          <div className="flex items-center space-x-2.5 pt-2 border-t border-border/40 mt-2">
            <div className="h-8 w-8 rounded-full bg-muted border border-border/40 flex items-center justify-center text-[12px] font-bold text-foreground uppercase shrink-0">
              {initial}
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-[13px] font-bold text-foreground truncate leading-tight">
                {ride.hostName || "Host"}
              </span>
              <span className="text-[11px] font-normal text-muted-foreground truncate">
                {formatBranchYear(ride.department, ride.year, ride.college || "CET")}
              </span>
            </div>
          </div>
        </div>

        {/* Right Column: Action Button */}
        {onAction && (
          <div className="flex flex-col items-end justify-center self-center shrink-0">
            <button
              type="button"
              disabled={actionDisabled}
              onClick={(e) => {
                e.stopPropagation()
                if (!actionDisabled) onAction(ride)
              }}
              className={`px-4 h-10 rounded-full text-[14px] font-bold transition-all active:scale-[0.98] ${
                actionDisabled
                  ? "bg-muted text-muted-foreground border border-border/40 cursor-not-allowed"
                  : "bg-[#C5FF00] text-black font-extrabold hover:opacity-90 cursor-pointer"
              }`}
            >
              {actionLabel}
            </button>
          </div>
        )}

      </div>
    </div>
  )
}
