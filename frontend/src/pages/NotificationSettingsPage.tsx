import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Bell, MessageSquare, CheckCircle2, AlertTriangle, XCircle, Smartphone, ShieldCheck } from "lucide-react"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { useToast } from "../components/feedback/ToastContext"
import { userService, defaultNotificationPreferences } from "../services/user/userService"
import type { NotificationPreferences } from "../services/user/userService"
import { fcmService } from "../services/messaging/fcmService"

export function NotificationSettingsPage() {
  const navigate = useNavigate()
  const { goBack } = useBackNavigation()
  const { user, profile, loading: authLoading } = useAuth()
  const { showToast } = useToast()

  const [prefs, setPrefs] = useState<NotificationPreferences>(defaultNotificationPreferences)
  const [isSaving, setIsSaving] = useState(false)
  const [pushPermissionStatus, setPushPermissionStatus] = useState<NotificationPermission>(
    typeof window !== "undefined" && "Notification" in window ? Notification.permission : "default"
  )
  const [isRequestingPush, setIsRequestingPush] = useState(false)

  useEffect(() => {
    if (!authLoading && !user) {
      navigate("/login", { replace: true })
    } else if (profile) {
      setPrefs({
        ...defaultNotificationPreferences,
        ...profile.notificationPreferences
      })
    }
  }, [user, profile, authLoading, navigate])

  const handleEnablePush = async () => {
    if (!user) return
    setIsRequestingPush(true)
    try {
      const token = await fcmService.requestPermissionAndGetToken(user.uid)
      if (typeof window !== "undefined" && "Notification" in window) {
        setPushPermissionStatus(Notification.permission)
      }
      if (token) {
        showToast("OS Push notifications enabled!", "success")
      } else if (Notification.permission === "denied") {
        showToast("Push permission was denied in browser settings.", "error")
      }
    } catch (err) {
      console.error("Failed to enable push notifications:", err)
      showToast("Error requesting push permission", "error")
    } finally {
      setIsRequestingPush(false)
    }
  }

  const isSettingsLoading = authLoading || !profile

  const updatePreference = async (key: keyof NotificationPreferences, value: boolean) => {
    if (!user) return
    const updated = { ...prefs, [key]: value }
    setPrefs(updated)
    setIsSaving(true)

    try {
      await userService.updateUserProfile(user.uid, {
        notificationPreferences: updated
      })
      showToast("Notification preferences updated", "success")
    } catch (e) {
      console.error("Failed to update notification preferences:", e)
      showToast("Failed to save settings", "error")
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <MobileShell hideBottomNav hasStickyHeader className="bg-background min-h-screen">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between bg-background/95 px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 backdrop-blur border-b border-border/40">
        <Button variant="ghost" size="icon" onClick={goBack} className="-ml-2 h-9 w-9 rounded-full">
          <ArrowLeft className="h-5 w-5 text-foreground" />
        </Button>
        <h1 className="text-[17px] font-bold text-foreground">Notifications</h1>
        <div className="w-9" />
      </div>

      <div className="p-5 space-y-6">
        {isSettingsLoading ? (
          <div className="space-y-4">
            <div className="h-[76px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4" />
            <div className="h-[76px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4" />
            <div className="h-[76px] w-full bg-card border border-border/60 rounded-[24px] animate-pulse p-4" />
          </div>
        ) : (
          <>
            {/* OS Push Notifications Card */}
        <div className="bg-card rounded-[24px] border border-border/60 p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3.5">
              <div className="p-2.5 bg-muted rounded-[14px] text-foreground shrink-0">
                <Smartphone className="h-5 w-5" />
              </div>
              <div>
                <span className="text-[15px] font-bold text-foreground block">OS Push Notifications</span>
                <span className="text-[12px] text-muted-foreground block">Receive background alerts on lock screen</span>
              </div>
            </div>

            {pushPermissionStatus === "granted" ? (
              <span className="inline-flex items-center px-3 py-1 rounded-full text-[12px] font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                <ShieldCheck className="w-3.5 h-3.5 mr-1" /> Active
              </span>
            ) : (
              <Button
                size="sm"
                onClick={handleEnablePush}
                disabled={isRequestingPush}
                className="bg-[#C5FF00] hover:bg-[#b0e600] text-black font-extrabold rounded-full px-4 text-[13px] h-8 shadow-xs cursor-pointer"
              >
                {isRequestingPush ? "Enabling..." : "Enable"}
              </Button>
            )}
          </div>
        </div>

        {/* Master Toggle Card */}
        <div className="bg-card rounded-[24px] border border-border/60 p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3.5">
              <div className="p-2.5 bg-muted rounded-[14px] text-foreground shrink-0">
                <Bell className="h-5 w-5 text-foreground" />
              </div>
              <div>
                <span className="text-[15px] font-bold text-foreground block">Allow Notifications</span>
                <span className="text-[12px] text-muted-foreground block">Enable or disable all in-app alerts</span>
              </div>
            </div>

            {/* Toggle Switch */}
            <button
              type="button"
              onClick={() => updatePreference("enabled", !prefs.enabled)}
              disabled={isSaving}
              className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                prefs.enabled ? "bg-[#C5FF00]" : "bg-muted"
              }`}
            >
              <span
                className={`pointer-events-none inline-block h-6 w-6 transform rounded-full shadow-md ring-0 transition duration-200 ease-in-out ${
                  prefs.enabled ? "translate-x-5 bg-black" : "translate-x-0 bg-white dark:bg-zinc-300"
                }`}
              />
            </button>
          </div>
        </div>

        {/* Individual Notification Types */}
        <div className="space-y-2.5">
          <h3 className="text-[14px] font-semibold text-muted-foreground px-1">
            Notification Types
          </h3>

          <div className={`bg-card rounded-[24px] border border-border/60 shadow-sm overflow-hidden divide-y divide-border/60 transition-opacity ${
            prefs.enabled ? "opacity-100" : "opacity-50 pointer-events-none"
          }`}>
            {/* Ride Requests */}
            <div className="flex items-center justify-between p-4">
              <div className="flex items-center space-x-3.5">
                <div className="p-2.5 bg-secondary rounded-[14px] text-foreground shrink-0">
                  <MessageSquare className="h-5 w-5" />
                </div>
                <div>
                  <span className="text-[15px] font-bold text-foreground block">Ride Requests</span>
                  <span className="text-[12px] text-muted-foreground block">Alerts when someone requests a seat</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => updatePreference("rideRequests", !prefs.rideRequests)}
                disabled={!prefs.enabled || isSaving}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  prefs.rideRequests && prefs.enabled ? "bg-[#C5FF00]" : "bg-muted"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full shadow-md ring-0 transition duration-200 ease-in-out ${
                    prefs.rideRequests && prefs.enabled ? "translate-x-5 bg-black" : "translate-x-0 bg-white dark:bg-zinc-300"
                  }`}
                />
              </button>
            </div>

            {/* Request Updates */}
            <div className="flex items-center justify-between p-4">
              <div className="flex items-center space-x-3.5">
                <div className="p-2.5 bg-secondary rounded-[14px] text-foreground shrink-0">
                  <CheckCircle2 className="h-5 w-5" />
                </div>
                <div>
                  <span className="text-[15px] font-bold text-foreground block">Request Updates</span>
                  <span className="text-[12px] text-muted-foreground block">Alerts when a host accepts or rejects your request</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => updatePreference("requestUpdates", !prefs.requestUpdates)}
                disabled={!prefs.enabled || isSaving}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  prefs.requestUpdates && prefs.enabled ? "bg-[#C5FF00]" : "bg-muted"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full shadow-md ring-0 transition duration-200 ease-in-out ${
                    prefs.requestUpdates && prefs.enabled ? "translate-x-5 bg-black" : "translate-x-0 bg-white dark:bg-zinc-300"
                  }`}
                />
              </button>
            </div>

            {/* Ride Cancellations */}
            <div className="flex items-center justify-between p-4">
              <div className="flex items-center space-x-3.5">
                <div className="p-2.5 bg-secondary rounded-[14px] text-foreground shrink-0">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <div>
                  <span className="text-[15px] font-bold text-foreground block">Ride Cancellations</span>
                  <span className="text-[12px] text-muted-foreground block">Alerts when a host cancels a scheduled ride</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => updatePreference("rideCancellations", !prefs.rideCancellations)}
                disabled={!prefs.enabled || isSaving}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  prefs.rideCancellations && prefs.enabled ? "bg-[#C5FF00]" : "bg-muted"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full shadow-md ring-0 transition duration-200 ease-in-out ${
                    prefs.rideCancellations && prefs.enabled ? "translate-x-5 bg-black" : "translate-x-0 bg-white dark:bg-zinc-300"
                  }`}
                />
              </button>
            </div>

            {/* Request Cancellations */}
            <div className="flex items-center justify-between p-4">
              <div className="flex items-center space-x-3.5">
                <div className="p-2.5 bg-secondary rounded-[14px] text-foreground shrink-0">
                  <XCircle className="h-5 w-5" />
                </div>
                <div>
                  <span className="text-[15px] font-bold text-foreground block">Request Cancellations</span>
                  <span className="text-[12px] text-muted-foreground block">Alerts when a passenger cancels their request</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => updatePreference("requestCancellations", !prefs.requestCancellations)}
                disabled={!prefs.enabled || isSaving}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  prefs.requestCancellations && prefs.enabled ? "bg-[#C5FF00]" : "bg-muted"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full shadow-md ring-0 transition duration-200 ease-in-out ${
                    prefs.requestCancellations && prefs.enabled ? "translate-x-5 bg-black" : "translate-x-0 bg-white dark:bg-zinc-300"
                  }`}
                />
              </button>
            </div>
          </div>
        </div>
      </>
    )}
  </div>
</MobileShell>
)
}
