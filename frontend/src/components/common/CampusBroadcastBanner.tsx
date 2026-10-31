import { useEffect, useState } from "react"
import { doc, onSnapshot } from "firebase/firestore"
import { db } from "../../config/firebase"
import { adminService, type SystemBanner } from "../../services/admin/adminService"
import { MaterialIcon } from "./MaterialIcon"

export function CampusBroadcastBanner() {
  const [banner, setBanner] = useState<SystemBanner | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    let mounted = true

    // Initial fetch from adminService as immediate fallback
    adminService.getSystemBanner().then(data => {
      if (mounted && data && data.enabled && data.message) {
        setBanner(data)
      }
    }).catch(() => {})

    // Real-time Firestore subscription for emergency & advisory broadcast updates
    const bannerDocRef = doc(db, "systemConfig", "broadcastBanner")
    const unsubscribe = onSnapshot(
      bannerDocRef,
      (docSnap) => {
        if (!mounted) return
        if (docSnap.exists()) {
          const data = docSnap.data() as SystemBanner
          setBanner(prev => {
            // Reset dismissal when message content, alert priority, or enabled flag changes
            if (!prev || prev.message !== data.message || prev.type !== data.type || prev.enabled !== data.enabled) {
              setDismissed(false)
            }
            return data
          })
        }
      },
      (err) => {
        console.warn("[CampusBroadcastBanner] Real-time snapshot listener error:", err)
      }
    )

    return () => {
      mounted = false
      unsubscribe()
    }
  }, [])

  if (!banner || !banner.enabled || dismissed || !banner.message) return null

  return (
    <div
      className={`w-full px-4 py-3 rounded-2xl flex items-center justify-between gap-3 text-xs font-medium shadow-md transition-all mb-4 ${
        banner.type === "alert"
          ? "bg-red-600 text-white font-bold animate-pulse border-2 border-red-400"
          : banner.type === "warning"
          ? "bg-[#C5FF00] text-black font-extrabold border border-black/10"
          : "bg-black text-white dark:bg-card dark:text-foreground border border-border/40"
      }`}
    >
      <div className="flex items-center gap-2.5 min-w-0 flex-1">
        <MaterialIcon
          name={banner.type === "alert" ? "emergency" : banner.type === "warning" ? "warning" : "campaign"}
          className="text-lg shrink-0"
        />
        <div className="min-w-0 flex-1">
          {banner.type === "alert" && (
            <span className="block text-[10px] uppercase tracking-widest font-black text-red-200">
              CAMPUS EMERGENCY ALERT
            </span>
          )}
          <p className="truncate leading-tight text-[13px]">{banner.message}</p>
        </div>
      </div>

      <button
        onClick={() => setDismissed(true)}
        className="opacity-80 hover:opacity-100 shrink-0 text-current p-1 rounded-full hover:bg-black/10 transition-colors cursor-pointer"
        aria-label="Dismiss alert"
      >
        <MaterialIcon name="close" className="text-base" />
      </button>
    </div>
  )
}
