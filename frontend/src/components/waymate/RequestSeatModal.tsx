import { useState, useEffect } from "react"
import { Check, Calendar, UserPlus } from "lucide-react"
import { ModalShell } from "../common/ModalShell"
import { SeatStepper } from "../common/SeatStepper"
import { formatDate, formatTime12h } from "../../utils/formatters"
import { useAuth } from "../../hooks/useAuth"
import { rideRequestService } from "../../services/rideRequest/rideRequestService"
import { fcmService } from "../../services/messaging/fcmService"
import { useToast } from "../feedback/ToastContext"

interface RequestSeatModalProps {
  isOpen: boolean
  onClose: () => void
  ride: any | null
  onSuccess?: (hostName: string) => void
}

export function RequestSeatModal({
  isOpen,
  onClose,
  ride,
  onSuccess
}: RequestSeatModalProps) {
  const { user } = useAuth()
  const { showToast } = useToast()
  const [requestSeats, setRequestSeats] = useState(1)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSubmittedSuccess, setIsSubmittedSuccess] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setRequestSeats(1)
      setIsSubmitting(false)
      setIsSubmittedSuccess(false)
    }
  }, [isOpen])

  const handleFinish = () => {
    onClose()
    if (onSuccess && ride) {
      onSuccess(ride.hostName || "the host")
    }
  }

  useEffect(() => {
    if (isSubmittedSuccess) {
      const timer = setTimeout(() => {
        handleFinish()
      }, 1800)
      return () => clearTimeout(timer)
    }
  }, [isSubmittedSuccess])

  if (!isOpen || !ride) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user || !ride) return
    setIsSubmitting(true)

    try {
      const result = await rideRequestService.createRideRequest(
        {
          id: ride.id,
          ownerId: ride.ownerId,
          status: ride.status,
          availableSeats: ride.availableSeats,
          from: ride.from,
          to: ride.to,
          date: ride.date,
          departureTime: ride.departureTime,
          genderPolicy: ride.genderPolicy
        },
        user.uid,
        requestSeats
      )

      if (!result.success) {
        showToast(result.message, "error")
        setIsSubmitting(false)
        return
      }

      if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
        fcmService.requestPermissionAndGetToken(user.uid).catch(console.error)
      }

      setIsSubmitting(false)
      setIsSubmittedSuccess(true)
    } catch (err: any) {
      console.error("Request submission error:", err)
      showToast("Failed to send request. Please try again.", "error")
      setIsSubmitting(false)
    }
  }

  if (isSubmittedSuccess) {
    const hostName = ride.hostName || "the host"
    return (
      <ModalShell isOpen={isOpen} onClose={handleFinish} title="Request Sent">
        <div className="flex flex-col items-center py-4 text-center space-y-4">
          <div className="my-2 flex h-20 w-20 items-center justify-center rounded-full bg-[#C5FF00] text-black shadow-lg animate-in zoom-in duration-300">
            <Check className="h-10 w-10 stroke-[3]" />
          </div>

          <div className="space-y-1">
            <h2 className="text-[22px] font-bold tracking-tight text-foreground">
              Request sent!
            </h2>
            <p className="text-[14px] font-normal text-muted-foreground max-w-[280px] leading-snug mx-auto">
              Waiting for <span className="font-semibold text-foreground">{hostName}</span> to accept your request.
            </p>
          </div>

          <button
            type="button"
            onClick={handleFinish}
            className="w-full h-12 bg-[#C5FF00] text-black font-extrabold text-[16px] rounded-full hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer mt-2 shadow-xs"
          >
            Done
          </button>
        </div>
      </ModalShell>
    )
  }

  const formattedDate = formatDate(ride.date)
  const formattedTime = formatTime12h(ride.departureTime)
  const subtextParts = [
    ride.college || "CET",
    [ride.year, ride.department].filter(Boolean).join(" ") || "ECE"
  ].filter(Boolean).join(" • ")

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title="Request Seat">
      <div className="space-y-4 pt-1">

        {/* 1. ROUTE & TRIP INFO BOX */}
        <div className="bg-card border border-border/60 rounded-[18px] p-4 space-y-3.5 shadow-xs">
          <div className="flex items-stretch space-x-3.5">
            <div className="relative flex flex-col items-center shrink-0 w-3.5 self-stretch my-1">
              <div className="w-3.5 h-3.5 rounded-full bg-[#3B82F6] ring-2 ring-[#3B82F6]/30 shrink-0 z-10" />
              <div className="w-[2px] flex-1 border-l-2 border-dashed border-foreground/30 dark:border-white/40 my-1" />
              <div className="w-3.5 h-3.5 rounded-full bg-[#25D366] ring-2 ring-[#25D366]/30 shrink-0 z-10" />
            </div>

            <div className="flex flex-col justify-between space-y-3.5 min-w-0 flex-1 py-0.5">
              <div className="text-[17px] sm:text-[18px] font-semibold text-foreground leading-tight truncate">
                {ride.from}
              </div>
              <div className="text-[17px] sm:text-[18px] font-semibold text-foreground leading-tight">
                {ride.to}
              </div>
            </div>
          </div>

          <div className="bg-muted border border-border/40 rounded-[14px] p-3 flex items-center justify-between gap-2">
            <div className="flex items-center space-x-2.5 min-w-0">
              <Calendar className="h-4.5 w-4.5 text-foreground shrink-0 stroke-[2.2]" />
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-foreground truncate leading-tight">
                  {formattedDate}
                </div>
                <div className="text-[12px] font-normal text-muted-foreground truncate mt-0.5">
                  {formattedTime}
                </div>
              </div>
            </div>

            <div className="bg-card border border-border/60 text-foreground px-3.5 py-1.5 rounded-[980px] text-[12px] font-semibold flex items-center space-x-1.5 shrink-0">
              <UserPlus className="h-4 w-4 text-foreground stroke-[2.5]" />
              <span>{ride.availableSeats} {ride.availableSeats === 1 ? "seat" : "seats"} available</span>
            </div>
          </div>
        </div>

        {/* 2. HOST INFO BOX */}
        <div className="bg-card border border-border/60 rounded-[18px] p-4 space-y-1 shadow-xs">
          <span className="text-[12px] font-normal text-muted-foreground block">Hosted by</span>
          <h3 className="text-[16px] font-semibold text-foreground truncate leading-tight">
            {ride.hostName || "Host"}
          </h3>
          <p className="text-[13px] font-normal text-muted-foreground truncate">
            {subtextParts}
          </p>
        </div>

        {/* 3. NO. OF SEATS STEPPER */}
        <div className="space-y-2">
          <label className="text-[14px] font-semibold text-foreground block">No. of seats</label>
          <SeatStepper
            value={requestSeats}
            onChange={setRequestSeats}
            max={ride.availableSeats}
            disabled={isSubmitting}
          />
        </div>

        {/* 4. SUBMIT BUTTON */}
        <button
          onClick={handleSubmit}
          disabled={isSubmitting}
          className="w-full h-12 bg-[#C5FF00] text-black font-extrabold text-[16px] rounded-full hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-50 shadow-xs flex items-center justify-center space-x-2 cursor-pointer"
        >
          <UserPlus className="h-5 w-5 stroke-[2.5]" />
          <span>{isSubmitting ? "Sending Request..." : "Send Request"}</span>
        </button>

      </div>
    </ModalShell>
  )
}
