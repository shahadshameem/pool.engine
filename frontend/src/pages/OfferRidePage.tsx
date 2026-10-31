import React, { useEffect, useState, useRef } from "react"
import { useNavigate, useLocation } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { rideService } from "../services/ride/rideService"
import { fcmService } from "../services/messaging/fcmService"
import { RouteSelector } from "../components/waymate/RouteSelector"
import { DateTimeFields } from "../components/common/DateTimeFields"
import { getLocalDateString } from "../utils/formatters"
import { useToast } from "../components/feedback/ToastContext"
import type { FixedLocation } from "../config/locations"
import { isDevMockEnabled } from "../utils/devMock"

interface OfferRideFormData {
  date: string
  departureTime: string
  totalSeats: number
  meetingPoint: string
  notes: string
}

export function OfferRidePage() {
  const navigate = useNavigate()
  const { goBack, registerDirtyGuard } = useBackNavigation()
  const location = useLocation()
  const { user, loading: authLoading } = useAuth()
  const { showToast } = useToast()

  const prefillState = location.state as {
    fromLocation?: FixedLocation
    toLocation?: FixedLocation
    date?: string
    departureTime?: string
  } | null

  useEffect(() => {
    if (!authLoading && !user && !isDevMockEnabled()) {
      navigate("/login", { replace: true })
    }
  }, [user, authLoading, navigate])

  const [fromLocation, setFromLocation] = useState<FixedLocation | undefined>(prefillState?.fromLocation)
  const [toLocation, setToLocation] = useState<FixedLocation | undefined>(prefillState?.toLocation)

  const todayStr = getLocalDateString()
  const [formData, setFormData] = useState<OfferRideFormData>({
    date: prefillState?.date || todayStr,
    departureTime: prefillState?.departureTime || "",
    totalSeats: 1,
    meetingPoint: "",
    notes: ""
  })

  const [errors, setErrors] = useState<Partial<Record<keyof OfferRideFormData | 'from' | 'to', string>>>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [createdRideId, setCreatedRideId] = useState<string | null>(null)
  const [isPostedSuccess, setIsPostedSuccess] = useState(false)
  const submittingRef = useRef(false)

  // Register Dirty Form Guard
  useEffect(() => {
    const isFormDirty = () => {
      if (isPostedSuccess) return false
      return Boolean(fromLocation || toLocation || formData.departureTime || formData.notes)
    }
    const unregister = registerDirtyGuard("offer-ride-form", isFormDirty, "You have entered ride details. Discard this offer?")
    return unregister
  }, [fromLocation, toLocation, formData, isPostedSuccess, registerDirtyGuard])

  const validateForm = () => {
    const newErrors: Partial<Record<keyof OfferRideFormData | 'from' | 'to', string>> = {}
    if (!fromLocation?.address) newErrors.from = "Origin is required"
    if (!toLocation?.address) newErrors.to = "Destination is required"
    if (fromLocation && toLocation && fromLocation.id === toLocation.id) {
      newErrors.to = "Choose different origin and destination locations."
    }
    if (!formData.date) newErrors.date = "Date is required"
    if (!formData.departureTime) newErrors.departureTime = "Time is required"

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (isSubmitting || submittingRef.current) return
    if (!validateForm() || !user || !fromLocation || !toLocation) return

    submittingRef.current = true
    setIsSubmitting(true)
    try {
      const cleanLocationPayload = (loc: FixedLocation) => {
        const name = loc.name || loc.address
        const payload: Record<string, any> = {
          name,
          address: loc.address || name,
          latitude: loc.latitude,
          longitude: loc.longitude
        }
        if (loc.matchedZoneId) payload.matchedZoneId = loc.matchedZoneId
        if (loc.rawGps) payload.rawGps = loc.rawGps
        if (loc.isLowAccuracy !== undefined) payload.isLowAccuracy = loc.isLowAccuracy
        if (loc.accuracyMeters !== undefined) payload.accuracyMeters = loc.accuracyMeters
        return payload
      }

      const fromName = fromLocation.name || fromLocation.address
      const toName = toLocation.name || toLocation.address
      const newRideId = await rideService.createRide(user.uid, {
        from: fromName,
        to: toName,
        fromLocation: cleanLocationPayload(fromLocation) as any,
        toLocation: cleanLocationPayload(toLocation) as any,
        date: formData.date,
        departureTime: formData.departureTime,
        totalSeats: formData.totalSeats,
        availableSeats: formData.totalSeats,
        meetingPoint: formData.meetingPoint,
        notes: formData.notes
      })

      if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
        fcmService.requestPermissionAndGetToken(user.uid).catch(console.error)
      }

      setCreatedRideId(newRideId)
      setIsPostedSuccess(true)
    } catch (error: any) {
      console.error("Failed to create ride:", error)
      showToast(error?.message || "Failed to create ride. Please try again.", "error")
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }

  // SCREEN 5: RIDE POSTED SUCCESS STATE
  if (isPostedSuccess) {
    return (
      <MobileShell hideBottomNav className="flex flex-col min-h-screen justify-between p-6 bg-background">
        <div />

        {/* Center Checkmark & Text */}
        <div className="text-center space-y-4 max-w-[300px] mx-auto py-12">
          <div className="h-24 w-24 rounded-full bg-[#E8F8EE] dark:bg-[#182B00] border-2 border-[#25D366] text-[#25D366] dark:text-[#C5FF00] flex items-center justify-center mx-auto shadow-sm">
            <MaterialIcon name="check" className="text-[54px] stroke-[3]" />
          </div>
          <div className="space-y-2">
            <h1 className="text-[26px] font-black text-foreground tracking-tight">Ride Posted!</h1>
            <p className="text-[14px] text-muted-foreground leading-relaxed">
              Your ride has been successfully posted and is now visible to other students.
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="space-y-3 pb-4">
          <button
            onClick={() => navigate(createdRideId ? `/rides/${createdRideId}` : "/rides", { replace: true })}
            className="w-full h-14 bg-[#C5FF00] text-black rounded-[18px] font-extrabold text-[16px] flex items-center justify-center space-x-2 shadow-sm hover:opacity-90 active:scale-[0.99] transition-all cursor-pointer"
          >
            <span>View My Ride</span>
            <MaterialIcon name="arrow_forward" className="text-[18px]" />
          </button>
          <button
            onClick={() => navigate("/home", { replace: true })}
            className="w-full h-14 bg-muted border border-border/60 text-foreground rounded-[18px] font-bold text-[16px] flex items-center justify-center hover:bg-card transition-colors cursor-pointer"
          >
            Back to Home
          </button>
        </div>
      </MobileShell>
    )
  }

  const isOfferLoading = authLoading || !user

  // SCREEN 4: OFFER A RIDE FORM
  return (
    <MobileShell hideBottomNav hasStickyHeader className="flex flex-col min-h-screen bg-background">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 bg-background/95 backdrop-blur border-b border-border/40">
        <button
          onClick={goBack}
          className="h-9 w-9 rounded-full bg-muted flex items-center justify-center text-foreground hover:opacity-80 cursor-pointer"
          aria-label="Back"
        >
          <MaterialIcon name="arrow_back" className="text-[20px]" />
        </button>
        <h1 className="text-[17px] font-extrabold text-foreground">Offer a Ride</h1>
        <div className="w-9" />
      </div>

      {isOfferLoading ? (
        <div className="p-4 space-y-4">
          <div className="h-[200px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4" />
          <div className="h-[120px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4" />
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="p-4 flex-1 space-y-4">
        {/* Route Selector */}
        <RouteSelector
          fromLocation={fromLocation}
          toLocation={toLocation}
          onFromChange={(loc) => { setFromLocation(loc); setErrors(prev => ({...prev, from: "", to: ""})) }}
          onToChange={(loc) => { setToLocation(loc); setErrors(prev => ({...prev, to: "", from: ""})) }}
          error={errors.from || errors.to}
        />

        {/* Date & Time */}
        <DateTimeFields
          date={formData.date}
          time={formData.departureTime}
          onDateChange={(dateStr) => setFormData(prev => ({ ...prev, date: dateStr }))}
          onTimeChange={(timeStr) => setFormData(prev => ({ ...prev, departureTime: timeStr }))}
          dateError={errors.date}
          timeError={errors.departureTime}
          minDate={todayStr}
        />

        {/* Available Seats Stepper */}
        <div className="bg-card border border-border/60 rounded-[18px] p-4 flex items-center justify-between shadow-xs">
          <div className="flex items-center space-x-3">
            <div className="h-9 w-9 rounded-full bg-muted flex items-center justify-center text-muted-foreground">
              <MaterialIcon name="directions_car" className="text-[20px]" />
            </div>
            <div>
              <p className="text-[14px] font-bold text-foreground">Available Seats</p>
              <p className="text-[12px] text-muted-foreground">Seats open for riders</p>
            </div>
          </div>

          <div className="flex items-center space-x-3 bg-muted px-3 py-1.5 rounded-[14px] border border-border/40">
            <button
              type="button"
              onClick={() => setFormData(prev => ({ ...prev, totalSeats: Math.max(1, prev.totalSeats - 1) }))}
              className="h-8 w-8 rounded-full bg-card flex items-center justify-center font-bold text-foreground hover:opacity-80 active:scale-95 transition-all cursor-pointer disabled:opacity-40"
              disabled={formData.totalSeats <= 1}
            >
              -
            </button>
            <span className="text-[15px] font-extrabold text-foreground min-w-[50px] text-center">
              {formData.totalSeats} {formData.totalSeats === 1 ? "seat" : "seats"}
            </span>
            <button
              type="button"
              onClick={() => setFormData(prev => ({ ...prev, totalSeats: Math.min(6, prev.totalSeats + 1) }))}
              className="h-8 w-8 rounded-full bg-card flex items-center justify-center font-bold text-foreground hover:opacity-80 active:scale-95 transition-all cursor-pointer disabled:opacity-40"
              disabled={formData.totalSeats >= 6}
            >
              +
            </button>
          </div>
        </div>

        {/* Additional Notes (Optional) */}
        <div className="bg-card border border-border/60 rounded-[18px] p-4 space-y-2 shadow-xs">
          <div className="flex items-center space-x-2 text-muted-foreground">
            <MaterialIcon name="description" className="text-[18px]" />
            <label className="text-[12px] font-bold uppercase tracking-wider">
              Additional Notes (Optional)
            </label>
          </div>
          <input
            name="notes"
            placeholder="Add a note (e.g. pick-up point, preferences)"
            value={formData.notes}
            onChange={(e) => setFormData(prev => ({ ...prev, notes: e.target.value }))}
            className="w-full text-[14px] text-foreground placeholder:text-muted-foreground/60 focus:outline-none bg-transparent pt-1"
          />
        </div>

        {/* Post Ride Primary CTA */}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full h-14 bg-[#C5FF00] text-black rounded-[18px] font-extrabold text-[16px] flex items-center justify-center space-x-2 shadow-sm hover:opacity-90 active:scale-[0.99] transition-all cursor-pointer mt-4 disabled:opacity-50"
        >
          <MaterialIcon name="directions_car" className="text-[22px]" />
          <span>{isSubmitting ? "Posting Ride..." : "Post Ride"}</span>
        </button>
      </form>
      )}
    </MobileShell>
  )
}
