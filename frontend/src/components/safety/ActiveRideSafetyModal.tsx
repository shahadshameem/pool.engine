import React, { useState } from "react"
import { ModalShell } from "../common/ModalShell"
import { Button } from "../ui/button"
import { MaterialIcon } from "../common/MaterialIcon"
import { blockService } from "../../services/safety/blockService"
import { useToast } from "../feedback/ToastContext"
import { ReportUserModal } from "./ReportUserModal"

interface ActiveRideSafetyModalProps {
  isOpen: boolean
  onClose: () => void
  currentUserId: string
  targetUserId?: string
  targetUserName?: string
  rideId?: string
  rideFrom?: string
  rideTo?: string
  rideDate?: string
  liveLocation?: { lat: number; lng: number } | null
}

export const ActiveRideSafetyModal: React.FC<ActiveRideSafetyModalProps> = ({
  isOpen,
  onClose,
  currentUserId,
  targetUserId,
  targetUserName = "User",
  rideId,
  rideFrom,
  rideTo,
  rideDate,
  liveLocation
}) => {
  const { showToast } = useToast()
  const [showReportModal, setShowReportModal] = useState(false)
  const [showEmergencyConfirm, setShowEmergencyConfirm] = useState(false)
  const [isBlocking, setIsBlocking] = useState(false)

  if (!isOpen && !showReportModal) return null

  const handleBlockUser = async () => {
    if (!targetUserId) return
    if (!confirm(`Are you sure you want to block ${targetUserName}? You will no longer see each other in ride matching.`)) {
      return
    }

    setIsBlocking(true)
    try {
      const res = await blockService.blockUser(currentUserId, targetUserId, "Blocked via safety menu")
      if (res.success) {
        showToast(`${targetUserName} has been blocked.`, "success")
        onClose()
      } else {
        showToast(res.message, "error")
      }
    } catch (e) {
      showToast("Failed to block user.", "error")
    } finally {
      setIsBlocking(false)
    }
  }

  const handleShareDetails = () => {
    const liveLocText = liveLocation
      ? `\nLive GPS: https://maps.google.com/?q=${liveLocation.lat.toFixed(6)},${liveLocation.lng.toFixed(6)}`
      : ""
    const text = `WayMate Active Ride Details:\nFrom: ${rideFrom || "Pickup"}\nTo: ${rideTo || "Destination"}\nDate: ${rideDate || "Today"}\nRide ID: ${rideId || "N/A"}${liveLocText}`
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text)
      showToast("Ride details & live GPS copied to clipboard!", "success")
    } else {
      showToast(text, "info")
    }
  }

  const handleConfirmEmergencyCall = () => {
    // Open emergency dialer explicitly
    window.location.href = "tel:112"
    setShowEmergencyConfirm(false)
  }

  return (
    <>
      <ModalShell isOpen={isOpen} onClose={onClose} title="Safety & Support">
        <div className="space-y-3 pt-1">
          {targetUserId && targetUserId !== currentUserId && (
            <>
              <button
                type="button"
                onClick={() => {
                  setShowReportModal(true)
                  onClose()
                }}
                className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-border bg-card hover:bg-muted font-bold text-left text-sm transition-all"
              >
                <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center text-amber-800">
                  <MaterialIcon name="report_problem" className="text-lg" />
                </div>
                <div>
                  <div className="text-foreground font-bold">Report User</div>
                  <div className="text-xs text-muted-foreground font-medium">File a confidential report about {targetUserName}</div>
                </div>
              </button>

              <button
                type="button"
                onClick={handleBlockUser}
                disabled={isBlocking}
                className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-border bg-card hover:bg-muted font-bold text-left text-sm transition-all"
              >
                <div className="w-9 h-9 rounded-full bg-red-100 flex items-center justify-center text-red-800">
                  <MaterialIcon name="block" className="text-lg" />
                </div>
                <div>
                  <div className="text-foreground font-bold">Block User</div>
                  <div className="text-xs text-muted-foreground font-medium">Prevent future ride matching and interaction</div>
                </div>
              </button>
            </>
          )}

          <button
            type="button"
            onClick={handleShareDetails}
            className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-border bg-card hover:bg-muted font-bold text-left text-sm transition-all"
          >
            <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center text-blue-800">
              <MaterialIcon name="share" className="text-lg" />
            </div>
            <div>
              <div className="text-foreground font-bold">Share Ride Details</div>
              <div className="text-xs text-muted-foreground font-medium">Copy trip details to share with trusted contacts</div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => setShowEmergencyConfirm(true)}
            className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-red-200 bg-red-50 hover:bg-red-100 font-bold text-left text-sm transition-all"
          >
            <div className="w-9 h-9 rounded-full bg-red-600 flex items-center justify-center text-white">
              <MaterialIcon name="local_police" className="text-lg" />
            </div>
            <div>
              <div className="text-red-900 font-bold">Contact Emergency Services</div>
              <div className="text-xs text-red-700 font-medium">Place an immediate call to emergency helpline (112)</div>
            </div>
          </button>
        </div>
      </ModalShell>

      {/* Explicit Emergency Confirmation Modal */}
      {showEmergencyConfirm && (
        <ModalShell isOpen={showEmergencyConfirm} onClose={() => setShowEmergencyConfirm(false)} title="Confirm Emergency Call">
          <div className="space-y-4 pt-1 text-center">
            <div className="w-12 h-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center mx-auto">
              <MaterialIcon name="emergency" className="text-2xl" />
            </div>
            <p className="text-sm font-semibold text-foreground">
              Are you sure you want to dial Emergency Helpline 112?
            </p>
            <div className="flex gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setShowEmergencyConfirm(false)}
                className="flex-1 h-12 rounded-xl font-bold"
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleConfirmEmergencyCall}
                className="flex-1 h-12 rounded-xl bg-red-600 text-white font-bold"
              >
                Call 112
              </Button>
            </div>
          </div>
        </ModalShell>
      )}

      {targetUserId && (
        <ReportUserModal
          isOpen={showReportModal}
          onClose={() => setShowReportModal(false)}
          reporterId={currentUserId}
          reportedUserId={targetUserId}
          reportedUserName={targetUserName}
          rideId={rideId}
        />
      )}
    </>
  )
}
