import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { ConfirmModal } from "../components/ui/confirm-modal"
import { useAuth } from "../hooks/useAuth"
import { authService } from "../services/auth/authService"
import { userService } from "../services/user/userService"
import { useToast } from "../components/feedback/ToastContext"
import { useAdmin } from "../contexts/AdminContext"
import { buildWhatsAppLink, formatBranchYear } from "../utils/formatters"
import { isDevMockEnabled, clearDevMock } from "../utils/devMock"

export function ProfilePage() {
  const navigate = useNavigate()
  const { user, profile, loading: authLoading, profileLoading } = useAuth()
  const { isAdmin } = useAdmin()
  const { showToast } = useToast()

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [isCheckingActiveRides, setIsCheckingActiveRides] = useState(false)
  const [isDeletingAccount, setIsDeletingAccount] = useState(false)

  useEffect(() => {
    if (!authLoading && !user && !isDevMockEnabled()) {
      navigate("/login", { replace: true })
    }
  }, [user, authLoading, navigate])

  const handleLogout = async () => {
    try {
      clearDevMock()
      await authService.signOut()
      navigate("/login", { replace: true })
    } catch (e) {
      console.error("Logout error:", e)
    }
  }

  const handleDeleteAccountClick = async () => {
    if (!user) return
    setIsCheckingActiveRides(true)

    try {
      const activeCheck = await userService.checkActiveRidesForUser(user.uid)
      setIsCheckingActiveRides(false)

      if (activeCheck.hasActiveRides) {
        showToast(activeCheck.message || "Cannot delete account with active rides or pending requests.", "error")
        return
      }

      setIsDeleteModalOpen(true)
    } catch (err) {
      console.error("Active rides check error:", err)
      setIsCheckingActiveRides(false)
      showToast("Error checking account status. Please try again.", "error")
    }
  }

  const handleConfirmDeleteAccount = async () => {
    if (!user) return
    setIsDeletingAccount(true)

    try {
      const res = await userService.deleteUserAccount(user.uid)
      if (res.success) {
        showToast("Account deleted successfully.", "info")
        await authService.signOut()
        navigate("/login", { replace: true })
      } else {
        showToast(res.message, "error")
      }
    } catch (err: any) {
      console.error("Delete account error:", err)
      showToast(err?.message || "Failed to delete account.", "error")
    } finally {
      setIsDeletingAccount(false)
      setIsDeleteModalOpen(false)
    }
  }

  const displayName = (profile?.name && profile.name !== "Student" && profile.name !== "User")
    ? profile.name
    : (user?.displayName || (user?.email ? user.email.split("@")[0] : "") || profile?.name || "User")
  const initial = displayName ? displayName.trim().charAt(0).toUpperCase() : "U"

  const isProfileDataLoading = authLoading || profileLoading

  return (
    <MobileShell className="flex flex-col space-y-6">
      {/* Title */}
      <h1 className="text-edex-section text-foreground font-bold shrink-0">Profile</h1>

      {/* User Info Header Card */}
      <div className="bg-card border border-border/60 rounded-[24px] p-5 flex items-center justify-between shadow-xs shrink-0">
        {isProfileDataLoading ? (
          <div className="flex items-center space-x-4 min-w-0 flex-1">
            <div className="h-16 w-16 rounded-full bg-muted animate-pulse border border-border/40 shrink-0" />
            <div className="space-y-2 min-w-0 flex-1">
              <div className="h-5 w-36 bg-muted animate-pulse rounded-md" />
              <div className="h-4 w-48 bg-muted/60 animate-pulse rounded-md" />
            </div>
          </div>
        ) : (
          <div className="flex items-center space-x-4 min-w-0 flex-1">
            <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center font-bold text-[24px] text-foreground border border-border/40 shrink-0">
              {initial}
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-[17px] text-foreground font-bold uppercase truncate">{displayName}</h2>
              <p className="text-[14px] font-semibold text-muted-foreground truncate">
                {formatBranchYear(profile?.department, profile?.year, profile?.college || "CET")}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Action Rows List */}
      <div className="bg-card border border-border/60 rounded-[24px] divide-y divide-border/40 overflow-hidden shadow-xs shrink-0">
        <button
          onClick={() => navigate("/profile/account")}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="edit" className="text-[20px] text-muted-foreground" />
            <span className="text-[15px] font-semibold text-foreground">Edit Profile</span>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        <button
          onClick={() => navigate("/rides")}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="directions_car" className="text-[20px] text-muted-foreground" />
            <span className="text-[15px] font-semibold text-foreground">My Rides</span>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        <button
          onClick={() => navigate("/activity")}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="notifications" className="text-[20px] text-muted-foreground" />
            <span className="text-[15px] font-semibold text-foreground">Notifications</span>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        <button
          onClick={() => navigate("/profile/privacy")}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="shield" className="text-[20px] text-muted-foreground" />
            <span className="text-[15px] font-semibold text-foreground">Privacy & Consent</span>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        <button
          onClick={() => navigate("/account-info")}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="phonelink_lock" className="text-[20px] text-muted-foreground" />
            <div>
              <span className="text-[15px] font-semibold text-foreground block">Two-Factor Authentication</span>
              <span className="text-[11px] text-muted-foreground">SMS verification security</span>
            </div>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        <button
          onClick={() => {
            const link = buildWhatsAppLink("9495816772", "Hi, I would like to report a bug on WayMate: ")
            window.open(link, "_blank")
          }}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="bug_report" className="text-[20px] text-muted-foreground" />
            <span className="text-[15px] font-semibold text-foreground">Report a Bug</span>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        {isAdmin && (
          <button
            onClick={() => navigate("/admin")}
            className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
          >
            <div className="flex items-center space-x-3.5">
              <MaterialIcon name="admin_panel_settings" className="text-[20px] text-foreground" />
              <div>
                <span className="text-[15px] font-bold text-foreground flex items-center gap-2">
                  Admin Portal
                  <span className="text-[10px] font-extrabold bg-[#C5FF00] text-black px-1.5 py-0.5 rounded">
                    OPS
                  </span>
                </span>
                <p className="text-[11px] text-muted-foreground">Campus rides & user moderation</p>
              </div>
            </div>
            <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
          </button>
        )}

        <button
          onClick={handleLogout}
          className="w-full flex items-center justify-between p-4 hover:bg-destructive/10 transition-colors cursor-pointer text-left text-destructive"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="logout" className="text-[20px] text-destructive" />
            <span className="text-[15px] font-bold">Log Out</span>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-destructive/60" />
        </button>
      </div>

      {/* Account & Data Rights Card */}
      <div className="bg-card border border-border/60 rounded-[24px] divide-y divide-border/40 overflow-hidden shadow-xs shrink-0">
        <button
          onClick={() => navigate("/data-rights")}
          className="w-full flex items-center justify-between p-4 hover:bg-muted/40 transition-colors cursor-pointer text-left"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="policy" className="text-[20px] text-muted-foreground" />
            <div>
              <span className="text-[14px] font-semibold text-foreground block leading-tight">
                Data Rights Request (DPDP)
              </span>
              <span className="text-[12px] text-muted-foreground block mt-0.5">
                Access, correct, or erase your data
              </span>
            </div>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-muted-foreground" />
        </button>

        <button
          onClick={handleDeleteAccountClick}
          disabled={isCheckingActiveRides}
          className="w-full flex items-center justify-between p-4 hover:bg-destructive/10 transition-colors cursor-pointer text-left text-destructive"
        >
          <div className="flex items-center space-x-3.5">
            <MaterialIcon name="delete_outline" className="text-[20px] text-destructive" />
            <div>
              <span className="text-[14px] font-semibold text-destructive block leading-tight">
                {isCheckingActiveRides ? "Checking active rides..." : "Delete Account"}
              </span>
              <span className="text-[12px] text-destructive/70 block mt-0.5">
                Permanently delete account and ride history
              </span>
            </div>
          </div>
          <MaterialIcon name="chevron_right" className="text-[20px] text-destructive/60" />
        </button>
      </div>

      {/* Privacy Grievance Footer */}
      <div className="text-center pt-2 pb-12 space-y-1 shrink-0">
        <p className="text-[12px] text-muted-foreground">
          Privacy grievances:{" "}
          <a
            href="mailto:icvalley@proton.me"
            className="underline font-semibold text-foreground hover:text-primary transition-colors"
          >
            icvalley@proton.me
          </a>
        </p>
        <p className="text-[11px] text-muted-foreground/60">
          WayMate v1.0.0 • DPDPA 2023 Compliant
        </p>
      </div>

      {/* Delete Account Modal */}
      <ConfirmModal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onConfirm={handleConfirmDeleteAccount}
        title="Delete Account?"
        description="Are you sure you want to delete your WayMate account? This action is permanent and cannot be undone."
        confirmText="Delete Account"
        cancelText="Keep Account"
        isLoading={isDeletingAccount}
        variant="destructive"
      />
    </MobileShell>
  )
}
