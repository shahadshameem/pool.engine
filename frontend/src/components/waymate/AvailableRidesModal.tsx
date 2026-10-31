import { createPortal } from "react-dom"
import { useNavigate } from "react-router-dom"
import { formatRideDateTime, formatBranchYear } from "../../utils/formatters"
import { MaterialIcon } from "../common/MaterialIcon"
import { Button } from "../ui/button"

export interface AvailableRidesModalProps {
  isOpen: boolean
  onClose: () => void
  rides: any[]
  isSearching: boolean
  onRequestSeat: (ride: any) => void
  onOfferRide: () => void
}

export function AvailableRidesModal({
  isOpen,
  onClose,
  rides,
  isSearching,
  onRequestSeat,
  onOfferRide
}: AvailableRidesModalProps) {
  const navigate = useNavigate()

  if (!isOpen) return null

  return createPortal(
    <>
      {/* Semi-transparent dark backdrop overlay */}
      <div
        className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
        onClick={onClose}
      />

      {/* Centered Rounded Panel Modal */}
      <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 pointer-events-none">
        <div
          className="pointer-events-auto bg-card text-foreground rounded-[28px] border border-border/60 shadow-2xl w-full max-w-md max-h-[85vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header Row */}
          <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-border/40 shrink-0">
            <h2 className="text-edex-subheading font-bold text-foreground">
              Available Rides ({rides.length})
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="h-9 w-9 rounded-full bg-muted text-foreground hover:bg-muted/80 transition-all flex items-center justify-center cursor-pointer shrink-0"
              aria-label="Close"
            >
              <MaterialIcon name="close" className="text-[20px]" />
            </button>
          </div>

          {/* Scrollable vertical list of cards */}
          <div className="px-5 py-4 overflow-y-auto space-y-4 flex-1">
            {isSearching ? (
              <div className="py-12 text-center text-[14px] font-medium text-muted-foreground animate-pulse">
                Searching available rides...
              </div>
            ) : rides.length > 0 ? (
              rides.map(ride => (
                <div
                  key={ride.id}
                  className="bg-muted/40 border border-border/60 rounded-[22px] p-4 space-y-3.5 shadow-xs"
                >
                  {/* Top Row: Route & Date */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-stretch space-x-3 min-w-0 flex-1">
                      <div className="relative flex flex-col items-center shrink-0 w-3.5 self-stretch my-1">
                        <div className="w-3.5 h-3.5 rounded-full bg-[#3B82F6] ring-2 ring-[#3B82F6]/30 shrink-0 z-10" />
                        <div className="w-[2px] flex-1 border-l-2 border-dashed border-foreground/30 dark:border-white/40 my-1" />
                        <div className="w-3.5 h-3.5 rounded-full bg-[#25D366] ring-2 ring-[#25D366]/30 shrink-0 z-10" />
                      </div>

                      <div className="flex flex-col justify-between space-y-2 min-w-0 flex-1 py-0.5">
                        <div className="text-[15px] font-bold text-foreground leading-snug truncate">
                          {ride.from}
                        </div>
                        <div className="text-[15px] font-bold text-foreground leading-snug truncate">
                          {ride.to}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-col items-end space-y-1.5 shrink-0 pt-0.5">
                      <div className="flex items-center space-x-1.5 text-[12px] font-medium text-muted-foreground">
                        <MaterialIcon name="calendar_today" className="text-[14px]" />
                        <span>{formatRideDateTime(ride.date, ride.departureTime)}</span>
                      </div>

                      <span className="bg-[#C5FF00] text-black px-2.5 py-0.5 rounded-full text-[12px] font-extrabold shadow-2xs">
                        {ride.availableSeats} {ride.availableSeats === 1 ? "seat left" : "seats left"}
                      </span>
                    </div>
                  </div>

                  <div className="border-t border-border/40" />

                  {/* Bottom Row: Host Info & CTAs */}
                  <div className="flex items-center justify-between gap-2 pt-0.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] font-bold text-foreground truncate">
                        {ride.hostName || "Host"}
                      </div>
                      <div className="text-[12px] text-muted-foreground truncate">
                        {formatBranchYear(ride.department, ride.year, ride.college || "CET")}
                      </div>
                    </div>

                    <div className="flex items-center space-x-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => {
                          onClose()
                          navigate(`/rides/${ride.id}`)
                        }}
                        className="h-9 px-3 bg-muted text-foreground hover:bg-muted/80 font-bold text-[13px] rounded-full border border-border/40 transition-all cursor-pointer"
                      >
                        View Details
                      </button>

                      <Button
                        type="button"
                        variant="primary"
                        size="sm"
                        className="h-9 px-3 text-[13px]"
                        onClick={() => onRequestSeat(ride)}
                      >
                        Request Seat
                      </Button>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-8 text-center space-y-3">
                <MaterialIcon name="search_off" className="text-[36px] text-muted-foreground/60" />
                <p className="text-[15px] font-bold text-foreground">No rides found for this route and time.</p>
                <p className="text-[13px] text-muted-foreground max-w-[280px] mx-auto">
                  Try adjusting your date or offer a ride yourself to help other students!
                </p>
                <Button
                  variant="accent"
                  size="default"
                  className="mt-2"
                  onClick={() => {
                    onClose()
                    onOfferRide()
                  }}
                >
                  Offer a Ride Instead
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>,
    document.body
  )
}
