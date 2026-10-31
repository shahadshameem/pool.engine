/**
 * Data Rights Request Form Page
 * Implements DPDPA 2023 §12–14 rights for Data Principals.
 *
 * ⚠️ LEGAL REVIEW REQUIRED:
 *   - Confirm 30-day SLA commitment is operationally achievable.
 *   - Verify identity verification requirements before processing requests.
 *   - Add "Nomination" (§14(4)) handling procedure.
 */
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { useToast } from "../components/feedback/ToastContext"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import {
  submitDataRightsRequest,
  REQUEST_TYPE_LABELS,
  REQUEST_TYPE_DESCRIPTIONS,
  type DataRightsRequestType,
  GRIEVANCE_OFFICER,
} from "../services/consent/dataRightsService"
import { ArrowLeft, CheckCircle } from "lucide-react"
import { useSEO } from "../hooks/useSEO"

const REQUEST_TYPES: DataRightsRequestType[] = [
  "access",
  "correction",
  "erasure",
  "withdrawal",
  "grievance",
  "nomination",
]

export function DataRightsPage() {
  useSEO({
    title: "Data Rights & Privacy Request",
    description: "Submit personal data access, correction, erasure, or grievance requests under DPDPA 2023 for WayMate (wmate.app).",
    canonicalPath: "/data-rights",
  })

  const navigate = useNavigate()
  const { goBack } = useBackNavigation()
  const { user, profile } = useAuth()
  const { showToast } = useToast()

  const [selectedType, setSelectedType] = useState<DataRightsRequestType | null>(null)
  const [details, setDetails] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [ticketId, setTicketId] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user || !selectedType) return
    if (!details.trim()) {
      showToast("Please provide details for your request", "error")
      return
    }

    setSubmitting(true)
    try {
      const id = await submitDataRightsRequest(
        user.uid,
        profile?.email ?? user.email ?? "",
        profile?.name ?? user.displayName ?? "User",
        selectedType,
        details.trim()
      )
      setTicketId(id)
      setSubmitted(true)
    } catch (err: any) {
      console.error("Data rights request failed:", err)
      showToast(err?.message || "Failed to submit request. Please try again.", "error")
    } finally {
      setSubmitting(false)
    }
  }

  if (!user) {
    return (
      <MobileShell hideBottomNav>
        <div className="flex flex-col items-center justify-center h-[70vh] space-y-4 text-center">
          <MaterialIcon name="lock" className="text-[48px] text-muted-foreground" />
          <p className="text-muted-foreground text-[14px]">
            Please sign in to submit a data rights request.
          </p>
          <Button onClick={() => navigate("/login")}>Sign In</Button>
        </div>
      </MobileShell>
    )
  }

  if (submitted && ticketId) {
    return (
      <MobileShell hideBottomNav className="pb-12">
        <div className="flex flex-col items-center justify-center h-[70vh] space-y-5 text-center px-4">
          <CheckCircle className="h-16 w-16 text-green-500" />
          <div className="space-y-2">
            <h2 className="text-[18px] font-extrabold text-foreground">
              Request Submitted
            </h2>
            <p className="text-[13px] text-muted-foreground leading-relaxed">
              Your data rights request has been logged. We will respond within{" "}
              <strong>{GRIEVANCE_OFFICER.responseTimeDays} days</strong>.
            </p>
            {/* ⚠️ LEGAL REVIEW: Confirm 30-day SLA is achievable */}
            <div className="bg-muted/40 rounded-2xl p-3 mt-2">
              <p className="text-[11px] text-muted-foreground">Ticket ID</p>
              <p className="text-[13px] font-mono font-bold text-foreground break-all">
                {ticketId}
              </p>
            </div>
            <p className="text-[11px] text-muted-foreground">
              A copy will be sent to{" "}
              <strong>{profile?.email ?? user.email}</strong>. For questions,
              email{" "}
              <a
                href={`mailto:${GRIEVANCE_OFFICER.email}`}
                className="underline text-foreground"
              >
                {GRIEVANCE_OFFICER.email}
              </a>
              .
            </p>
          </div>
          <Button variant="outline" onClick={goBack}>
            Back to Profile
          </Button>
        </div>
      </MobileShell>
    )
  }

  return (
    <MobileShell hideBottomNav className="flex flex-col space-y-5">
      {/* Header */}
      <div className="flex items-center space-x-2">
        <button
          onClick={goBack}
          className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
          aria-label="Back"
        >
          <ArrowLeft className="h-5 w-5 text-foreground" />
        </button>
        <h1 className="text-edex-heading text-foreground font-bold">
          Data Rights Request
        </h1>
      </div>

      <p className="text-[12px] text-muted-foreground leading-relaxed">
        Under the <strong>Digital Personal Data Protection Act 2023 (India)</strong>,
        you have the right to access, correct, erase, and withdraw consent for
        your personal data. Submit your request below.
      </p>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Request type selection */}
        <div className="space-y-2">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            Request Type
          </label>
          <div className="space-y-2">
            {REQUEST_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setSelectedType(type)}
                className={`w-full text-left p-4 rounded-2xl border transition-all ${
                  selectedType === type
                    ? "border-foreground bg-foreground/5 shadow-sm"
                    : "border-border/60 bg-card hover:bg-muted/40"
                }`}
              >
                <p className="text-[14px] font-bold text-foreground">
                  {selectedType === type && (
                    <MaterialIcon
                      name="check_circle"
                      className="text-[16px] text-foreground mr-1.5 inline"
                    />
                  )}
                  {REQUEST_TYPE_LABELS[type]}
                </p>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  {REQUEST_TYPE_DESCRIPTIONS[type]}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Details */}
        <div className="space-y-1.5">
          <label
            htmlFor="details"
            className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block"
          >
            Details
          </label>
          <textarea
            id="details"
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            placeholder="Please describe your request in detail…"
            rows={4}
            className="w-full bg-card border border-border/60 rounded-2xl px-4 py-3 text-[14px] text-foreground resize-none focus:outline-none focus:border-foreground"
            maxLength={2000}
          />
          <p className="text-[11px] text-muted-foreground text-right">
            {details.length}/2000
          </p>
        </div>

        {/* Disclaimer */}
        <p className="text-[11px] text-muted-foreground leading-relaxed bg-muted/40 rounded-xl p-3">
          We may need to verify your identity before processing your request. We
          will respond within <strong>{GRIEVANCE_OFFICER.responseTimeDays} days</strong>. If your
          grievance remains unresolved, you may escalate to the{" "}
          <strong>Data Protection Board of India</strong>.
        </p>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full"
          disabled={submitting || !selectedType}
        >
          {submitting ? "Submitting…" : "Submit Request"}
        </Button>
      </form>
    </MobileShell>
  )
}
