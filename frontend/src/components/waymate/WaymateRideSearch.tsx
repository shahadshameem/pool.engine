import { useState, useEffect, useRef } from "react"
import {
  MapPin,
  Search,
  X,
  ArrowUpDown,
  Footprints,
  Award,
  Car,
  Bike,
  User,
  Loader2,
  ChevronRight,
  ArrowRight,
  Compass,
  AlertCircle
} from "lucide-react"
import {
  searchLocations,
  getCurrentLiveLocation,
  CAMPUS_PRESETS,
  type LocationPoint
} from "../../utils/locationService"
import {
  findRidesBySmallestDistance,
  type H3RideDocument
} from "../../services/rideService"

/**
 * Crosshair Target GPS Icon matching user spec
 */
export function CurrentLocationIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-label="Use Current Location"
    >
      <circle cx="12" cy="12" r="7" />
      <circle cx="12" cy="12" r="3" fill="currentColor" stroke="none" />
      <line x1="12" y1="1.5" x2="12" y2="5" />
      <line x1="12" y1="19" x2="12" y2="22.5" />
      <line x1="1.5" y1="12" x2="5" y2="12" />
      <line x1="19" y1="12" x2="22.5" y2="12" />
    </svg>
  )
}

export interface WaymateRideSearchProps {
  initialFrom?: LocationPoint | null
  initialTo?: LocationPoint | null
  onSelectRide?: (ride: H3RideDocument) => void
  onRequestSeat?: (ride: H3RideDocument) => void
  onFromChange?: (loc: LocationPoint | null) => void
  onToChange?: (loc: LocationPoint | null) => void
  onFindRide?: (from: LocationPoint, to: LocationPoint) => void | Promise<void>
  onOfferRideClick?: (from: LocationPoint | null, to: LocationPoint | null) => void
  className?: string
}

export function WaymateRideSearch({
  initialFrom = null,
  initialTo = null,
  onSelectRide,
  onRequestSeat,
  onFromChange,
  onToChange,
  onFindRide,
  onOfferRideClick,
  className = ""
}: WaymateRideSearchProps) {
  // Location States
  const [fromPoint, setFromPoint] = useState<LocationPoint | null>(initialFrom)
  const [toPoint, setToPoint] = useState<LocationPoint | null>(initialTo)
  const [fromText, setFromText] = useState<string>(initialFrom?.name || "")
  const [toText, setToText] = useState<string>(initialTo?.name || "")

  // Live GPS Tracking State
  const [detectedGps, setDetectedGps] = useState<LocationPoint | null>(null)
  const [isLocating, setIsLocating] = useState<boolean>(false)
  const [gpsError, setGpsError] = useState<string | null>(null)

  // Focused input: "from" | "to" | null
  const [activeField, setActiveField] = useState<"from" | "to" | null>(null)

  // Suggestions & Autocomplete
  const [suggestions, setSuggestions] = useState<LocationPoint[]>([])
  const [isLoadingSuggestions, setIsLoadingSuggestions] = useState<boolean>(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Refs for auto-focusing
  const fromInputRef = useRef<HTMLInputElement>(null)
  const toInputRef = useRef<HTMLInputElement>(null)

  // Search Results State
  const [isSearchingRides, setIsSearchingRides] = useState<boolean>(false)
  const [hasSearched, setHasSearched] = useState<boolean>(false)
  const [matchedRides, setMatchedRides] = useState<H3RideDocument[]>([])
  const [searchError, setSearchError] = useState<string | null>(null)

  // 1. Auto-Live Location on Component Mount
  useEffect(() => {
    let isMounted = true

    async function detectLiveLocation() {
      setIsLocating(true)
      setGpsError(null)
      try {
        const liveLoc = await getCurrentLiveLocation()
        if (!isMounted) return

        setDetectedGps(liveLoc)
        if (liveLoc.isLowAccuracy) {
          setGpsError(liveLoc.subtext || "Low GPS accuracy. Please confirm your pickup point.")
        }

        // If from is not already specified by props, auto-fill with detected GPS
        if (!initialFrom) {
          setFromPoint(liveLoc)
          setFromText(liveLoc.name)
          onFromChange?.(liveLoc)

          // Smoothly focus "Where to?" input once live pickup is set
          setTimeout(() => {
            toInputRef.current?.focus()
            setActiveField("to")
          }, 250)
        }
      } catch (err: any) {
        if (!isMounted) return
        console.warn("[WaymateRideSearch] Live GPS detection error:", err)
        setGpsError("Could not access live GPS. Select a pickup point.")

        // Fallback default: CET Main Gate
        if (!initialFrom) {
          const cetDefault = CAMPUS_PRESETS[0]
          setFromPoint(cetDefault)
          setFromText(cetDefault.name)
          onFromChange?.(cetDefault)
        }
      } finally {
        if (isMounted) setIsLocating(false)
      }
    }

    detectLiveLocation()

    return () => {
      isMounted = false
    }
  }, [])

  // 2. Fetch Suggestions with debouncing and Haversine distance
  useEffect(() => {
    if (!activeField) {
      setSuggestions([])
      return
    }

    const query = activeField === "from" ? fromText : toText
    const refLat = fromPoint?.lat ?? detectedGps?.lat
    const refLng = fromPoint?.lng ?? detectedGps?.lng

    const isInstant = query.trim().length === 0
    const delay = isInstant ? 0 : 250

    if (debounceRef.current) clearTimeout(debounceRef.current)

    setIsLoadingSuggestions(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const list = await searchLocations(query, refLat, refLng)
        setSuggestions(list)
      } catch (err) {
        console.warn("[WaymateRideSearch] Suggestion error:", err)
        setSuggestions(CAMPUS_PRESETS)
      } finally {
        setIsLoadingSuggestions(false)
      }
    }, delay)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [activeField, fromText, toText, fromPoint?.lat, fromPoint?.lng, detectedGps?.lat, detectedGps?.lng])

  // Select a suggestion row
  const handleSelectLocation = (loc: LocationPoint) => {
    if (activeField === "from") {
      setFromPoint(loc)
      setFromText(loc.name)
      onFromChange?.(loc)
      setActiveField(null)

      // If destination isn't chosen yet, focus Destination input
      if (!toPoint) {
        setTimeout(() => {
          toInputRef.current?.focus()
          setActiveField("to")
        }, 150)
      }
    } else if (activeField === "to") {
      setToPoint(loc)
      setToText(loc.name)
      onToChange?.(loc)
      setActiveField(null)
    }
  }

  // 1-Tap Use Detected GPS
  const handleUseGpsAsPickup = async () => {
    if (detectedGps) {
      setFromPoint(detectedGps)
      setFromText(detectedGps.name)
      onFromChange?.(detectedGps)
      setActiveField(null)
      if (!toPoint) {
        setTimeout(() => {
          toInputRef.current?.focus()
          setActiveField("to")
        }, 150)
      }
    } else {
      setIsLocating(true)
      try {
        const loc = await getCurrentLiveLocation()
        setDetectedGps(loc)
        setFromPoint(loc)
        setFromText(loc.name)
        onFromChange?.(loc)
        if (loc.isLowAccuracy) {
          setGpsError(loc.subtext || "Low GPS accuracy. Please confirm your pickup point.")
        } else {
          setGpsError(null)
        }
        setActiveField(null)
        if (!toPoint) {
          setTimeout(() => {
            toInputRef.current?.focus()
            setActiveField("to")
          }, 150)
        }
      } catch (err) {
        alert("Unable to acquire live GPS location. Please check browser permissions.")
      } finally {
        setIsLocating(false)
      }
    }
  }

  // Swap From & To
  const handleSwap = () => {
    const tempP = fromPoint
    const tempT = fromText
    setFromPoint(toPoint)
    setFromText(toText)
    setToPoint(tempP)
    setToText(tempT)
    onFromChange?.(toPoint)
    onToChange?.(tempP)
  }

  // 3. Find Ride Button Trigger -> Smallest-Distance Matching
  const handleFindRide = async () => {
    if (!fromPoint || !toPoint) return

    setIsSearchingRides(true)
    setHasSearched(true)
    setSearchError(null)

    if (onFindRide) {
      try {
        await onFindRide(fromPoint, toPoint)
      } catch (err: any) {
        console.error("[WaymateRideSearch] onFindRide error:", err)
        setSearchError("Failed to search matching rides. Please try again.")
      } finally {
        setIsSearchingRides(false)
      }
      return
    }

    try {
      const results = await findRidesBySmallestDistance({
        source: { lat: fromPoint.lat, lng: fromPoint.lng },
        destination: { lat: toPoint.lat, lng: toPoint.lng },
        pickupRadiusMeters: 3000,
        dropoffRadiusMeters: 3000,
        minSeats: 1
      })

      setMatchedRides(results)
    } catch (err: any) {
      console.error("[WaymateRideSearch] findMatchingRides error:", err)
      setSearchError("Failed to search matching rides. Please try again.")
    } finally {
      setIsSearchingRides(false)
    }
  }

  return (
    <div className={`space-y-4 ${className}`}>
      {/* UBER-STYLE CONNECTED DUAL INPUT CARD */}
      <div className="bg-card border border-border/80 shadow-md rounded-[26px] p-4 relative">
        <div className="flex items-center space-x-3">
          {/* Left Vertical Connected Icons */}
          <div className="flex flex-col items-center justify-between self-stretch py-3 px-1">
            {/* From: Green/Emerald Circle */}
            <div className="h-4 w-4 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0">
              <div className="h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-emerald-500/40" />
            </div>

            {/* Connecting Vertical Line */}
            <div className="w-[2px] flex-1 bg-gradient-to-b from-emerald-500/50 via-border to-foreground/50 my-1" />

            {/* To: Square Icon */}
            <div className="h-4 w-4 rounded-sm bg-foreground/10 flex items-center justify-center shrink-0">
              <div className="h-2 w-2 rounded-xs bg-foreground" />
            </div>
          </div>

          {/* Center Input Rows */}
          <div className="flex-1 space-y-2">
            {/* FROM (PICKUP) ROW */}
            <div className="relative flex items-center">
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">
                    Pickup Location
                  </span>
                  {fromPoint?.isLiveGps && (
                    <span className="inline-flex items-center text-[10px] font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.2 rounded-full">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mr-1 animate-pulse" />
                      Live GPS
                    </span>
                  )}
                </div>
                <input
                  ref={fromInputRef}
                  type="text"
                  value={fromText}
                  onChange={(e) => {
                    setFromText(e.target.value)
                    setFromPoint(null)
                    onFromChange?.(null)
                  }}
                  onFocus={() => setActiveField("from")}
                  placeholder={isLocating ? "Detecting your live location..." : "Enter pickup location"}
                  className="w-full bg-transparent text-[14px] font-semibold text-foreground placeholder:text-muted-foreground/60 outline-none truncate pr-16"
                />
              </div>

              {/* Action buttons inside From field */}
              <div className="flex items-center space-x-1 shrink-0 ml-1">
                {/* Clear button (X) */}
                {fromText && (
                  <button
                    type="button"
                    onClick={() => {
                      setFromText("")
                      setFromPoint(null)
                      onFromChange?.(null)
                      fromInputRef.current?.focus()
                      setActiveField("from")
                    }}
                    className="p-1 rounded-full text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
                    title="Clear pickup"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}

                {/* Current Location Target Icon (From option only, like attached image) */}
                <button
                  type="button"
                  onClick={handleUseGpsAsPickup}
                  disabled={isLocating}
                  className="p-1.5 rounded-full text-foreground/80 hover:text-foreground hover:bg-muted active:scale-90 transition-all cursor-pointer"
                  title="Use Current Location"
                  aria-label="Use Current Location"
                >
                  <CurrentLocationIcon className={`h-5 w-5 ${isLocating ? "animate-spin text-primary" : "text-foreground hover:text-primary"}`} />
                </button>
              </div>
            </div>

            {/* DIVIDER LINE */}
            <div className="border-b border-border/60" />

            {/* TO (DESTINATION) ROW */}
            <div className="relative flex items-center">
              <div className="flex-1 min-w-0">
                <span className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground block mb-0.5">
                  Where to?
                </span>
                <input
                  ref={toInputRef}
                  type="text"
                  value={toText}
                  onChange={(e) => {
                    setToText(e.target.value)
                    setToPoint(null)
                    onToChange?.(null)
                  }}
                  onFocus={() => setActiveField("to")}
                  placeholder="Where to? (e.g. Technopark, LuLu Mall)"
                  className="w-full bg-transparent text-[14px] font-semibold text-foreground placeholder:text-muted-foreground/60 outline-none truncate pr-6"
                />
              </div>

              {/* Clear button (X) */}
              {toText && (
                <button
                  type="button"
                  onClick={() => {
                    setToText("")
                    setToPoint(null)
                    onToChange?.(null)
                    toInputRef.current?.focus()
                    setActiveField("to")
                  }}
                  className="p-1 rounded-full text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
                  title="Clear destination"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* Right Swap Button */}
          <button
            type="button"
            onClick={handleSwap}
            className="p-2.5 rounded-2xl bg-muted/70 hover:bg-muted text-foreground border border-border/50 hover:scale-105 active:scale-95 transition-all cursor-pointer self-center"
            title="Swap locations"
          >
            <ArrowUpDown className="h-4 w-4" />
          </button>
        </div>

        {gpsError && (
          <div className="mt-2 text-[11px] text-amber-600 dark:text-amber-400 flex items-center space-x-1.5 px-1">
            <AlertCircle className="h-3 w-3 shrink-0" />
            <span>{gpsError}</span>
          </div>
        )}

        {/* Action Button: Find Ride */}
        <div className="mt-4 pt-3 border-t border-border/60 flex items-center space-x-2">
          <button
            type="button"
            disabled={!fromPoint || !toPoint || isSearchingRides}
            onClick={handleFindRide}
            className={`flex-1 h-12 rounded-[18px] font-extrabold text-[15px] flex items-center justify-center space-x-2 transition-all cursor-pointer ${
              fromPoint && toPoint
                ? "bg-[#C5FF00] hover:bg-[#b5ee00] text-black shadow-md hover:shadow-lg active:scale-[0.98]"
                : "bg-muted text-muted-foreground cursor-not-allowed opacity-70"
            }`}
          >
            {isSearchingRides ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Finding Closest Rides...</span>
              </>
            ) : (
              <>
                <Search className="h-4 w-4" />
                <span>Find Ride</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* DROPDOWN SUGGESTIONS LIST (WHEN TYPING OR FOCUSED) */}
      {activeField && (
        <div className="bg-card border border-border/80 shadow-xl rounded-[24px] overflow-hidden divide-y divide-border/40 animate-in fade-in slide-in-from-top-2 duration-150">
          {/* Header Bar */}
          <div className="px-4 py-2.5 bg-muted/40 flex items-center justify-between text-xs font-bold text-muted-foreground">
            <span className="flex items-center space-x-1.5">
              <Compass className="h-3.5 w-3.5 text-primary" />
              <span>
                {activeField === "from" ? "Choose Pickup Location" : "Choose Destination"}
              </span>
            </span>
            <button
              type="button"
              onClick={() => setActiveField(null)}
              className="text-xs font-semibold hover:text-foreground cursor-pointer"
            >
              Close
            </button>
          </div>

          {/* Suggestion Rows */}
          {isLoadingSuggestions ? (
            <div className="py-6 text-center space-y-2">
              <Loader2 className="h-5 w-5 animate-spin mx-auto text-primary" />
              <p className="text-xs font-medium text-muted-foreground">Searching Trivandrum locations...</p>
            </div>
          ) : suggestions.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">
              No matching locations found in Trivandrum. Try a different landmark or junction.
            </div>
          ) : (
            <div className="max-h-[320px] overflow-y-auto divide-y divide-border/30">
              {suggestions.map((loc, idx) => (
                <button
                  key={`${loc.name}-${idx}`}
                  type="button"
                  onClick={() => handleSelectLocation(loc)}
                  className="w-full px-4 py-3 text-left flex items-center space-x-3 hover:bg-muted/60 transition-colors cursor-pointer group"
                >
                  {/* Left Icon + Distance Below */}
                  <div className="flex flex-col items-center justify-center shrink-0 w-11">
                    <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center text-muted-foreground group-hover:text-primary group-hover:bg-primary/10 transition-colors">
                      <MapPin className="h-4 w-4" />
                    </div>
                    {loc.distanceFormatted && (
                      <span className="text-[10px] font-extrabold text-primary tracking-tight mt-0.5">
                        {loc.distanceFormatted}
                      </span>
                    )}
                  </div>

                  {/* Place Name & Sub-locality */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-2">
                      <p className="text-[13px] font-bold text-foreground truncate group-hover:text-primary transition-colors">
                        {loc.name}
                      </p>
                      {loc.isPreset && (
                        <span className="text-[9px] font-extrabold uppercase px-1.5 py-0.2 bg-[#C5FF00]/20 text-black dark:text-[#C5FF00] rounded-md shrink-0">
                          Preset
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground truncate">
                      {loc.subtext || loc.area || "Thiruvananthapuram, Kerala"}
                    </p>
                  </div>

                  <ChevronRight className="h-4 w-4 text-muted-foreground/40 group-hover:text-foreground group-hover:translate-x-0.5 transition-all shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* SEARCH RESULTS SECTION */}
      {hasSearched && !isSearchingRides && (
        <div className="space-y-3 pt-2">
          {searchError && (
            <div className="p-3 rounded-2xl bg-destructive/10 text-destructive text-xs font-semibold flex items-center space-x-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{searchError}</span>
            </div>
          )}

          {matchedRides.length > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-extrabold text-foreground tracking-wide uppercase">
                  Available Rides ({matchedRides.length})
                </span>
                <span className="text-xs font-bold text-primary">
                  Sorted by Shortest Walking Distance
                </span>
              </div>

              {matchedRides.map((ride, index) => {
                const isTopMatch = index === 0 || ride.isClosestMatch
                const vehicle = (ride.vehicleType || "bike").toLowerCase()

                return (
                  <div
                    key={ride.id || index}
                    onClick={() => onSelectRide?.(ride)}
                    className={`bg-card rounded-[22px] border p-4 space-y-3 transition-all relative overflow-hidden cursor-pointer hover:shadow-md ${
                      isTopMatch
                        ? "border-[#C5FF00] ring-1 ring-[#C5FF00]/60 shadow-sm"
                        : "border-border/70 hover:border-border"
                    }`}
                  >
                    {/* #1 Closest Match Gold/Lime Ribbon */}
                    {isTopMatch && (
                      <div className="bg-[#C5FF00] text-black text-[10px] font-black uppercase tracking-wider px-3 py-1 rounded-bl-xl absolute top-0 right-0 flex items-center space-x-1 shadow-xs">
                        <Award className="h-3 w-3 stroke-[2.5]" />
                        <span>#1 Closest Match</span>
                      </div>
                    )}

                    {/* Proximity Walk Badge */}
                    <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[11px] font-bold border border-blue-500/20 w-fit">
                      <Footprints className="h-3.5 w-3.5 shrink-0" />
                      <span>
                        {ride.proximityBadge ||
                          `Pickup: ${ride.pickupDistanceFormatted || "nearby"} • Drop-off: ${ride.dropoffDistanceFormatted || "nearby"}`}
                      </span>
                    </div>

                    {/* Origin & Destination */}
                    <div className="space-y-1.5">
                      <div className="flex items-center space-x-2 text-[14px] font-bold text-foreground">
                        <span className="h-2 w-2 rounded-full bg-blue-500 shrink-0" />
                        <span className="truncate">{ride.source?.name || (ride as any).from || "Origin"}</span>
                      </div>
                      <div className="flex items-center space-x-2 text-[14px] font-bold text-foreground">
                        <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
                        <span className="truncate">{ride.destination?.name || (ride as any).to || "Destination"}</span>
                      </div>
                    </div>

                    {/* Footer Details */}
                    <div className="flex items-center justify-between pt-2 border-t border-border/40 text-xs">
                      <div className="flex items-center space-x-3">
                        <div className="flex items-center space-x-1 font-semibold text-foreground">
                          <User className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="truncate max-w-[100px]">{ride.driverName || (ride as any).hostName || "Driver"}</span>
                        </div>
                        <div className="flex items-center space-x-1 text-muted-foreground">
                          {vehicle === "car" ? <Car className="h-3.5 w-3.5 text-primary" /> : <Bike className="h-3.5 w-3.5 text-primary" />}
                          <span className="capitalize">{vehicle}</span>
                        </div>
                      </div>

                      <div className="flex items-center space-x-2">
                        <div className="text-right">
                          <span className="text-[14px] font-black text-foreground">
                            {ride.farePerSeat ? `₹${ride.farePerSeat}` : "Free"}
                          </span>
                          <span className="text-[10px] text-muted-foreground block">
                            {ride.availableSeats ?? 1} seat left
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
          ) : (
            <div className="p-6 text-center bg-card border border-border/60 rounded-[24px] space-y-3">
              <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mx-auto text-muted-foreground">
                <Search className="h-6 w-6" />
              </div>
              <div className="space-y-1">
                <h3 className="text-[15px] font-extrabold text-foreground">No matching rides found</h3>
                <p className="text-xs text-muted-foreground">
                  No drivers traveling along this corridor right now.
                </p>
              </div>
              {onOfferRideClick && (
                <button
                  type="button"
                  onClick={() => onOfferRideClick(fromPoint, toPoint)}
                  className="px-4 py-2 bg-[#C5FF00] text-black text-xs font-extrabold rounded-xl hover:opacity-90 active:scale-95 transition-all cursor-pointer inline-flex items-center space-x-1.5"
                >
                  <Car className="h-3.5 w-3.5" />
                  <span>Offer a Ride on this Route</span>
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default WaymateRideSearch