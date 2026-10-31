import { useState, useEffect } from "react"
import { useNavigate, useLocation } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { WaymateRideSearch } from "../components/waymate/WaymateRideSearch"
import { DateTimeFields } from "../components/common/DateTimeFields"
import { CampusBroadcastBanner } from "../components/common/CampusBroadcastBanner"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { rideService } from "../services/ride/rideService"
import { findRidesBySmallestDistance } from "../services/rideService"
import { getDistanceInMeters, formatDistance } from "../utils/locationService"
import { Award, Clock } from "lucide-react"
import { userService } from "../services/user/userService"
import type { FixedLocation } from "../config/locations"
import { formatTime12h, getLocalDateString, formatBranchYear, cleanLocationDisplayName } from "../utils/formatters"
import { isDevMockEnabled } from "../utils/devMock"
import { useSEO } from "../hooks/useSEO"

export function FindRidePage() {
  useSEO({
    title: "Find College Rides & Student Carpools",
    description: "Search and join verified campus rides, cab pools, and auto shares to CET Trivandrum, Technopark, and nearby college hubs.",
    canonicalPath: "/rides/search",
  })

  const navigate = useNavigate()
  const { goBack } = useBackNavigation()
  const location = useLocation()
  const { user, profile, loading: authLoading } = useAuth()

  const navState = location.state as {
    fromLocation?: FixedLocation
    toLocation?: FixedLocation
    date?: string
    departureTime?: string
    seats?: number
  } | null

  const todayStr = getLocalDateString()
  const [fromLocation, setFromLocation] = useState<FixedLocation | undefined>(navState?.fromLocation)
  const [toLocation, setToLocation] = useState<FixedLocation | undefined>(navState?.toLocation)
  const [date, setDate] = useState<string>((navState?.date && navState.date >= todayStr) ? navState.date : todayStr)
  const [departureTime, setDepartureTime] = useState<string>(navState?.departureTime || "")
  const [seats, setSeats] = useState<number>(navState?.seats || 1)
  const [showAdvancedSchedule, setShowAdvancedSchedule] = useState(false)

  const [isSearching, setIsSearching] = useState(false)
  const [hasSearched, setHasSearched] = useState(false)
  const [results, setResults] = useState<any[]>([])
  const [hostProfiles, setHostProfiles] = useState<Record<string, any>>({})

  useEffect(() => {
    if (!authLoading && !user && !isDevMockEnabled()) {
      navigate("/login", { replace: true })
    }
  }, [user, authLoading, navigate])

  const executeSearch = async (
    fromLoc?: FixedLocation,
    toLoc?: FixedLocation,
    dVal?: string,
    tVal?: string,
    sVal?: number
  ) => {
    const f = fromLoc || fromLocation
    const t = toLoc || toLocation
    if (!f || !t) return

    setIsSearching(true)
    setHasSearched(true)
    setResults([])

    try {
      // 1. Text & Route Search
      const rides = await rideService.searchRides({
        from: f.address || f.name,
        to: t.address || t.name,
        date: dVal || date,
        time: tVal || departureTime,
        seats: sVal || seats || 1,
        userGender: profile?.gender,
        userId: user?.uid,
        matchedZoneId: f.matchedZoneId,
        fromCoords: (f.latitude && f.longitude) ? { lat: f.latitude, lng: f.longitude } : undefined
      })

      // 2. Spatial Smallest-Distance Matching
      let geoRides: any[] = []
      if (f.latitude && f.longitude && t.latitude && t.longitude) {
        try {
          geoRides = await findRidesBySmallestDistance({
            source: { lat: f.latitude, lng: f.longitude },
            destination: { lat: t.latitude, lng: t.longitude },
            pickupRadiusMeters: 4000,
            dropoffRadiusMeters: 4000,
            minSeats: sVal || seats || 1,
            date: dVal || date,
            time: tVal || departureTime,
            userId: user?.uid
          })
        } catch (err) {
          console.warn("[FindRidePage] Geo matching error:", err)
        }
      }

      // Merge rides from both sources
      const allRidesMap = new Map<string, any>()
      rides.forEach(r => {
        if (r.id) allRidesMap.set(r.id, r)
      })
      geoRides.forEach(r => {
        if (r.id) {
          const existing = allRidesMap.get(r.id)
          allRidesMap.set(r.id, { ...existing, ...r })
        }
      })

      const combinedRides = Array.from(allRidesMap.values()).filter(r => (r.ownerId || r.driverId) !== user?.uid)

      // Calculate exact distance metrics for each ride
      const enrichedRides = combinedRides.map(ride => {
        const driverSrc = {
          lat: ride.fromLocation?.latitude ?? ride.source?.lat,
          lng: ride.fromLocation?.longitude ?? ride.source?.lng
        }
        const driverDst = {
          lat: ride.toLocation?.latitude ?? ride.destination?.lat,
          lng: ride.toLocation?.longitude ?? ride.destination?.lng
        }

        if (f.latitude && f.longitude && driverSrc.lat && driverSrc.lng && driverDst.lat && driverDst.lng) {
          const pickupDist = getDistanceInMeters(f.latitude, f.longitude, driverSrc.lat, driverSrc.lng)
          const dropoffDist = getDistanceInMeters(t.latitude, t.longitude, driverDst.lat, driverDst.lng)
          const totalDist = pickupDist + dropoffDist
          return {
            ...ride,
            pickupDistanceMeters: pickupDist,
            dropoffDistanceMeters: dropoffDist,
            totalDistanceMeters: totalDist,
            pickupDistanceFormatted: formatDistance(pickupDist),
            dropoffDistanceFormatted: formatDistance(dropoffDist),
            totalDistanceFormatted: formatDistance(totalDist),
            proximityBadge: `Pickup: ${formatDistance(pickupDist)} away • Drop-off: ${formatDistance(dropoffDist)} away (Total walk: ${formatDistance(totalDist)})`
          }
        }
        return ride
      })

      // Sort strictly in ascending order of totalDistanceMeters (shortest walk at top)
      enrichedRides.sort((a, b) => {
        const distA = a.totalDistanceMeters ?? 999999
        const distB = b.totalDistanceMeters ?? 999999
        if (distA !== distB) return distA - distB
        const pickA = a.pickupDistanceMeters ?? 999999
        const pickB = b.pickupDistanceMeters ?? 999999
        return pickA - pickB
      })

      if (enrichedRides.length > 0 && enrichedRides[0].totalDistanceMeters !== undefined) {
        enrichedRides[0].isClosestMatch = true
      }

      setResults(enrichedRides)

      // Fetch host profiles using batch loader (chunks of 30, cached, and phone-stripped)
      const hostIds = Array.from(new Set(enrichedRides.map(r => (r.ownerId || r.driverId) as string).filter(Boolean)))
      const profilesMap = await userService.getUserProfilesBatch(hostIds)
      setHostProfiles(profilesMap)
    } catch (e) {
      console.error("Error searching rides:", e)
    } finally {
      setIsSearching(false)
    }
  }

  // Auto-sync search on mount or navState update
  useEffect(() => {
    if (navState) {
      const effectiveDate = (navState.date && navState.date >= todayStr) ? navState.date : todayStr
      if (navState.fromLocation) setFromLocation(navState.fromLocation)
      if (navState.toLocation) setToLocation(navState.toLocation)
      setDate(effectiveDate)
      if (navState.departureTime) setDepartureTime(navState.departureTime)
      if (navState.seats) setSeats(navState.seats)

      if (navState.fromLocation && navState.toLocation) {
        executeSearch(
          navState.fromLocation,
          navState.toLocation,
          effectiveDate,
          navState.departureTime,
          navState.seats
        )
      }
    }
  }, [location.state, location.key, user])

  const routeSubhead = fromLocation && toLocation
    ? `${cleanLocationDisplayName(fromLocation.name)} → ${cleanLocationDisplayName(toLocation.name)}`
    : "Search Rides"

  return (
    <MobileShell hideBottomNav hasStickyHeader className="flex flex-col min-h-screen bg-black">
      {/* 1. TOP HEADER */}
      <div className={`sticky top-0 z-10 flex items-center justify-between px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 bg-black ${hasSearched ? "border-b-0" : "border-b border-border/40"}`}>
        <button
          onClick={goBack}
          className="h-10 w-10 rounded-full bg-[#1c1c1e] flex items-center justify-center text-white hover:bg-zinc-800 cursor-pointer transition-colors shrink-0"
          aria-label="Back"
        >
          <MaterialIcon name="arrow_back" className="text-[20px]" />
        </button>
        <div className="text-center px-2 flex-1">
          <h1 className="text-[20px] font-extrabold text-white leading-tight">
            {hasSearched ? (results.length > 0 ? "Rides Found" : "No Rides Found") : "Find a Ride"}
          </h1>
          {hasSearched && (
            fromLocation && toLocation ? (
              <div className="text-[13px] text-[#8E8E93] font-medium leading-tight mt-1 text-center">
                <div>{cleanLocationDisplayName(fromLocation.name)} &rarr;</div>
                <div>{cleanLocationDisplayName(toLocation.name)}</div>
              </div>
            ) : (
              <p className="text-[12px] text-zinc-400 font-medium mt-0.5">{routeSubhead}</p>
            )
          )}
        </div>
        <div className="w-10 shrink-0" />
      </div>

      <div className="p-4 flex-1 flex flex-col space-y-4 bg-black">
        {!hasSearched && <CampusBroadcastBanner />}
        {/* If user hasn't searched yet or wants to adjust search criteria */}
        {!hasSearched && (
          <div className="space-y-4">
            <div className="flex items-center justify-between px-1">
              <div>
                <h2 className="text-[18px] font-extrabold text-foreground">Plan Your Ride</h2>
                <p className="text-[12px] text-muted-foreground">Uber-style instant distance matching</p>
              </div>
              <button
                type="button"
                onClick={() => setShowAdvancedSchedule(!showAdvancedSchedule)}
                className="text-xs font-bold text-primary flex items-center space-x-1 cursor-pointer hover:underline py-1 px-2 rounded-lg hover:bg-primary/10 transition-colors"
              >
                <span>{showAdvancedSchedule ? "Hide Schedule" : "Add Date & Time"}</span>
              </button>
            </div>

            {showAdvancedSchedule && (
              <div className="bg-card border border-border/60 rounded-[22px] p-4 shadow-sm animate-in fade-in slide-in-from-top-2">
                <DateTimeFields
                  date={date}
                  time={departureTime}
                  seats={seats}
                  minDate={todayStr}
                  onDateChange={(d) => setDate(d)}
                  onTimeChange={(t) => setDepartureTime(t)}
                  onSeatsChange={(s) => setSeats(s)}
                />
              </div>
            )}

            <WaymateRideSearch
              initialFrom={fromLocation ? {
                name: fromLocation.name,
                lat: fromLocation.latitude,
                lng: fromLocation.longitude,
                area: fromLocation.address
              } : null}
              initialTo={toLocation ? {
                name: toLocation.name,
                lat: toLocation.latitude,
                lng: toLocation.longitude,
                area: toLocation.address
              } : null}
              onFromChange={(loc) => {
                if (loc) {
                  setFromLocation({
                    id: loc.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                    name: loc.name,
                    address: loc.area || loc.name,
                    latitude: loc.lat,
                    longitude: loc.lng
                  })
                } else {
                  setFromLocation(undefined)
                }
              }}
              onToChange={(loc) => {
                if (loc) {
                  setToLocation({
                    id: loc.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                    name: loc.name,
                    address: loc.area || loc.name,
                    latitude: loc.lat,
                    longitude: loc.lng
                  })
                } else {
                  setToLocation(undefined)
                }
              }}
              onFindRide={async (from, to) => {
                const fLoc: FixedLocation = {
                  id: from.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                  name: from.name,
                  address: from.area || from.name,
                  latitude: from.lat,
                  longitude: from.lng
                }
                const tLoc: FixedLocation = {
                  id: to.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                  name: to.name,
                  address: to.area || to.name,
                  latitude: to.lat,
                  longitude: to.lng
                }
                setFromLocation(fLoc)
                setToLocation(tLoc)
                await executeSearch(fLoc, tLoc)
              }}
              onOfferRideClick={(from, to) => {
                navigate("/rides/create", {
                  state: {
                    fromLocation: from ? {
                      id: from.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                      name: from.name,
                      address: from.area || from.name,
                      latitude: from.lat,
                      longitude: from.lng
                    } : undefined,
                    toLocation: to ? {
                      id: to.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                      name: to.name,
                      address: to.area || to.name,
                      latitude: to.lat,
                      longitude: to.lng
                    } : undefined,
                    date,
                    departureTime
                  }
                })
              }}
            />
          </div>
        )}

        {/* LOADING STATE */}
        {isSearching && (
          <div className="py-16 text-center space-y-3">
            <div className="h-10 w-10 border-4 border-muted border-t-[#25D366] rounded-full animate-spin mx-auto" />
            <p className="text-sm font-semibold text-muted-foreground">Searching for available rides...</p>
          </div>
        )}

        {/* STATE 1: MATCHING RIDES FOUND */}
        {hasSearched && !isSearching && results.length > 0 && (
          <div className="space-y-4 flex-1">
            {/* Lime Banner with Ride Count & Change Route CTA */}
            <div className="bg-[#C5FF00] rounded-[20px] p-3 px-4 flex items-center justify-between shadow-md">
              <div className="flex items-center">
                <span className="text-[40px] font-black text-black leading-none tracking-tight">
                  {results.length}
                </span>
                <div className="h-8 w-[1.5px] bg-black/20 mx-3.5 shrink-0" />
                <div>
                  <p className="text-[16px] font-bold text-black leading-tight">
                    {results.length === 1 ? "ride found" : "rides found"}
                  </p>
                  <p className="text-[12px] font-medium text-black/75 leading-tight mt-0.5">
                    Sorted by shortest walking distance
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setHasSearched(false)}
                className="bg-black text-white rounded-[12px] px-3.5 py-1.5 flex items-center space-x-2 shrink-0 hover:bg-zinc-900 active:scale-95 transition-all cursor-pointer shadow-sm"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-white shrink-0">
                  <path d="M4 8h13M14 5l3 3-3 3M20 16H7M10 13l-3 3 3 3" />
                </svg>
                <div className="flex flex-col text-left leading-[1.1]">
                  <span className="text-[12px] font-bold text-white">Change</span>
                  <span className="text-[12px] font-bold text-white">Route</span>
                </div>
              </button>
            </div>

            {/* Ride List */}
            <div className="space-y-4">
              {results.map((ride, index) => {
                const host = hostProfiles[ride.ownerId] || {
                  name: ride.hostName || "Student Host",
                  department: (ride as any).hostDepartment,
                  year: (ride as any).hostYear,
                  college: (ride as any).hostCollege
                }
                const hostSubtitle = formatBranchYear(host.department || (ride as any).hostDepartment, host.year || (ride as any).hostYear, host.college || "CET")
                const isTopMatch = index === 0 || ride.isClosestMatch

                return (
                  <div
                    key={ride.id}
                    onClick={() => navigate(`/rides/${ride.id}`, {
                      state: {
                        from: "search",
                        fromLocation,
                        toLocation,
                        date,
                        departureTime,
                        seats,
                        pickupDistanceMeters: ride.pickupDistanceMeters,
                        dropoffDistanceMeters: ride.dropoffDistanceMeters,
                        totalDistanceMeters: ride.totalDistanceMeters,
                        proximityBadge: ride.proximityBadge
                      }
                    })}
                    className={`bg-black border-2 rounded-[24px] p-5 shadow-lg transition-all cursor-pointer relative overflow-hidden active:scale-[0.99] ${
                      isTopMatch
                        ? "border-[#C5FF00]"
                        : "border-[#C5FF00]/50 hover:border-[#C5FF00]"
                    }`}
                  >
                    {/* #1 Closest Match Badge */}
                    {isTopMatch && (
                      <div className="bg-[#C5FF00] text-black text-[11px] font-black uppercase tracking-wider px-3.5 py-1.5 rounded-bl-[16px] rounded-tr-[22px] absolute top-0 right-0 flex items-center space-x-1.5 shadow-sm z-10">
                        <Award className="h-3.5 w-3.5 stroke-[2.5]" />
                        <span>#1 CLOSEST MATCH</span>
                      </div>
                    )}

                    {/* Top Row: Host Info & Walking Distance */}
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 pr-2">
                        <h3 className="text-[20px] font-bold text-white truncate leading-tight">
                          {host.name}
                        </h3>
                        <p className="text-[14px] text-zinc-400 font-medium truncate mt-1">
                          {hostSubtitle}
                        </p>
                      </div>

                      {/* Walking Distance */}
                      <div className={`flex items-center space-x-1 shrink-0 ${isTopMatch ? "mt-4" : "mt-0"}`}>
                        <MaterialIcon name="directions_walk" className="text-[#C5FF00] text-[22px] shrink-0" />
                        <span className="text-[#C5FF00] font-bold text-[15px]">
                          {ride.pickupDistanceFormatted || "192 m"}
                        </span>
                        <span className="text-zinc-300 font-normal text-[14px]">away</span>
                      </div>
                    </div>

                    {/* Vertical Timeline Route */}
                    <div className="relative pl-7 py-0.5 space-y-4 mt-6">
                      {/* Dashed Connecting Line */}
                      <div className="absolute left-[6px] top-[14px] bottom-[14px] w-[2px] border-l-2 border-dashed border-zinc-500/80" />

                      {/* Origin Dot & Location */}
                      <div className="relative flex items-center space-x-3">
                        <div className="absolute -left-[28px] top-1 h-3.5 w-3.5 rounded-full bg-[#007AFF] shrink-0" />
                        <span className="text-[16px] font-bold text-white leading-snug truncate">
                          {cleanLocationDisplayName(ride.from)}
                        </span>
                      </div>

                      {/* Destination Dot & Location */}
                      <div className="relative flex items-center space-x-3">
                        <div className="absolute -left-[28px] top-1 h-3.5 w-3.5 rounded-full bg-[#00E676] shrink-0" />
                        <span className="text-[16px] font-bold text-white leading-snug truncate">
                          {cleanLocationDisplayName(ride.to)}
                        </span>
                      </div>
                    </div>

                    {/* Card Footer: Departure Time & Available Seats */}
                    <div className="flex items-center text-white pt-3.5 mt-5 border-t border-zinc-800/80">
                      {/* Departure Time */}
                      <div className="flex items-center space-x-2 flex-1">
                        <Clock className="h-5 w-5 text-[#C5FF00] stroke-[2.2] shrink-0" />
                        <span className="text-[16px] font-bold text-white">
                          {formatTime12h(ride.departureTime) || "12:15 AM"}
                        </span>
                      </div>

                      {/* Middle Vertical Divider */}
                      <div className="h-6 w-[1px] bg-zinc-800 mx-4 shrink-0" />

                      {/* Available Seats */}
                      <div className="flex items-center space-x-2 flex-1 justify-end sm:justify-start">
                        <MaterialIcon name="airline_seat_recline_normal" className="text-[20px] text-white shrink-0" />
                        <span className="text-[14px] font-semibold text-white">
                          {ride.availableSeats} {ride.availableSeats === 1 ? "seat left" : "seats left"}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* STATE 2: NO MATCHING RIDE */}
        {hasSearched && !isSearching && results.length === 0 && (
          <div className="flex-1 flex flex-col justify-between py-6">
            {/* Center Graphic & Text */}
            <div className="text-center py-10 space-y-4 max-w-[280px] mx-auto">
              <div className="h-20 w-20 rounded-full bg-muted border border-border flex items-center justify-center mx-auto text-foreground">
                <MaterialIcon name="search" className="text-[36px] text-muted-foreground" />
              </div>
              <div className="space-y-1">
                <h2 className="text-[20px] font-extrabold text-foreground">No matching rides found</h2>
                <p className="text-[13px] text-muted-foreground leading-relaxed">
                  {departureTime?.trim()
                    ? "Looks like there are no rides for this route at the selected time."
                    : "No upcoming rides found for this route."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setHasSearched(false)}
                className="inline-flex items-center space-x-1.5 px-4 py-2 bg-muted hover:bg-muted/80 border border-border/60 text-foreground text-[13px] font-bold rounded-full transition-colors cursor-pointer"
              >
                <MaterialIcon name="tune" className="text-[16px]" />
                <span>{departureTime?.trim() ? "Adjust Route or Time" : "Adjust Route"}</span>
              </button>
            </div>

            {/* Bottom Offer a Ride Card CTA */}
            <div className="bg-[#D7FF00] dark:bg-[#1A2600] border border-black/10 dark:border-[#C5FF00]/30 rounded-[24px] p-5 text-black dark:text-white space-y-3">
              <div className="flex items-start space-x-3">
                <div className="h-10 w-10 rounded-full bg-black/10 dark:bg-[#C5FF00]/20 flex items-center justify-center shrink-0">
                  <MaterialIcon name="directions_car" className="text-[22px] text-black dark:text-[#C5FF00]" />
                </div>
                <div>
                  <h3 className="text-[15px] font-extrabold text-black dark:text-[#C5FF00]">
                    Be the first to offer a ride!
                  </h3>
                  <p className="text-[12px] text-black/70 dark:text-white/80 leading-snug">
                    Help fellow students and share your ride.
                  </p>
                </div>
              </div>

              <button
                onClick={() => navigate("/rides/create", {
                  state: {
                    fromLocation,
                    toLocation,
                    date,
                    departureTime
                  }
                })}
                className="w-full h-13 bg-black text-white dark:bg-[#C5FF00] dark:text-black rounded-[16px] font-extrabold text-[15px] flex items-center justify-center space-x-2 shadow-sm hover:opacity-90 active:scale-[0.99] transition-all cursor-pointer"
              >
                <span>Offer a Ride</span>
                <MaterialIcon name="arrow_forward" className="text-[18px]" />
              </button>
            </div>
          </div>
        )}
      </div>
    </MobileShell>
  )
}
