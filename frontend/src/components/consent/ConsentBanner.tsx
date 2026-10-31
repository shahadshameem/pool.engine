/**
 * ConsentBanner
 * Shown to all users who have not yet expressed per-purpose consent.
 * Compliant with DPDPA 2023 §6: consent must be free, specific, informed,
 * unconditional, and unambiguous. Each checkbox starts unchecked (opt-in).
 *
 * ⚠️ LEGAL REVIEW REQUIRED: Purpose descriptions and policy links must be
 *    approved by qualified legal counsel before public release.
 */
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "../ui/button"
import { MaterialIcon } from "../common/MaterialIcon"
import {
  OPTIONAL_PURPOSES,
  PURPOSE_LABELS,
  PURPOSE_DESCRIPTIONS,
  type ConsentPurpose,
  recordBulkConsent,
} from "../../services/consent/consentService"
import { useAuth } from "../../hooks/useAuth"
import { useConsent } from "../../contexts/ConsentContext"

export function ConsentBanner() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { needsBanner, dismissBanner } = useConsent()

  const [optionalConsents, setOptionalConsents] = useState<
    Record<ConsentPurpose, boolean>
  >({
    essential:     true,   // always true, not shown as a checkbox
    analytics:     false,  // unchecked by default (opt-in)
    notifications: false,
    location:      false,
    marketing:     false,
  })
  const [saving, setSaving] = useState(false)

  if (!needsBanner) return null

  const toggle = (purpose: ConsentPurpose) => {
    setOptionalConsents((prev) => ({ ...prev, [purpose]: !prev[purpose] }))
  }

  const handleAcceptSelected = async () => {
    setSaving(true)
    try {
      if (user) {
        await recordBulkConsent(user.uid, optionalConsents, "consent_banner")
      }
    } catch (err) {
      console.warn("Could not save consent to Firestore:", err)
    } finally {
      dismissBanner()
      setSaving(false)
    }
  }

  const handleAcceptAll = async () => {
    setSaving(true)
    const all: Record<ConsentPurpose, boolean> = {
      essential:     true,
      analytics:     true,
      notifications: true,
      location:      true,
      marketing:     true,
    }
    try {
      if (user) {
        await recordBulkConsent(user.uid, all, "consent_banner")
      }
    } catch (err) {
      console.warn("Could not save consent to Firestore:", err)
    } finally {
      dismissBanner()
      setSaving(false)
    }
  }

  return (
    /* Backdrop */
    <div className="fixed inset-0 z-[9999] flex items-end justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md bg-background rounded-t-[28px] border border-border/60 shadow-2xl p-6 pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))] space-y-5 animate-in slide-in-from-bottom duration-300 max-h-[calc(100dvh-env(safe-area-inset-top,0px)-24px)] overflow-y-auto">
        {/* Header */}
        <div className="flex items-start space-x-3">
          <div className="p-2 bg-primary/10 rounded-xl shrink-0 mt-0.5">
            <MaterialIcon name="privacy_tip" className="text-[22px] text-foreground" />
          </div>
          <div>
            <h2 className="text-[17px] font-extrabold text-foreground leading-tight">
              Your Privacy Choices
            </h2>
            <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
              WayMate uses your data only for the purposes you allow. Essential
              processing (your account & rides) is always on.{" "}
              {/* ⚠️ LEGAL REVIEW: Ensure this statement accurately reflects data practices */}
            </p>
          </div>
        </div>

        {/* Essential — non-toggleable */}
        <div className="bg-muted/40 rounded-2xl p-3.5 flex items-center justify-between">
          <div>
            <p className="text-[13px] font-bold text-foreground">
              Core Service (always active)
            </p>
            <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
              Required to deliver rides, manage your account, and ensure safety.
            </p>
          </div>
          <div className="ml-3 shrink-0">
            <div className="h-5 w-5 rounded bg-foreground flex items-center justify-center">
              <MaterialIcon name="check" className="text-[14px] text-background" />
            </div>
          </div>
        </div>

        {/* Optional purposes */}
        <div className="space-y-3">
          {OPTIONAL_PURPOSES.filter((p) => p !== "marketing").map((purpose) => (
            <label
              key={purpose}
              className="flex items-start space-x-3 cursor-pointer group"
            >
              <input
                type="checkbox"
                checked={optionalConsents[purpose]}
                onChange={() => toggle(purpose)}
                className="mt-0.5 h-4 w-4 rounded accent-foreground shrink-0"
                aria-label={PURPOSE_LABELS[purpose]}
              />
              <div>
                <p className="text-[13px] font-bold text-foreground group-hover:underline">
                  {PURPOSE_LABELS[purpose]}
                </p>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  {PURPOSE_DESCRIPTIONS[purpose]}
                </p>
              </div>
            </label>
          ))}
        </div>

        {/* Privacy policy link */}
        <p className="text-[11px] text-muted-foreground text-center">
          Read our{" "}
          <button
            onClick={() => navigate("/profile/privacy")}
            className="underline font-semibold text-foreground"
          >
            Privacy Notice
          </button>{" "}
          to learn how we handle your data.{" "}
          You can change these choices anytime in Profile → Privacy.
        </p>

        {/* Actions */}
        <div className="flex gap-3">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={handleAcceptSelected}
            disabled={saving}
          >
            {saving ? "Saving…" : "Accept Selected"}
          </Button>
          <Button
            variant="primary"
            size="sm"
            className="flex-1"
            onClick={handleAcceptAll}
            disabled={saving}
          >
            Accept All
          </Button>
        </div>
      </div>
    </div>
  )
}
