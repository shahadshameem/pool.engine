/**
 * Privacy Settings Page (Profile → Privacy)
 * Shows user's current per-purpose consent state and allows toggling.
 * Extended for DPDP compliance: consent toggles, links to Privacy Notice,
 * Terms, Data Rights, and grievance contact.
 *
 * Replaces the old placeholder PrivacyPage with a fully functional settings page.
 */
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Shield, Lock, Eye, FileText, ExternalLink } from "lucide-react"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { useConsent } from "../contexts/ConsentContext"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import {
  type ConsentPurpose,
  PURPOSE_LABELS,
  PURPOSE_DESCRIPTIONS,
  OPTIONAL_PURPOSES,
} from "../services/consent/consentService"
import { GRIEVANCE_OFFICER } from "../services/consent/dataRightsService"

function ConsentToggle({
  label,
  description,
  checked,
  onToggle,
}: {
  label: string
  description: string
  checked: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex items-start justify-between space-x-4 py-3.5 border-b border-border/40 last:border-b-0">
      <div className="flex-1">
        <p className="text-[14px] font-bold text-foreground">{label}</p>
        <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={`${checked ? "Disable" : "Enable"} ${label}`}
        onClick={onToggle}
        className={`relative shrink-0 h-6 w-11 rounded-full transition-colors ${
          checked ? "bg-foreground" : "bg-muted-foreground/30"
        }`}
      >
        <span
          className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? "left-6" : "left-1"
          }`}
        />
      </button>
    </div>
  )
}

export function PrivacyPage() {
  const navigate = useNavigate()
  const { goBack } = useBackNavigation()
  const { user } = useAuth()
  const { consentMap, updateConsent, loading } = useConsent()

  const handleToggle = async (purpose: ConsentPurpose) => {
    if (!user || !consentMap) return
    await updateConsent(purpose, !consentMap[purpose])
  }

  return (
    <MobileShell hideBottomNav hasStickyHeader className="bg-background min-h-screen">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between bg-background/95 px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 backdrop-blur border-b border-border/40">
        <Button variant="ghost" size="icon" onClick={goBack} className="-ml-2 h-9 w-9 rounded-full">
          <ArrowLeft className="h-5 w-5 text-foreground" />
        </Button>
        <h1 className="text-[17px] font-bold text-foreground">Privacy Settings</h1>
        <div className="w-9" />
      </div>

      <div className="p-5 space-y-5">
        {/* Intro */}
        <div className="bg-card rounded-[24px] border border-border/60 p-5 shadow-sm space-y-3">
          <div className="flex items-center space-x-3">
            <div className="h-11 w-11 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
              <Shield className="h-5 w-5 text-foreground" />
            </div>
            <div>
              <h2 className="text-[16px] font-extrabold text-foreground">Your Privacy at WayMate</h2>
              <p className="text-[11px] text-muted-foreground">
                Under DPDPA 2023, you control how your data is used.
              </p>
            </div>
          </div>
        </div>

        {/* Essential — always on */}
        <div className="space-y-2">
          <h3 className="text-[13px] font-semibold text-muted-foreground px-1">Always Active</h3>
          <div className="bg-card rounded-[20px] border border-border/60 shadow-sm p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[14px] font-bold text-foreground">Core Service</p>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  Account, ride management, safety — required for the service to work.
                </p>
              </div>
              <div className="h-6 w-11 rounded-full bg-foreground relative shrink-0">
                <span className="absolute top-1 left-6 h-4 w-4 rounded-full bg-white shadow" />
              </div>
            </div>
          </div>
        </div>

        {/* Optional consent toggles */}
        <div className="space-y-2">
          <h3 className="text-[13px] font-semibold text-muted-foreground px-1">Optional Purposes</h3>
          <div className="bg-card rounded-[20px] border border-border/60 shadow-sm px-5">
            {loading ? (
              <div className="py-8 text-center">
                <p className="text-[13px] text-muted-foreground">Loading your preferences…</p>
              </div>
            ) : !user ? (
              <div className="py-6 text-center">
                <p className="text-[13px] text-muted-foreground">
                  Sign in to manage your consent preferences.
                </p>
              </div>
            ) : (
              OPTIONAL_PURPOSES.map((purpose) => (
                <ConsentToggle
                  key={purpose}
                  label={PURPOSE_LABELS[purpose]}
                  description={PURPOSE_DESCRIPTIONS[purpose]}
                  checked={consentMap?.[purpose] ?? false}
                  onToggle={() => handleToggle(purpose)}
                />
              ))
            )}
          </div>
          {!loading && user && (
            <p className="text-[10px] text-muted-foreground px-1 pt-0.5">
              You can withdraw consent at any time. Withdrawal does not affect the
              lawfulness of processing before withdrawal.
            </p>
          )}
        </div>

        {/* Data details */}
        <div className="space-y-2">
          <h3 className="text-[13px] font-semibold text-muted-foreground px-1">How We Handle Your Data</h3>
          <div className="bg-card rounded-[20px] border border-border/60 shadow-sm p-5 space-y-4">
            <div className="flex items-start space-x-3.5">
              <div className="p-2 bg-secondary rounded-xl text-foreground shrink-0 mt-0.5">
                <FileText className="h-4 w-4" />
              </div>
              <div>
                <span className="text-[14px] font-bold text-foreground block">Profile & Student Info</span>
                <span className="text-[12px] text-muted-foreground block mt-0.5 leading-relaxed">
                  Your name, college, department, and year are visible to verified students browsing rides to ensure trust in campus carpooling.
                </span>
              </div>
            </div>
            <div className="flex items-start space-x-3.5 pt-3 border-t border-border/50">
              <div className="p-2 bg-secondary rounded-xl text-foreground shrink-0 mt-0.5">
                <Lock className="h-4 w-4" />
              </div>
              <div>
                <span className="text-[14px] font-bold text-foreground block">Protected Contact Information</span>
                <span className="text-[12px] text-muted-foreground block mt-0.5 leading-relaxed">
                  Your mobile phone number is shared only once a ride request is officially accepted.
                </span>
              </div>
            </div>
            <div className="flex items-start space-x-3.5 pt-3 border-t border-border/50">
              <div className="p-2 bg-secondary rounded-xl text-foreground shrink-0 mt-0.5">
                <Eye className="h-4 w-4" />
              </div>
              <div>
                <span className="text-[14px] font-bold text-foreground block">Ride History & Requests</span>
                <span className="text-[12px] text-muted-foreground block mt-0.5 leading-relaxed">
                  Trip origin and drop locations are stored securely to facilitate ride matching and history views.
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Links */}
        <div className="space-y-2">
          <h3 className="text-[13px] font-semibold text-muted-foreground px-1">Your Rights & Documents</h3>
          <div className="bg-card rounded-[20px] border border-border/60 shadow-sm divide-y divide-border/40 overflow-hidden">
            <button
              onClick={() => navigate("/profile/privacy")}
              className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors text-left"
            >
              <div className="flex items-center space-x-3">
                <Shield className="h-4 w-4 text-muted-foreground" />
                <span className="text-[14px] font-semibold text-foreground">Privacy Notice (DPDPA)</span>
              </div>
              <ExternalLink className="h-4 w-4 text-muted-foreground" />
            </button>
            <button
              onClick={() => navigate("/terms")}
              className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors text-left"
            >
              <div className="flex items-center space-x-3">
                <FileText className="h-4 w-4 text-muted-foreground" />
                <span className="text-[14px] font-semibold text-foreground">Terms of Service</span>
              </div>
              <ExternalLink className="h-4 w-4 text-muted-foreground" />
            </button>
            <button
              onClick={() => navigate("/data-rights")}
              className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors text-left"
            >
              <div className="flex items-center space-x-3">
                <MaterialIcon name="policy" className="text-[20px] text-muted-foreground" />
                <span className="text-[14px] font-semibold text-foreground">Data Rights Request</span>
              </div>
              <ExternalLink className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
        </div>

        {/* Grievance contact footer */}
        <div className="bg-muted/40 rounded-[20px] p-4 border border-border/60 text-center space-y-1">
          <span className="text-[12px] font-bold text-foreground block">
            Privacy Grievance Officer
          </span>
          <a
            href={`mailto:${GRIEVANCE_OFFICER.email}`}
            className="text-[12px] text-foreground underline font-semibold"
          >
            {GRIEVANCE_OFFICER.email}
          </a>
          {/* ⚠️ LEGAL: Replace with real Grievance Officer name and contact before go-live */}
          <span className="text-[11px] text-muted-foreground block">
            Response within {GRIEVANCE_OFFICER.responseTimeDays} days. Unresolved grievances may be escalated to the Data Protection Board of India.
          </span>
        </div>
      </div>
    </MobileShell>
  )
}
