import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { EmptyState } from "../components/feedback/EmptyState"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { useToast } from "../components/feedback/ToastContext"
import { notificationService } from "../services/notification/notificationService"
import type { AppNotification } from "../services/notification/notificationService"

export function ActivityPage() {
  const navigate = useNavigate()
  const { goBack } = useBackNavigation()
  const { user, loading: authLoading } = useAuth()
  const { showToast } = useToast()

  const [isLoading, setIsLoading] = useState(true)
  const [notifications, setNotifications] = useState<AppNotification[]>([])

  useEffect(() => {
    if (!authLoading && !user) {
      navigate("/login", { replace: true })
      return
    }

    async function loadNotifications() {
      if (!user) return
      try {
        const notifs = await notificationService.getUserNotifications(user.uid)
        setNotifications(notifs)
      } catch (error) {
        console.error("Failed to load notifications", error)
        showToast("Couldn't load your notifications.", "error")
      } finally {
        setIsLoading(false)
      }
    }

    loadNotifications()
  }, [user, authLoading, navigate])

  const handleMarkAsRead = async (id: string) => {
    const success = await notificationService.markNotificationAsRead(id)
    if (success) {
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
    }
  }

  const handleMarkAllAsRead = async () => {
    if (!user) return
    const success = await notificationService.markAllNotificationsAsRead(user.uid)
    if (success) {
      setNotifications(prev => prev.map(n => ({ ...n, read: true })))
      showToast("All marked as read", "success")
    }
  }

  const isActivityLoading = authLoading || isLoading
  const unreadCount = notifications.filter(n => !n.read).length
  const hasNotifications = notifications.length > 0

  const getIconForType = (type: string) => {
    switch (type) {
      case "request_accepted":
        return <MaterialIcon name="check_circle" className="text-[22px] text-[#25D366]" />
      case "request_rejected":
      case "ride_cancelled":
        return <MaterialIcon name="cancel" className="text-[22px] text-[#E02424]" />
      case "ride_request":
        return <MaterialIcon name="directions_car" className="text-[22px] text-foreground" />
      default:
        return <MaterialIcon name="notifications" className="text-[22px] text-muted-foreground" />
    }
  }

  return (
    <MobileShell className="flex flex-col space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <button
            onClick={goBack}
            className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
            aria-label="Back"
          >
            <MaterialIcon name="arrow_back" className="text-[24px] text-foreground" />
          </button>
          <h1 className="text-edex-heading text-foreground font-bold">Notifications</h1>
        </div>

        {unreadCount > 0 && (
          <button
            onClick={handleMarkAllAsRead}
            className="text-[13px] font-bold text-foreground underline underline-offset-4 cursor-pointer"
          >
            Mark all read
          </button>
        )}
      </div>

      {/* Notifications List */}
      <div className="space-y-3">
        {isActivityLoading ? (
          <>
            <div className="h-[72px] w-full bg-card border border-border/60 rounded-[20px] animate-pulse p-4 flex items-center space-x-3.5">
              <div className="h-10 w-10 rounded-full bg-muted shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-4 w-3/4 bg-muted rounded-md" />
                <div className="h-3 w-1/2 bg-muted/60 rounded-md" />
              </div>
            </div>
            <div className="h-[72px] w-full bg-card border border-border/60 rounded-[20px] animate-pulse p-4 flex items-center space-x-3.5">
              <div className="h-10 w-10 rounded-full bg-muted shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-4 w-2/3 bg-muted rounded-md" />
                <div className="h-3 w-1/3 bg-muted/60 rounded-md" />
              </div>
            </div>
          </>
        ) : !hasNotifications ? (
          <div className="pt-6">
            <EmptyState
              icon={<MaterialIcon name="notifications_off" className="text-[32px] text-muted-foreground/60" />}
              title="No notifications yet"
              description="When someone requests a seat or accepts your request, it will show up here."
              actionLabel="Find a Ride"
              onAction={() => navigate("/rides/search")}
            />
          </div>
        ) : (
          notifications.map((notif) => (
            <div
              key={notif.id}
              onClick={() => {
                if (!notif.read && notif.id) handleMarkAsRead(notif.id)
                if (notif.rideId) navigate(`/rides/${notif.rideId}`)
              }}
              className={`bg-card border rounded-[20px] p-4 flex items-start space-x-3.5 cursor-pointer transition-all ${
                notif.read ? "border-border/60" : "border-[#C5FF00] bg-muted/60 shadow-xs"
              }`}
            >
              <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center shrink-0">
                {getIconForType(notif.type)}
              </div>

              <div className="flex-1 min-w-0 pr-2">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-[15px] text-foreground truncate">{notif.title}</h3>
                  {!notif.read && (
                    <div className="h-2 w-2 rounded-full bg-[#25D366] shrink-0" />
                  )}
                </div>
                <p className="text-[13px] text-muted-foreground mt-0.5">{notif.message}</p>
              </div>
            </div>
          ))
        )}
      </div>
    </MobileShell>
  )
}
