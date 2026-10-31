import React, { useEffect, useState } from "react"
import { useNavigate, useLocation } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { RouteSelector } from "../components/waymate/RouteSelector"
import { DateTimeFields } from "../components/common/DateTimeFields"
import { CampusBroadcastBanner } from "../components/common/CampusBroadcastBanner"
import { useAuth } from "../hooks/useAuth"
import type { FixedLocation } from "../config/locations"
import { getLocalDateString } from "../utils/formatters"
import { isDevMockEnabled } from "../utils/devMock"
import { useSEO } from "../hooks/useSEO"

export function HomePage() {
  useSEO({
    title: "Campus Rideshare Dashboard",
    description: "Search and offer verified rides, share cab fares, and commute with college peers on WayMate (wmate.app).",
    canonicalPath: "/home",
  })

  const navigate = useNavigate()
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
  const [formData, setFormData] = useState({
    date: (navState?.date && navState.date >= todayStr) ? navState.date : todayStr,
    departureTime: navState?.departureTime || "",
    seats: navState?.seats || 1
  })
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (navState) {
      if (navState.fromLocation) setFromLocation(navState.fromLocation)
      if (navState.toLocation) setToLocation(navState.toLocation)
      setFormData(prev => ({
        ...prev,
        date: (navState.date && navState.date >= todayStr) ? navState.date : (prev.date >= todayStr ? prev.date : todayStr),
        departureTime: navState.departureTime ?? prev.departureTime,
        seats: navState.seats ?? prev.seats
      }))
    }
  }, [location.state, location.key])

  useEffect(() => {
    if (!authLoading && !user && !isDevMockEnabled()) {
      navigate("/login", { replace: true })
      return
    }

    if (user && profile) {
      const isIncomplete =
        !profile.department ||
        !profile.year ||
        !profile.gender ||
        (profile.gender as string) === "other" ||
        !profile.phone ||
        profile.phone === "0000000000"

      if (isIncomplete) {
        navigate("/onboarding", { replace: true })
      }
    }
  }, [user, profile, authLoading, navigate])

  const resolvedName = (profile?.name && profile.name !== "Student" && profile.name !== "User")
    ? profile.name
    : (user?.displayName || profile?.name || "U")
  const userInitials = resolvedName.trim().charAt(0).toUpperCase() || "U"

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!fromLocation) newErrors.from = "Select departure location"
    if (!toLocation) newErrors.to = "Select destination"
    if (fromLocation && toLocation && fromLocation.id === toLocation.id) {
      newErrors.to = "Origin and destination cannot be the same"
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleFindRides = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    navigate("/rides/search", {
      state: {
        fromLocation,
        toLocation,
        date: formData.date,
        departureTime: formData.departureTime,
        seats: formData.seats
      }
    })
  }

  return (
    <MobileShell className="flex flex-col space-y-4 sm:space-y-5">
      {/* 1. TOP APP BAR */}
      <div className="flex items-center justify-between px-1 shrink-0">
        <h1 className="text-[22px] font-black tracking-tight text-foreground">
          WayMate
        </h1>
        <button
          onClick={() => navigate("/profile")}
          className="h-10 w-10 rounded-full bg-muted border border-border/40 flex items-center justify-center font-bold text-foreground hover:opacity-80 transition-colors cursor-pointer"
          aria-label="Profile"
        >
          {userInitials}
        </button>
      </div>

      {/* ACTIVE CAMPUS BROADCAST ADVISORY */}
      <CampusBroadcastBanner />

      {/* 2. MINIMAL EDEX HERO CARD */}
      <div className="w-full bg-[#C5FF00] rounded-[24px] p-5 text-black relative overflow-hidden shadow-xs border border-black/10 shrink-0 min-h-[128px]">
        <div className="space-y-1 max-w-[220px] relative z-10">
          <span className="text-[10px] font-extrabold tracking-widest uppercase text-black/70">
            TRAVEL TOGETHER
          </span>
          <h2 className="text-[24px] font-black leading-tight pt-0.5 text-black [text-wrap:balance]">
            Go Further.
          </h2>
          <p className="text-[12px] text-black/80 pt-1 font-medium leading-snug [text-wrap:pretty]">
            Find rides with students near you.
          </p>
        </div>

        {/* Minimal Decorative Route Dots Vector */}
        <div className="absolute right-4 top-1/2 -translate-y-1/2 opacity-80 pointer-events-none select-none">
          <svg width="80" height="80" viewBox="0 0 100 100" fill="none" aria-hidden="true">
            <path d="M 15 20 Q 75 20 75 50 T 15 80" stroke="currentColor" strokeWidth="3" strokeDasharray="4 4" className="text-black" fill="none" />
            <circle cx="15" cy="20" r="5" className="fill-black" />
            <circle cx="15" cy="80" r="5" className="fill-black" />
          </svg>
        </div>
      </div>

      {/* 3. FIND YOUR RIDE FORM */}
      <div className="bg-card border border-border/60 rounded-[24px] p-5 shadow-sm space-y-4 shrink-0">
        <h2 className="text-[18px] font-extrabold text-foreground tracking-tight [text-wrap:balance]">
          Find your ride
        </h2>

        <form onSubmit={handleFindRides} className="space-y-4">
          <RouteSelector
            fromLocation={fromLocation}
            toLocation={toLocation}
            onFromChange={(loc) => {
              setFromLocation(loc)
              if (errors.from) setErrors(prev => ({ ...prev, from: "" }))
            }}
            onToChange={(loc) => {
              setToLocation(loc)
              if (errors.to) setErrors(prev => ({ ...prev, to: "" }))
            }}
            error={errors.from || errors.to}
          />
          {(errors.from || errors.to) && (
            <p className="text-xs text-destructive font-medium px-1">
              {errors.from || errors.to}
            </p>
          )}

          <DateTimeFields
            date={formData.date}
            time={formData.departureTime}
            seats={formData.seats}
            minDate={todayStr}
            onDateChange={(date) => setFormData(prev => ({ ...prev, date }))}
            onTimeChange={(time) => setFormData(prev => ({ ...prev, departureTime: time }))}
            onSeatsChange={(seats) => setFormData(prev => ({ ...prev, seats }))}
          />

          <button
            type="submit"
            className="w-full h-14 bg-[#C5FF00] text-black rounded-[18px] font-extrabold text-[16px] tracking-tight flex items-center justify-center space-x-2 shadow-sm hover:opacity-95 active:scale-[0.98] transition-transform transition-opacity duration-150 cursor-pointer mt-2"
          >
            <MaterialIcon name="search" className="text-[22px]" />
            <span>Find Rides</span>
          </button>
        </form>
      </div>

    </MobileShell>
  )
}