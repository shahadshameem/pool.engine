import { useState } from "react"
import type { AdminRide } from "../../services/admin/adminService"
import { canForceCancel } from "../../services/admin/adminService"
import { MaterialIcon } from "../common/MaterialIcon"

interface RideDetailModalProps {
  ride: AdminRide | null
  onClose: () => void
  onCancelRide: (rideId: string, reason: string) => Promise<boolean> | void
  onMarkCompleted: (rideId: string) => Promise<boolean> | void
}

export function RideDetailModal({
  ride,
  onClose,
  onCancelRide,
  onMarkCompleted
}: RideDetailModalProps) {
  const [showCancelPrompt, setShowCancelPrompt] = useState(false)
  const [cancelReason, setCancelReason] = useState("")
  const [isSubmittingCancel, setIsSubmittingCancel] = useState(false)

  if (!ride) return null

  const handleCancelSubmit = async () => {
    if (!cancelReason.trim() || isSubmittingCancel) return
    setIsSubmittingCancel(true)
    try {
      const res = await onCancelRide(ride.id, cancelReason)
      if (res !== false) {
        setShowCancelPrompt(false)
        onClose()
      }
    } catch {
      // Keep prompt open and let error toast show
    } finally {
      setIsSubmittingCancel(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div
        className="w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-black/10 overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 bg-gradient-to-r from-gray-900 to-black text-white relative">
          <button
            onClick={onClose}
            className="absolute top-5 right-5 text-gray-400 hover:text-white transition-colors"
          >
            <MaterialIcon name="close" className="text-xl" />
          </button>

          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
              ride.status === "cancelled" ? "bg-red-400 text-black" :
              ride.status === "active" ? "bg-green-400 text-black" :
              ride.status === "full" ? "bg-amber-400 text-black" :
              ride.status === "completed" ? "bg-blue-400 text-black" :
              "bg-gray-400 text-black"
            }`}>
              {ride.status.toUpperCase()}
            </span>

            {(ride.genderPolicy === "female_only" || ride.genderPolicy === "female") && (
              <span className="text-xs bg-white/20 text-white px-2 py-0.5 rounded-full capitalize">
                Female Only
              </span>
            )}
          </div>

          <h2 className="text-xl font-bold">{ride.from} → {ride.to}</h2>
          <p className="text-xs text-gray-300 mt-1 flex items-center gap-3">
            <span className="flex items-center gap-1">
              <MaterialIcon name="calendar_today" className="text-sm" />
              {ride.date}
            </span>
            <span className="flex items-center gap-1">
              <MaterialIcon name="schedule" className="text-sm" />
              {ride.departureTime}
            </span>
          </p>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Host Card */}
          <div className="bg-gray-50 p-4 rounded-xl border border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-black text-white font-bold text-sm flex items-center justify-center">
                {ride.hostName ? ride.hostName.charAt(0) : "H"}
              </div>
              <div>
                <p className="text-xs text-gray-500 font-medium">Host / Driver</p>
                <p className="font-semibold text-gray-900">{ride.hostName || "Host Student"}</p>
                <p className="text-xs text-gray-500">{ride.hostDepartment} • {ride.hostCollege || "CET"}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">Seats</p>
              <p className="text-sm font-bold text-gray-900">
                {ride.availableSeats} / {ride.totalSeats} free
              </p>
            </div>
          </div>

          {/* Additional details */}
          {(ride.vehicleType || ride.notes) && (
            <div className="space-y-2 text-sm bg-gray-50 p-4 rounded-xl border border-gray-100">
              {ride.vehicleType && (
                <p className="text-gray-700">
                  <span className="font-medium text-gray-900">Vehicle: </span>
                  {ride.vehicleType}
                </p>
              )}
              {ride.notes && (
                <p className="text-gray-700">
                  <span className="font-medium text-gray-900">Driver Notes: </span>
                  {ride.notes}
                </p>
              )}
            </div>
          )}

          {/* Passenger Roster */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                Confirmed Passengers ({ride.acceptedPassengers?.length || 0})
              </h3>
            </div>

            {ride.acceptedPassengers && ride.acceptedPassengers.length > 0 ? (
              <div className="space-y-2">
                {ride.acceptedPassengers.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-gray-50 border border-gray-100 text-sm">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-full bg-[#C5FF00] text-black font-bold text-xs flex items-center justify-center">
                        {p.name.charAt(0)}
                      </div>
                      <div>
                        <p className="font-medium text-gray-900">{p.name}</p>
                        <p className="text-xs text-gray-500">{p.department || "Student"}</p>
                      </div>
                    </div>
                    <span className="text-[11px] font-semibold text-green-700 bg-green-50 px-2 py-0.5 rounded-full border border-green-200">
                      Confirmed
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-4 bg-gray-50 rounded-xl border border-gray-100 text-xs text-gray-500">
                No passengers accepted yet
              </div>
            )}
          </div>

          {/* Cancel Prompt Inline */}
          {showCancelPrompt && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-xl space-y-3 animate-in fade-in duration-150">
              <div className="flex items-center gap-2 text-red-900 font-semibold text-xs uppercase tracking-wider">
                <MaterialIcon name="warning" className="text-base text-red-600" />
                Administrative Cancellation Reason
              </div>
              <textarea
                value={cancelReason}
                onChange={e => setCancelReason(e.target.value)}
                placeholder="Explain why this ride is being cancelled (e.g. policy violation, safety report, improper route)..."
                rows={2}
                className="w-full text-xs p-2.5 bg-white rounded-lg border border-red-200 focus:outline-none focus:ring-1 focus:ring-red-500"
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setShowCancelPrompt(false)}
                  className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-900 font-medium"
                >
                  Back
                </button>
                <button
                  onClick={handleCancelSubmit}
                  disabled={!cancelReason.trim() || isSubmittingCancel}
                  className="px-4 py-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 cursor-pointer disabled:cursor-not-allowed"
                >
                  {isSubmittingCancel ? (
                    <>
                      <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      <span>Cancelling...</span>
                    </>
                  ) : (
                    <span>Confirm Force Cancel</span>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Administrative Actions */}
          {ride.status !== "cancelled" && !showCancelPrompt && (
            <div className="space-y-3 pt-2 border-t border-gray-100">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Admin Actions</h3>
              <div className="grid grid-cols-2 gap-2.5">
                {ride.status !== "completed" && (
                  <button
                    onClick={() => onMarkCompleted(ride.id)}
                    className="py-2.5 px-3 rounded-xl text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-900 flex items-center justify-center gap-1.5 transition-all"
                  >
                    <MaterialIcon name="check_circle" className="text-base" />
                    Mark Completed
                  </button>
                )}

                <button
                  onClick={() => canForceCancel(ride.status) && setShowCancelPrompt(true)}
                  disabled={!canForceCancel(ride.status)}
                  title={!canForceCancel(ride.status) ? "Completed rides cannot be cancelled" : "Force cancel ride"}
                  className={`py-2.5 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all ${
                    canForceCancel(ride.status)
                      ? "bg-red-50 hover:bg-red-100 text-red-800 border border-red-200 cursor-pointer"
                      : "bg-gray-100 text-gray-400 border border-gray-200 cursor-not-allowed opacity-60"
                  }`}
                >
                  <MaterialIcon name="block" className="text-base" />
                  <span>Force Cancel Ride</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 bg-gray-50 border-t border-gray-100 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-gray-900 hover:bg-black text-white text-xs font-semibold transition-all"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
