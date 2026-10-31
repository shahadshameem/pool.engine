import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { collection, query, where, onSnapshot, doc, getDoc, updateDoc } from "firebase/firestore"
import { db } from "../config/firebase"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { StatusBadge } from "../components/common/StatusBadge"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { formatDate, formatTime12h } from "../utils/formatters"
import { isRideExpired, parseTimeToMinutes } from "../config/matchingConfig"
import { isDevMockEnabled } from "../utils/devMock"

interface TripItem {
  id: string
  rideId: string
  from: string
  to: string
  date: string
  departureTime: string
  status: string
  role: "host" | "passenger"
  availableSeats?: number
}

/**
 * Accurately parses ISO ("YYYY-MM-DD") or Indian ("DD-MM-YYYY") date string
 * combined with any time format (24h or 12h AM/PM) into epoch milliseconds.
 */
function getRideTimestamp(dateStr?: string, timeStr?: string): number {
  if (!dateStr) return 0
  try {
    let year: number
    let month: number
    let day: number

    const isoMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/)
    const ddmmyyyyMatch = dateStr.match(/^(\d{2})-(\d{2})-(\d{4})/)

    if (isoMatch) {
      year = parseInt(isoMatch[1], 10)
      month = parseInt(isoMatch[2], 10) - 1
      day = parseInt(isoMatch[3], 10)
    } else if (ddmmyyyyMatch) {
      day = parseInt(ddmmyyyyMatch[1], 10)
      month = parseInt(ddmmyyyyMatch[2], 10) - 1
      year = parseInt(ddmmyyyyMatch[3], 10)
    } else {
      const parsedDate = new Date(dateStr)
      if (isNaN(parsedDate.getTime())) return 0
      year = parsedDate.getFullYear()
      month = parsedDate.getMonth()
      day = parsedDate.getDate()
    }

    const departureMinutes = parseTimeToMinutes(timeStr)
    const hours = Math.floor(departureMinutes / 60)
    const minutes = departureMinutes % 60

    return new Date(year, month, day, hours, minutes, 0, 0).getTime()
  } catch {
    return 0
  }
}

export function MyRidesPage() {
  const navigate = useNavigate()
  const { goBack } = useBackNavigation()
  const { user, loading: authLoading } = useAuth()

  const [isLoading, setIsLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<"upcoming" | "past">("upcoming")
  const [upcomingTrips, setUpcomingTrips] = useState<TripItem[]>([])
  const [pastTrips, setPastTrips] = useState<TripItem[]>([])

  const isMockMode = isDevMockEnabled()

  useEffect(() => {
    if (isMockMode) return
    if (!authLoading && !user) {
      navigate("/login", { replace: true })
    }
  }, [user, authLoading, navigate, isMockMode])

  useEffect(() => {
    if (isMockMode) {
      setUpcomingTrips([
        {
          id: "mock-joined-1",
          rideId: "mock-ride-1",
          from: "CET",
          to: "TVM Central",
          date: "2026-09-30",
          departureTime: "09:00",
          status: "accepted",
          role: "passenger",
          availableSeats: 2
        },
        {
          id: "mock-pending-1",
          rideId: "mock-ride-3",
          from: "CET",
          to: "Kazhakkoottam",
          date: "2026-10-01",
          departureTime: "11:00",
          status: "pending",
          role: "passenger",
          availableSeats: 1
        },
        {
          id: "mock-hosted-1",
          rideId: "mock-ride-2",
          from: "CET",
          to: "Kottayam",
          date: "2026-10-02",
          departureTime: "10:00",
          status: "active",
          role: "host",
          availableSeats: 3
        }
      ])
      setPastTrips([
        {
          id: "mock-past-1",
          rideId: "mock-ride-4",
          from: "Kollam",
          to: "CET",
          date: "2026-09-25",
          departureTime: "08:30",
          status: "completed",
          role: "host",
          availableSeats: 0
        },
        {
          id: "mock-past-2",
          rideId: "mock-ride-5",
          from: "CET",
          to: "Airport",
          date: "2026-09-24",
          departureTime: "16:00",
          status: "rejected",
          role: "passenger",
          availableSeats: 2
        }
      ])
      setIsLoading(false)
      return
    }

    if (!user) {
      setUpcomingTrips([])
      setPastTrips([])
      setIsLoading(false)
      return
    }

    const hostMap = new Map<string, TripItem>()
    const passengerMap = new Map<string, TripItem>()
    let hostLoaded = false
    let passengerLoaded = false

    const updateMergedTrips = () => {
      const allHosted = Array.from(hostMap.values())
      const allJoined = Array.from(passengerMap.values())

      // Deduplicate identical hosted rides
      const seenHostedKeys = new Set<string>()
      const uniqueHosted = allHosted.filter(t => {
        if (t.status === "active" || t.status === "full") {
          const key = `${t.date}_${t.departureTime}_${t.from}_${t.to}`
          if (seenHostedKeys.has(key)) {
            return false
          }
          seenHostedKeys.add(key)
        }
        return true
      })

      const allTrips = [...uniqueHosted, ...allJoined]

      // A trip belongs to Past if cancelled, declined/rejected, completed, or departure has expired
      const isTripPast = (t: TripItem) => {
        return (
          t.status === "cancelled" ||
          t.status === "rejected" ||
          t.status === "completed" ||
          isRideExpired(t.date, t.departureTime, t.status)
        )
      }

      const upcoming = allTrips.filter(t => !isTripPast(t))
      const past = allTrips.filter(t => isTripPast(t))

      // Chronological numeric timestamp sorting
      upcoming.sort((a, b) => getRideTimestamp(a.date, a.departureTime) - getRideTimestamp(b.date, b.departureTime))
      past.sort((a, b) => getRideTimestamp(b.date, b.departureTime) - getRideTimestamp(a.date, a.departureTime))

      setUpcomingTrips(upcoming)
      setPastTrips(past)
      if (hostLoaded && passengerLoaded) {
        setIsLoading(false)
      }
    }

    // 1. Host query: listen to all rides owned by current user
    const qHost = query(collection(db, "rides"), where("ownerId", "==", user.uid))
    const unsubHost = onSnapshot(qHost, (snap) => {
      hostMap.clear()
      snap.docs.forEach(d => {
        const data = d.data()
        const isCancelled = data.status === "cancelled"
        const expired = !isCancelled && isRideExpired(data.date, data.departureTime, data.status)
        if (expired && (data.status === "active" || data.status === "full" || data.status === "started")) {
          updateDoc(doc(db, "rides", d.id), { status: "completed" }).catch(console.error)
        }
        hostMap.set(d.id, {
          id: d.id,
          rideId: d.id,
          from: data.from,
          to: data.to,
          date: data.date,
          departureTime: data.departureTime,
          status: isCancelled ? "cancelled" : (expired ? "completed" : data.status),
          role: "host",
          availableSeats: data.availableSeats
        })
      })
      hostLoaded = true
      updateMergedTrips()
    }, (err) => {
      console.error("Host rides error:", err)
      hostLoaded = true
      setIsLoading(false)
    })

    // 2. Passenger query: listen to ALL ride requests by current user (pending, accepted, rejected, cancelled)
    const qPassenger = query(
      collection(db, "rideRequests"),
      where("requesterId", "==", user.uid)
    )
    const unsubPassenger = onSnapshot(qPassenger, async (snap) => {
      const reqDocs = snap.docs.map(d => ({ id: d.id, ...d.data() })) as any[]

      // Group requests by rideId
      const requestsByRide = new Map<string, any[]>()
      reqDocs.forEach(req => {
        if (!req.rideId) return
        const list = requestsByRide.get(req.rideId) || []
        list.push(req)
        requestsByRide.set(req.rideId, list)
      })

      const uniqueRideIds = Array.from(requestsByRide.keys())
      const newPassengerMap = new Map<string, TripItem>()

      if (uniqueRideIds.length > 0) {
        await Promise.all(
          uniqueRideIds.map(async (rId) => {
            try {
              const rideSnap = await getDoc(doc(db, "rides", rId))
              if (rideSnap.exists()) {
                const rideData = rideSnap.data()
                const reqsForRide = requestsByRide.get(rId) || []

                // Rank: accepted (4) > pending (3) > cancelled (2) > rejected (1)
                const statusRank: Record<string, number> = {
                  accepted: 4,
                  pending: 3,
                  cancelled: 2,
                  rejected: 1
                }
                reqsForRide.sort((a, b) => {
                  const rankA = statusRank[a.status] || 0
                  const rankB = statusRank[b.status] || 0
                  if (rankA !== rankB) return rankB - rankA
                  const timeA = a.updatedAt?.seconds || a.createdAt?.seconds || 0
                  const timeB = b.updatedAt?.seconds || b.createdAt?.seconds || 0
                  return timeB - timeA
                })

                const bestReq = reqsForRide[0]
                const reqStatus = bestReq?.status || "pending"

                const isCancelled = rideData.status === "cancelled" || reqStatus === "cancelled"
                const isRejected = !isCancelled && reqStatus === "rejected"
                const isExpired = !isCancelled && !isRejected && (rideData.status === "completed" || isRideExpired(rideData.date, rideData.departureTime, rideData.status))

                let tripStatus = "accepted"
                if (isCancelled) {
                  tripStatus = "cancelled"
                } else if (isRejected) {
                  tripStatus = "rejected"
                } else if (isExpired) {
                  tripStatus = "completed"
                } else if (reqStatus === "pending") {
                  tripStatus = "pending"
                } else if (rideData.status === "started") {
                  tripStatus = "started"
                } else {
                  tripStatus = "accepted"
                }

                newPassengerMap.set(rId, {
                  id: rId,
                  rideId: rId,
                  from: rideData.from,
                  to: rideData.to,
                  date: rideData.date,
                  departureTime: rideData.departureTime,
                  status: tripStatus,
                  role: "passenger",
                  availableSeats: rideData.availableSeats
                })
              }
            } catch (e) {
              console.error("Error fetching passenger trip:", e)
            }
          })
        )
      }

      passengerMap.clear()
      newPassengerMap.forEach((val, key) => passengerMap.set(key, val))
      passengerLoaded = true
      updateMergedTrips()
    }, (err) => {
      console.error("Passenger trips error:", err)
      passengerLoaded = true
      setIsLoading(false)
    })

    return () => {
      unsubHost()
      unsubPassenger()
    }
  }, [user, isMockMode])

  const isTripsLoading = authLoading || (isLoading && upcomingTrips.length === 0 && pastTrips.length === 0)
  const currentList = activeTab === "upcoming" ? upcomingTrips : pastTrips

  return (
    <MobileShell className="flex flex-col space-y-5">
      {/* Header */}
      <div className="flex items-center space-x-2">
        <button
          onClick={goBack}
          className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
          aria-label="Back to Home"
        >
          <MaterialIcon name="arrow_back" className="text-[24px] text-foreground" />
        </button>
        <h1 className="text-edex-section text-foreground font-bold">My Trips</h1>
      </div>

      {/* Segmented Control (Upcoming vs Past) */}
      <div className="bg-muted p-1.5 rounded-full grid grid-cols-2 gap-1 border border-border/40 shadow-xs">
        <button
          onClick={() => setActiveTab("upcoming")}
          className={`py-2.5 text-center text-[15px] rounded-full transition-all cursor-pointer ${
            activeTab === "upcoming"
              ? "bg-[#C5FF00] text-black font-extrabold shadow-sm"
              : "text-muted-foreground hover:text-foreground font-semibold"
          }`}
        >
          Upcoming
        </button>
        <button
          onClick={() => setActiveTab("past")}
          className={`py-2.5 text-center text-[15px] rounded-full transition-all cursor-pointer ${
            activeTab === "past"
              ? "bg-[#C5FF00] text-black font-extrabold shadow-sm"
              : "text-muted-foreground hover:text-foreground font-semibold"
          }`}
        >
          Past
        </button>
      </div>

      {/* Trip Cards */}
      <div className="space-y-3 pt-1">
        {isTripsLoading ? (
          <>
            <div className="h-[80px] w-full bg-card border border-border/60 rounded-[22px] animate-pulse p-4 flex items-center space-x-3.5">
              <div className="h-11 w-11 rounded-full bg-muted shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-4 w-3/4 bg-muted rounded-md" />
                <div className="h-3 w-1/2 bg-muted/60 rounded-md" />
              </div>
            </div>
            <div className="h-[80px] w-full bg-card border border-border/60 rounded-[22px] animate-pulse p-4 flex items-center space-x-3.5">
              <div className="h-11 w-11 rounded-full bg-muted shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-4 w-2/3 bg-muted rounded-md" />
                <div className="h-3 w-1/3 bg-muted/60 rounded-md" />
              </div>
            </div>
          </>
        ) : currentList.length === 0 ? (
          <div className="bg-card border border-border/60 rounded-[28px] p-8 sm:p-10 text-center space-y-5 shadow-xs">
            <p className="text-[15px] text-muted-foreground font-medium tracking-wide">
              {activeTab === "upcoming" ? "No upcoming trips scheduled." : "No past trip history."}
            </p>
            <div className="flex items-center justify-center pt-1">
              <button
                onClick={() => navigate("/rides/search")}
                className="px-6 py-2.5 rounded-full bg-[#C5FF00] text-black text-[14px] font-extrabold hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer shadow-sm"
              >
                Find a ride
              </button>
            </div>
          </div>
        ) : (
          currentList.map((trip) => {
            const initial = trip.from ? trip.from.charAt(0).toUpperCase() : "A"
            return (
              <div
                key={trip.id}
                onClick={() => navigate(`/rides/${trip.rideId}`, { state: { from: "my-rides" } })}
                className="bg-card border border-border/60 rounded-[22px] p-4 flex items-center justify-between cursor-pointer hover:border-[#C5FF00] transition-all shadow-xs"
              >
                <div className="flex items-center space-x-3.5 min-w-0 flex-1">
                  {/* Initial Avatar */}
                  <div className="h-11 w-11 rounded-full bg-muted flex items-center justify-center font-bold text-[18px] text-foreground shrink-0">
                    {initial}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="font-bold text-[16px] text-foreground truncate">
                      {trip.from} → {trip.to}
                    </div>

                    <div className="flex items-center space-x-2 text-[13px] text-muted-foreground mt-0.5">
                      <MaterialIcon name="calendar_today" className="text-[14px]" />
                      <span>{formatDate(trip.date)} • {formatTime12h(trip.departureTime)}</span>
                    </div>

                    <div className="mt-2">
                      <StatusBadge
                        status={
                          trip.status === "cancelled"
                            ? "cancelled"
                            : trip.status === "rejected"
                            ? "declined"
                            : trip.status === "started"
                            ? "started"
                            : trip.status === "completed" || isRideExpired(trip.date, trip.departureTime, trip.status)
                            ? "completed"
                            : trip.status === "pending"
                            ? "requested"
                            : trip.role === "host"
                            ? "hosting"
                            : "joined"
                        }
                      />
                    </div>
                  </div>
                </div>

                <MaterialIcon name="chevron_right" className="text-[24px] text-muted-foreground/60 ml-2" />
              </div>
            )
          })
        )}
      </div>
    </MobileShell>
  )
}
