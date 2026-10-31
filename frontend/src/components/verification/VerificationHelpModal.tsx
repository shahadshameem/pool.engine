import React, { useState } from "react"
import { ModalShell } from "../common/ModalShell"
import { Button } from "../ui/button"
import { MaterialIcon } from "../common/MaterialIcon"
import { verificationHelpService } from "../../services/verification/verificationHelpService"
import { useToast } from "../feedback/ToastContext"

interface VerificationHelpModalProps {
  isOpen: boolean
  onClose: () => void
  userId: string
  onSubmitted?: () => void
}

export function VerificationHelpModal({ isOpen, onClose, userId, onSubmitted }: VerificationHelpModalProps) {
  const { showToast } = useToast()
  const [reason, setReason] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) {
      showToast("Please enter a short reason for urgent verification.", "error")
      return
    }

    setIsSubmitting(true)
    try {
      const result = await verificationHelpService.submitHelpRequest(userId, reason)
      if (result.success) {
        showToast(result.message, "success")
        setReason("")
        onClose()
        if (onSubmitted) onSubmitted()
      } else {
        showToast(result.message, "info")
      }
    } catch (err: any) {
      showToast(err?.message || "Failed to submit request.", "error")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title="Request Verification Help">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 flex items-start gap-3 text-xs text-amber-900 dark:text-amber-200">
          <MaterialIcon name="info" className="text-lg text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-bold text-[13px]">Need Urgent Access?</p>
            <p className="leading-relaxed">
              For safety reasons, gender verification cannot be bypassed on the client. If you urgently need to join a gender-restricted ride, submit a verification help request for campus admins.
            </p>
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-bold text-foreground block">
            Reason / Details for Urgent Review:
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Urgent lab commute from CET main gate. Registered with official CET email..."
            rows={3}
            className="w-full bg-muted text-foreground border border-border/60 rounded-2xl p-3 text-xs focus:outline-none focus:ring-1 focus:ring-foreground"
          />
        </div>

        <div className="pt-2 flex items-center justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={isSubmitting}>
            {isSubmitting ? "Submitting..." : "Submit Verification Help Request"}
          </Button>
        </div>
      </form>
    </ModalShell>
  )
}
