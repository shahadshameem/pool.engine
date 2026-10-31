import React, { useState } from "react"
import { ModalShell } from "../common/ModalShell"
import { Button } from "../ui/button"
import { userService, type Gender } from "../../services/user/userService"
import { useToast } from "../feedback/ToastContext"

interface GenderChangeRequestModalProps {
  isOpen: boolean
  onClose: () => void
  currentUserId: string
  currentGender?: Gender
}

export const GenderChangeRequestModal: React.FC<GenderChangeRequestModalProps> = ({
  isOpen,
  onClose,
  currentUserId,
  currentGender
}) => {
  const { showToast } = useToast()
  const [targetGender, setTargetGender] = useState<Gender>(currentGender === "female" ? "male" : "female")
  const [reason, setReason] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!reason.trim()) {
      showToast("Please provide a reason for the gender update request.", "error")
      return
    }

    setIsSubmitting(true)
    try {
      const res = await userService.requestGenderChange(currentUserId, targetGender, reason)
      if (res.success) {
        showToast("Gender change request submitted for moderation review.", "success")
        onClose()
      } else {
        showToast(res.message, "error")
      }
    } catch (err) {
      showToast("Failed to submit request.", "error")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title="Request Gender Update">
      <form onSubmit={handleSubmit} className="space-y-4 pt-1">
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-900 leading-relaxed font-medium">
          <strong>Important Safety Notice:</strong> Gender information affects ride eligibility, same-gender matching, and user safety controls. Unrestricted direct changes are disabled. Updates require moderation review.
        </div>

        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground block mb-2">
            Requested Gender <span className="text-destructive">*</span>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setTargetGender("female")}
              className={`h-12 rounded-xl border font-bold text-sm flex items-center justify-center transition-all ${
                targetGender === "female"
                  ? "bg-[#C5FF00] text-black border-transparent font-extrabold"
                  : "bg-card border-border text-foreground hover:bg-muted font-semibold"
              }`}
            >
              Female
            </button>
            <button
              type="button"
              onClick={() => setTargetGender("male")}
              className={`h-12 rounded-xl border font-bold text-sm flex items-center justify-center transition-all ${
                targetGender === "male"
                  ? "bg-[#C5FF00] text-black border-transparent font-extrabold"
                  : "bg-card border-border text-foreground hover:bg-muted font-semibold"
              }`}
            >
              Male
            </button>
          </div>
        </div>

        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground block mb-1">
            Reason for Change Request <span className="text-destructive">*</span>
          </label>
          <textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Please explain why your gender profile needs to be updated..."
            className="w-full rounded-xl border border-border bg-card p-3 font-medium text-sm focus:outline-none focus:ring-2 focus:ring-black"
          />
        </div>

        <div className="flex gap-3 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1 h-12 rounded-xl font-bold"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={isSubmitting}
            className="flex-1 h-12 rounded-xl bg-black text-white hover:bg-black/90 font-bold"
          >
            {isSubmitting ? "Submitting..." : "Submit Request"}
          </Button>
        </div>
      </form>
    </ModalShell>
  )
}
