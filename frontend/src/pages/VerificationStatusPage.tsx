import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { Button } from "../components/ui/button"
import { useAuth } from "../hooks/useAuth"
import { verificationHelpService, type VerificationHelpRequest } from "../services/verification/verificationHelpService"
import { VerificationHelpModal } from "../components/verification/VerificationHelpModal"
import { getCollegeShortName } from "../utils/formatters"
import { isDevMockEnabled } from "../utils/devMock"

export function VerificationStatusPage() {
  const navigate = useNavigate()
  const { user, profile, loading: authLoading } = useAuth()
  const [latestHelpReq, setLatestHelpReq] = useState<VerificationHelpRequest | null>(null)
  const [isHelpModalOpen, setIsHelpModalOpen] = useState(false)

  const vStatus = profile?.genderVerificationStatus || "verified"
  const isVerified = vStatus === "verified"
  const isPending = vStatus === "pending" || vStatus === "unverified"
  const isRejected = vStatus === "rejected"

  useEffect(() => {
    if (!authLoading && !user && !isDevMockEnabled()) {
      navigate("/login", { replace: true })
      return
    }

    if (user) {
      verificationHelpService.getUserLatestRequest(user.uid).then(setLatestHelpReq).catch(() => {})
    }
  }, [user, authLoading, navigate])

  const refreshHelpReq = () => {
    if (user) {
      verificationHelpService.getUserLatestRequest(user.uid).then(setLatestHelpReq).catch(() => {})
    }
  }

  return (
    <MobileShell hideBottomNav className="flex flex-col space-y-6">
      {/* Navigation Header */}
      <div className="flex items-center space-x-2">
        <button
          onClick={() => navigate(-1)}
          className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
          aria-label="Back"
        >
          <MaterialIcon name="arrow_back" className="text-[24px] text-foreground" />
        </button>
        <h1 className="text-edex-heading text-foreground font-bold">Gender Verification Status</h1>
      </div>

      {/* Main Status Display Card */}
      <div className="bg-card border border-border/60 rounded-[24px] p-6 shadow-sm space-y-5 text-center">
        <div className="flex justify-center">
          <div className={`w-16 h-16 rounded-full flex items-center justify-center shadow-xs ${
            isVerified ? "bg-[#25D366]/20 text-[#25D366] border border-[#25D366]/30" :
            isPending ? "bg-amber-500/10 text-amber-600 border border-amber-500/30" :
            "bg-destructive/10 text-destructive border border-destructive/30"
          }`}>
            <MaterialIcon
              name={isVerified ? "verified" : isPending ? "hourglass_top" : "highlight_off"}
              className="text-[36px]"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <h2 className="text-xl font-black text-foreground capitalize">
            {isVerified ? "Gender Verified" : isRejected ? "Verification Needs Attention" : "Verification Pending"}
          </h2>
          <p className="text-xs text-muted-foreground max-w-xs mx-auto leading-relaxed">
            {isVerified
              ? "Your account verification is complete."
              : isRejected
              ? "Verification could not be completed. Please review your profile details or submit a verification help request for administrator assistance."
              : ""}
          </p>
        </div>

        {/* Profile Details Breakdown */}
        <div className="bg-muted/50 rounded-2xl p-4 text-left text-xs space-y-2 border border-border/40">
          <div className="flex justify-between py-1 border-b border-border/30">
            <span className="text-muted-foreground">Registered Name:</span>
            <span className="font-semibold text-foreground">{profile?.name || "Student"}</span>
          </div>
          <div className="flex justify-between py-1 border-b border-border/30">
            <span className="text-muted-foreground">College / Campus:</span>
            <span className="font-semibold text-foreground truncate max-w-[180px]">{getCollegeShortName(profile?.college)}</span>
          </div>
          <div className="flex justify-between py-1 border-b border-border/30">
            <span className="text-muted-foreground">Declared Gender:</span>
            <span className="font-semibold text-foreground capitalize">{profile?.gender || "Not set"}</span>
          </div>
          <div className="flex justify-between py-1">
            <span className="text-muted-foreground">Verification State:</span>
            <span className={`font-bold capitalize ${
              isVerified ? "text-[#25D366]" : isRejected ? "text-destructive" : "text-amber-600"
            }`}>
              {vStatus}
            </span>
          </div>
        </div>
      </div>

      {/* Verification Escalation / Help Card */}
      {!isVerified && (
        <div className="bg-card border border-border/60 rounded-[24px] p-5 shadow-sm space-y-4">
          <div className="flex items-start gap-3">
            <MaterialIcon name="support_agent" className="text-2xl text-foreground shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h3 className="font-bold text-sm text-foreground">Need Verification Help?</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                If an administrator is busy or you urgently need access to a ride for campus commute, submit a verification help request for priority review.
              </p>
            </div>
          </div>

          {latestHelpReq && latestHelpReq.status === "pending" ? (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-3 text-xs text-amber-900 dark:text-amber-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MaterialIcon name="pending" className="text-base text-amber-600" />
                <span>Help Request Under Review</span>
              </div>
              <span className="text-[10px] font-bold uppercase bg-amber-200 dark:bg-amber-900/50 text-amber-800 dark:text-amber-200 px-2 py-0.5 rounded-full">
                Pending
              </span>
            </div>
          ) : (
            <Button
              variant="outline"
              size="default"
              className="w-full text-xs font-bold"
              onClick={() => setIsHelpModalOpen(true)}
            >
              <MaterialIcon name="forward_to_inbox" className="text-base mr-1.5" />
              Request Verification Help
            </Button>
          )}
        </div>
      )}

      {/* Emergency Assistance Notice */}
      <div className="bg-muted/40 rounded-2xl p-4 text-xs space-y-2 border border-border/30 text-center">
        <p className="font-semibold text-foreground">Need Urgent Assistance?</p>
        <p className="text-muted-foreground text-[11px] leading-relaxed">
          Verification cannot be bypassed on the client for safety reasons. For official support, contact your designated campus WayMate administrator.
        </p>
      </div>

      {/* Escalation Help Modal */}
      {user && (
        <VerificationHelpModal
          isOpen={isHelpModalOpen}
          onClose={() => setIsHelpModalOpen(false)}
          userId={user.uid}
          onSubmitted={refreshHelpReq}
        />
      )}
    </MobileShell>
  )
}
