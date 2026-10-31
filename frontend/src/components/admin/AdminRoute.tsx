import type { ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { useAdmin } from "../../contexts/AdminContext"
import { useAuth } from "../../hooks/useAuth"
import { MaterialIcon } from "../common/MaterialIcon"

interface AdminRouteProps {
  children: ReactNode
}

export function AdminRoute({ children }: AdminRouteProps) {
  const { isAdmin, isDevBypass, toggleDevBypass } = useAdmin()
  const { user, loading, profileLoading } = useAuth()
  const navigate = useNavigate()

  // 1. Loading state while checking authentication & Firestore profile
  if (loading || profileLoading) {
    return (
      <div className="min-h-screen bg-[#F4F4F6] flex items-center justify-center p-4">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 rounded-full border-3 border-gray-300 border-t-black animate-spin mx-auto" />
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Verifying Admin Authorization...
          </p>
        </div>
      </div>
    )
  }

  // 2. Unauthenticated: Prompt to log in
  if (!user && !isDevBypass) {
    return (
      <div className="min-h-screen bg-[#F4F4F6] flex items-center justify-center p-4">
        <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-black/10 p-8 text-center space-y-6">
          <div className="w-16 h-16 rounded-full bg-amber-50 text-amber-600 flex items-center justify-center mx-auto">
            <MaterialIcon name="lock" className="text-3xl text-amber-600" />
          </div>

          <div className="space-y-2">
            <h1 className="text-2xl font-bold text-black tracking-tight">Admin Sign-In Required</h1>
            <p className="text-sm text-gray-600">
              This area is restricted to authorized WayMate campus administrators. Please sign in with an administrator account to continue.
            </p>
          </div>

          <div className="space-y-3 pt-2">
            <button
              onClick={() => navigate("/login")}
              className="w-full py-3 px-4 rounded-xl bg-black hover:bg-neutral-800 text-[#C5FF00] font-semibold text-sm transition-all shadow-sm flex items-center justify-center gap-2 cursor-pointer"
            >
              <MaterialIcon name="login" className="text-lg" />
              <span>Sign In with Admin Account</span>
            </button>

            <button
              onClick={() => navigate("/home")}
              className="w-full py-2.5 px-4 rounded-xl border border-gray-200 hover:bg-gray-50 text-gray-700 font-medium text-sm transition-all cursor-pointer"
            >
              Return to Student App
            </button>
          </div>
        </div>
      </div>
    )
  }

  // 3. Authenticated but unauthorized: 403 Forbidden
  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-[#F4F4F6] flex items-center justify-center p-4">
        <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-red-200 p-8 text-center space-y-6">
          <div className="w-16 h-16 rounded-full bg-red-50 text-red-600 flex items-center justify-center mx-auto">
            <MaterialIcon name="gpp_bad" className="text-3xl text-red-600" />
          </div>

          <div className="space-y-2">
            <h1 className="text-2xl font-bold text-red-600 tracking-tight">403 — Access Denied</h1>
            <p className="text-sm text-gray-600">
              Your account does not have administrator privileges to access the WayMate Central Management Portal.
            </p>
          </div>

          <div className="bg-red-50/70 border border-red-100 rounded-xl p-3.5 text-xs text-gray-600 font-mono break-all text-left">
            Current account: <span className="text-black font-semibold">{user?.email || "Unknown"}</span>
          </div>

          <div className="space-y-3 pt-2">
            <button
              onClick={() => navigate("/home")}
              className="w-full py-3 px-4 rounded-xl bg-black hover:bg-neutral-800 text-white font-semibold text-sm transition-all shadow-sm cursor-pointer"
            >
              Return to Student App
            </button>
          </div>

          {/* Dev Mode toggle strictly on localhost dev environment */}
          {import.meta.env.DEV && window.location.hostname === "localhost" && (
            <div className="pt-4 border-t border-dashed border-gray-200">
              <button
                onClick={() => toggleDevBypass()}
                className="text-xs text-amber-600 hover:underline font-mono"
              >
                [Dev Only] Enable Local Dev Bypass
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }

  return <>{children}</>
}
