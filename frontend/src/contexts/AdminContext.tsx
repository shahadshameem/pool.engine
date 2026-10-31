import { createContext, useContext, useState, useEffect, type ReactNode } from "react"
import { AuthContext } from "./AuthContext"
import { mfaService } from "../services/auth/mfaService"

interface AdminContextType {
  isAdmin: boolean
  isDevBypass: boolean
  toggleDevBypass: () => void
  adminEmail: string
  adminUid: string
  refreshTrigger: number
  triggerRefresh: () => void
  hasMfaEnrolled: boolean
}

// Configurable admin emails from environment variables (prevents bundling personal emails into production JS)
const ENV_ADMIN_EMAILS: string[] = ((import.meta.env.VITE_ADMIN_EMAILS as string) || "")
  .split(",")
  .map(e => e.trim().toLowerCase())
  .filter(Boolean)

export const AdminContext = createContext<AdminContextType>({
  isAdmin: false,
  isDevBypass: false,
  toggleDevBypass: () => {},
  adminEmail: "",
  adminUid: "",
  refreshTrigger: 0,
  triggerRefresh: () => {},
  hasMfaEnrolled: false
})

const isLocalDev = Boolean(
  import.meta.env.DEV &&
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
)

export const AdminProvider = ({ children }: { children: ReactNode }) => {
  const { user, profile } = useContext(AuthContext)
  const [isDevBypass, setIsDevBypass] = useState<boolean>(() => {
    if (!isLocalDev) {
      if (typeof window !== "undefined") {
        try {
          localStorage.removeItem("wm_admin_bypass")
        } catch {
          // ignore
        }
      }
      return false
    }
    return localStorage.getItem("wm_admin_bypass") === "true"
  })
  const [refreshTrigger, setRefreshTrigger] = useState(0)

  const triggerRefresh = () => setRefreshTrigger(prev => prev + 1)

  const toggleDevBypass = () => {
    if (!isLocalDev) return
    setIsDevBypass(prev => {
      const next = !prev
      localStorage.setItem("wm_admin_bypass", String(next))
      return next
    })
  }

  const [hasAdminClaim, setHasAdminClaim] = useState<boolean>(false)

  useEffect(() => {
    if (user && typeof user.getIdTokenResult === "function") {
      user.getIdTokenResult()
        .then((result) => {
          setHasAdminClaim(Boolean(result.claims?.admin))
        })
        .catch(() => setHasAdminClaim(false))
    } else {
      setHasAdminClaim(false)
    }
  }, [user])

  // Determine if active user is an authorized admin
  const userEmail = (user?.email || profile?.email || "").toLowerCase().trim()
  const isEnvAdmin = ENV_ADMIN_EMAILS.length > 0 && ENV_ADMIN_EMAILS.includes(userEmail)
  const hasAdminRole = (profile as any)?.role === "admin" || (profile as any)?.admin === true

  // Grant access strictly if user is verified admin (custom claim or role), in env whitelist, OR in local development bypass
  const isAdmin = isEnvAdmin || hasAdminRole || hasAdminClaim || (isLocalDev && isDevBypass)

  const adminEmail = userEmail || (isLocalDev && isDevBypass ? "dev-preview@waymate.app" : "")
  const adminUid = user?.uid || (isLocalDev && isDevBypass ? "dev-admin-uid" : "")
  const hasMfaEnrolled = mfaService.isMfaEnrolled(user)

  return (
    <AdminContext.Provider
      value={{
        isAdmin,
        isDevBypass,
        toggleDevBypass,
        adminEmail,
        adminUid,
        refreshTrigger,
        triggerRefresh,
        hasMfaEnrolled
      }}
    >
      {children}
    </AdminContext.Provider>
  )
}

export const useAdmin = () => useContext(AdminContext)
