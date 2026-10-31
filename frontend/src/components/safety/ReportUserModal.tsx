import React, { useState } from "react"
import { ModalShell } from "../common/ModalShell"
import { Button } from "../ui/button"
import { safetyReportService, type SafetyReportCategory } from "../../services/safety/safetyReportService"
import { useToast } from "../feedback/ToastContext"

interface ReportUserModalProps {
  isOpen: boolean
  onClose: () => void
  reporterId: string
  reportedUserId: string
  reportedUserName?: string
  rideId?: string
  rideRequestId?: string
}

const CATEGORIES: { value: SafetyReportCategory; label: string }[] = [
  { value: "wrong_profile_information", label: "Wrong profile information" },
  { value: "phone_misuse", label: "Phone number misuse" },
  { value: "harassment", label: "Harassment" },
  { value: "inappropriate_behavior", label: "Inappropriate behaviour" },
  { value: "impersonation", label: "Impersonation" },
  { value: "safety_concern", label: "Safety concern" },
  { value: "other", label: "Other" },
]

export const ReportUserModal: React.FC<ReportUserModalProps> = ({
  isOpen,
  onClose,
  reporterId,
  reportedUserId,
  reportedUserName = "User",
  rideId,
  rideRequestId
}) => {
  const { showToast } = useToast()
  const [category, setCategory] = useState<SafetyReportCategory>("safety_concern")
  const [description, setDescription] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSubmitting(true)

    try {
      const res = await safetyReportService.submitReport({
        reporterId,
        reportedUserId,
        rideId,
        rideRequestId,
        category,
        description
      })

      if (res.success) {
        showToast("Safety report submitted successfully.", "success")
        setDescription("")
        onClose()
      } else {
        showToast(res.message || "Failed to submit report.", "error")
      }
    } catch (err: any) {
      showToast("An unexpected error occurred.", "error")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <ModalShell isOpen={isOpen} onClose={onClose} title={`Report ${reportedUserName}`}>
      <form onSubmit={handleSubmit} className="space-y-4 pt-2">
        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground block mb-1">
            Reason for Report <span className="text-destructive">*</span>
          </label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as SafetyReportCategory)}
            className="w-full h-12 rounded-xl border border-border bg-card px-3 font-semibold text-sm focus:outline-none focus:ring-2 focus:ring-black"
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground block mb-1">
            Details / Description
          </label>
          <textarea
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Please provide details about your report..."
            className="w-full rounded-xl border border-border bg-card p-3 font-medium text-sm focus:outline-none focus:ring-2 focus:ring-black"
          />
        </div>

        <p className="text-[12px] text-muted-foreground">
          Reports are confidential and reviewed by moderation. Misuse of the reporting system may lead to account restrictions.
        </p>

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
            className="flex-1 h-12 rounded-xl bg-destructive text-destructive-foreground hover:bg-destructive/90 font-bold"
          >
            {isSubmitting ? "Submitting..." : "Submit Report"}
          </Button>
        </div>
      </form>
    </ModalShell>
  )
}
