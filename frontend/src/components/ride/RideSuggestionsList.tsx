import {
  Award,
  MapPin,
  Clock,
  User,
  Car,
  Bike,
  Footprints,
  ArrowRight
} from "lucide-react"
import type { H3RideDocument } from "../../services/rideService"

export interface RideSuggestionsListProps {
  rides: H3RideDocument[]
  isLoading?: boolean
  onSelectRide?: (ride: H3RideDocument) => void
  onRequestSeat?: (ride: H3RideDocument) => void
  emptyMessage?: string
}

export function RideSuggestionsList({
  rides,
  isLoading = false,
  onSelectRide,
  onRequestSeat,
  emptyMessage = "No matching rides found within your selected pickup/drop-off radius."
}: RideSuggestionsListProps) {
  if (isLoading) {
    return (
      <div className="space-y-3 py-6">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-32 bg-muted/40 animate-pulse rounded-2xl border border-border/50 p-4" />
        ))}
      </div>
    )
  }

  if (rides.length === 0) {
    return (
      <div className="p-8 text-center bg-card border border-border/60 rounded-2xl space-y-2">
        <MapPin className="h-8 w-8 text-muted-foreground mx-auto opacity-50" />
        <p className="text-sm font-semibold text-foreground">{emptyMessage}</p>
        <p className="text-xs text-muted-foreground">
          Try expanding your search radius slider on the map to find more campus drivers.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3.5">
      <div className="flex items-center justify-between px-1">
        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
          Matched Rides (Ordered by Shortest Walk)
        </h3>
        <span className="text-xs font-bold text-primary">
          {rides.length} {rides.length === 1 ? "Ride" : "Rides"} Available
        </span>
      </div>

      <div className="space-y-3">
        {rides.map((ride, index) => {
          const isTopMatch = index === 0 || ride.isClosestMatch
          const vehicle = (ride.vehicleType || "bike").toLowerCase()

          return (
            <div
              key={ride.id || index}
              onClick={() => onSelectRide?.(ride)}
              className={`bg-card rounded-2xl border p-4 transition-all relative overflow-hidden cursor-pointer hover:shadow-md ${
                isTopMatch
                  ? "border-primary/80 ring-1 ring-primary/40 shadow-sm"
                  : "border-border/60 hover:border-border"
              }`}
            >
              {/* #1 Closest Match Banner */}
              {isTopMatch && (
                <div className="bg-primary text-primary-foreground text-[10px] font-black uppercase tracking-wider px-3 py-1 rounded-bl-xl absolute top-0 right-0 flex items-center space-x-1 shadow-xs">
                  <Award className="h-3 w-3 stroke-[2.5]" />
                  <span>#1 Closest Match (Minimal Walking)</span>
                </div>
              )}

              {/* Proximity Walking Distance Badge */}
              <div className="mb-2.5">
                <div className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[11px] font-bold border border-blue-500/20">
                  <Footprints className="h-3.5 w-3.5 shrink-0" />
                  <span>
                    {ride.proximityBadge ||
                      `Pickup: ${ride.pickupDistanceFormatted || "nearby"} • Drop-off: ${ride.dropoffDistanceFormatted || "nearby"} (Walk: ${ride.totalDistanceFormatted || "~"})`}
                  </span>
                </div>
              </div>

              {/* Route Endpoints */}
              <div className="space-y-1.5 mb-3">
                <div className="flex items-center space-x-2 text-[14px] font-bold text-foreground">
                  <span className="h-2 w-2 rounded-full bg-blue-500 shrink-0" />
                  <span className="truncate">{ride.source?.name || (ride as any).from || "Trivandrum Origin"}</span>
                </div>
                <div className="flex items-center space-x-2 text-[14px] font-bold text-foreground">
                  <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
                  <span className="truncate">{ride.destination?.name || (ride as any).to || "Trivandrum Destination"}</span>
                </div>
              </div>

              {/* Driver & Ride Details Footer */}
              <div className="flex items-center justify-between pt-3 border-t border-border/40 text-xs">
                <div className="flex items-center space-x-3">
                  <div className="flex items-center space-x-1 font-semibold text-foreground">
                    <User className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="truncate max-w-[110px]">{ride.driverName || (ride as any).hostName || "Driver"}</span>
                  </div>

                  <div className="flex items-center space-x-1 text-muted-foreground">
                    {vehicle === "car" ? (
                      <Car className="h-3.5 w-3.5 text-primary" />
                    ) : (
                      <Bike className="h-3.5 w-3.5 text-primary" />
                    )}
                    <span className="capitalize">{vehicle}</span>
                  </div>

                  {ride.departureTime && (
                    <div className="flex items-center space-x-1 text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{typeof ride.departureTime === "string" ? ride.departureTime : "Today"}</span>
                    </div>
                  )}
                </div>

                <div className="flex items-center space-x-2">
                  <div className="text-right">
                    <span className="text-[14px] font-black text-foreground">
                      {ride.farePerSeat ? `₹${ride.farePerSeat}` : "Free"}
                    </span>
                    <span className="text-[10px] text-muted-foreground block">
                      {ride.availableSeats ?? (ride as any).totalSeats ?? 1} seat left
                    </span>
                  </div>

                  {onRequestSeat && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        onRequestSeat(ride)
                      }}
                      className="px-3 py-1.5 bg-[#C5FF00] hover:bg-[#b2eb00] text-black font-extrabold text-xs rounded-xl flex items-center space-x-1 shadow-2xs active:scale-95 transition-all cursor-pointer"
                    >
                      <span>Request</span>
                      <ArrowRight className="h-3 w-3" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default RideSuggestionsList
