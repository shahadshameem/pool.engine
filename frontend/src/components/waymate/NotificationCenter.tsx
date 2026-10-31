import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Bell, X, Check, CheckCircle2, Car } from "lucide-react"
import { useNotifications } from "../../contexts/NotificationContext"
import { formatDistanceToNow } from "date-fns"

const formatTimeAgo = (createdAt: any) => {
  if (!createdAt) return "Just now"
  try {
    const millis = typeof createdAt.toMillis === "function" ? createdAt.toMillis() : (createdAt.seconds ? createdAt.seconds * 1000 : null)
    if (millis && !isNaN(millis)) {
      return formatDistanceToNow(millis, { addSuffix: true })
    }
  } catch (e) {}
  return "Just now"
}

export function NotificationCenter() {
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const { notifications, unreadCount, markAsRead, markAllAsRead } = useNotifications()

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        aria-label="Notifications"
        className="h-11 w-11 rounded-full bg-[#F4F4F5] hover:bg-[#E4E4E7] border border-[#E4E4E7]/60 flex items-center justify-center relative shadow-2xs transition-colors cursor-pointer"
      >
        <Bell className="h-5 w-5 text-[#18181B]" strokeWidth={2} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 h-5 min-w-[20px] px-1 bg-[#1D1D1F] text-[#FFFFFF] text-[11px] font-bold rounded-full border-2 border-[#FFFFFF] flex items-center justify-center shadow-2xs">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background animate-in slide-in-from-bottom-full duration-300 sm:items-end sm:justify-start sm:bg-black/40 sm:p-4">
          <div className="flex h-full w-full flex-col bg-[#FFFFFF] sm:h-auto sm:max-h-[85vh] sm:w-[400px] sm:rounded-[18px] sm:shadow-[0_12px_40px_rgba(0,0,0,0.12)] border border-[#1D1D1F]/15">

            <div className="flex items-center justify-between border-b border-[#1D1D1F]/10 px-4 py-4">
              <div className="flex items-center space-x-2">
                <h2 className="text-[20px] font-bold text-[#1D1D1F]">Notifications</h2>
                {unreadCount > 0 && (
                  <span className="bg-[#1D1D1F] text-[#FFFFFF] text-[12px] font-bold px-2 py-0.5 rounded-[980px]">
                    {unreadCount} new
                  </span>
                )}
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="h-8 w-8 rounded-full bg-[#F2F2F7] flex items-center justify-center text-[#1D1D1F]"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
                  <Bell className="h-8 w-8 mb-2 opacity-20 text-[#1D1D1F]" />
                  <p className="text-[14px] font-medium text-[#1D1D1F]/60">No notifications yet</p>
                </div>
              ) : (
                <div className="divide-y divide-[#1D1D1F]/10">
                  {notifications.map(notif => (
                    <div
                      key={notif.id}
                      onClick={() => {
                        if (notif.id && !notif.read) markAsRead(notif.id)
                        const targetRideId = notif.matchedRideId || notif.rideId
                        if (targetRideId) {
                          setIsOpen(false)
                          navigate(`/rides/${targetRideId}`)
                        }
                      }}
                      className={`p-4 transition-colors cursor-pointer ${!notif.read ? "bg-[#F2F2F7]" : "hover:bg-[#F2F2F7]/50"}`}
                    >
                      <div className="flex gap-3">
                        <div className="shrink-0 mt-1">
                          {notif.type === "request_accepted" ? (
                            <div className="h-8 w-8 rounded-full bg-[#1D1D1F] flex items-center justify-center">
                              <CheckCircle2 className="h-5 w-5 text-[#FFFFFF]" />
                            </div>
                          ) : notif.type === "ride_match_found" ? (
                            <div className="h-8 w-8 rounded-full bg-[#1D1D1F] flex items-center justify-center">
                              <Car className="h-4 w-4 text-[#FFFFFF]" />
                            </div>
                          ) : notif.type === "ride_request" ? (
                            <div className="h-8 w-8 rounded-full bg-[#1D1D1F] flex items-center justify-center">
                              <Bell className="h-4 w-4 text-[#FFFFFF]" />
                            </div>
                          ) : notif.type === "request_rejected" || notif.type === "ride_cancelled" ? (
                            <div className="h-8 w-8 rounded-full bg-[#FF3B301A] flex items-center justify-center">
                              <X className="h-5 w-5 text-[#FF3B30]" />
                            </div>
                          ) : (
                            <div className="h-8 w-8 rounded-full bg-[#F2F2F7] flex items-center justify-center">
                              <Check className="h-5 w-5 text-[#1D1D1F]" />
                            </div>
                          )}
                        </div>
                        <div className="flex-1 space-y-1">
                          <p className="text-[15px] font-bold text-[#1D1D1F] leading-tight">{notif.title}</p>
                          <p className="text-[14px] text-[#1D1D1F]/70 leading-snug">{notif.message}</p>
                          <p className="text-[12px] text-[#1D1D1F]/50 font-normal pt-1">
                            {formatTimeAgo(notif.createdAt)}
                          </p>
                        </div>
                        {!notif.read && (
                          <div className="shrink-0">
                            <div className="h-2.5 w-2.5 rounded-full bg-[#1D1D1F] mt-1.5" />
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {unreadCount > 0 && (
              <div className="p-4 border-t border-[#1D1D1F]/10">
                <button
                  onClick={markAllAsRead}
                  className="w-full text-center text-[14px] font-semibold text-[#1D1D1F] py-2 hover:bg-[#F2F2F7] rounded-[980px] transition-colors cursor-pointer"
                >
                  Mark all as read
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
