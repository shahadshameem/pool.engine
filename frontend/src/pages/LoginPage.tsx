import { useState, useEffect } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { useToast } from "../components/feedback/ToastContext"
import { useAuth } from "../hooks/useAuth"
import { authService } from "../services/auth/authService"
import { userService } from "../services/user/userService"
import { getSafeRedirectPath } from "../utils/redirectUrl"
import { setDevMockEnabled } from "../utils/devMock"
import { useSEO } from "../hooks/useSEO"

/**
 * Official Google 4-Color Vector Logo
 */
function GoogleLogo({ className = "w-5 h-5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
        fill="#EA4335"
      />
    </svg>
  )
}

/**
 * Waymate Primary Authentication: Sign in with Google.
 * Instant, passwordless authentication using verified college or personal Google credentials.
 */
export function LoginPage() {
  useSEO({
    title: "Sign In to WayMate Campus",
    description: "Sign in with Google to access WayMate (wmate.app) college ridesharing and carpool network.",
    canonicalPath: "/login",
  })

  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { user, loading: authLoading } = useAuth()
  const { showToast } = useToast()

  const [isLoading, setIsLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState("")

  // Handle redirect callback (if mobile browser completed redirect flow)
  useEffect(() => {
    authService.handleRedirectResult().then((redirectUser) => {
      if (redirectUser) {
        showToast("Signed in successfully!", "success")
        handlePostSignInNavigation(redirectUser.uid)
      }
    })
  }, [])

  // If user is already authenticated, redirect to destination
  useEffect(() => {
    if (!authLoading && user) {
      handlePostSignInNavigation(user.uid)
    }
  }, [user, authLoading])

  const handlePostSignInNavigation = async (uid: string) => {
    try {
      const userProfile = await userService.getUserProfile(uid, true)
      const isIncomplete =
        !userProfile?.department ||
        !userProfile?.year ||
        !userProfile?.gender

      if (isIncomplete) {
        navigate("/onboarding", { replace: true })
      } else {
        const redirect = getSafeRedirectPath(searchParams.get("redirect"), "/home")
        navigate(redirect, { replace: true })
      }
    } catch {
      const redirect = getSafeRedirectPath(searchParams.get("redirect"), "/home")
      navigate(redirect, { replace: true })
    }
  }

  const handleGoogleSignIn = async () => {
    if (isLoading) return
    setIsLoading(true)
    setErrorMsg("")

    try {
      const { user: signedInUser } = await authService.signInWithGoogle()
      showToast("Signed in successfully!", "success")
      await handlePostSignInNavigation(signedInUser.uid)
    } catch (err: any) {
      const code = err?.code || ""
      if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") {
        // User voluntarily dismissed popup
        setErrorMsg("")
      } else {
        const msg = err?.message || "Failed to sign in with Google. Please try again."
        setErrorMsg(msg)
        showToast(msg, "error")
      }
    } finally {
      setIsLoading(false)
    }
  }

  // Quick Developer / Local Demo bypass (strictly disabled in production builds)
  const handleDevDemoSignIn = async () => {
    if (!import.meta.env.DEV) {
      console.error("[Security] Dev demo login is disabled in production environments.")
      return
    }
    if (isLoading) return
    setIsLoading(true)
    try {
      const ok = setDevMockEnabled(true)
      if (!ok) return
      showToast("Signed in as Demo Student!", "success")
      const redirect = getSafeRedirectPath(searchParams.get("redirect"), "/home")
      navigate(redirect, { replace: true })
      window.location.reload()
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <MobileShell hideBottomNav className="flex flex-col justify-between pt-2 min-h-screen">
      <div className="flex-1 flex flex-col justify-between">
        <div>
          {/* Header / Back */}
          <div className="flex items-center mb-6">
            <button
              type="button"
              onClick={() => navigate("/")}
              className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
              aria-label="Back to Welcome"
            >
              <MaterialIcon name="arrow_back" className="text-[24px] text-foreground" />
            </button>
          </div>

          {/* Badge & Heading */}
          <div className="mb-8 space-y-3">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#C5FF00]/15 border border-[#C5FF00]/30 text-xs font-bold text-foreground">
              <MaterialIcon name="school" className="text-sm text-[#C5FF00]" />
              <span>Verified Campus Community</span>
            </div>

            <h1 className="text-[28px] md:text-[32px] text-foreground font-extrabold tracking-tight leading-tight">
              Sign in to Waymate
            </h1>
            <p className="text-[15px] text-muted-foreground leading-relaxed">
              Connect with peers, pool rides, and commute safely. Use your Google account to get started in seconds.
            </p>
          </div>

          {/* Error Banner */}
          {errorMsg && (
            <div className="mb-6 p-4 rounded-2xl bg-destructive/10 border border-destructive/20 text-destructive text-[13px] font-semibold flex items-start gap-2.5">
              <MaterialIcon name="error_outline" className="text-[18px] shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Primary Action: Google Sign-In Button */}
          <div className="space-y-4">
            <button
              type="button"
              onClick={handleGoogleSignIn}
              disabled={isLoading}
              className="w-full h-[58px] rounded-2xl bg-card border border-border/80 hover:bg-muted font-bold text-[16px] text-foreground flex items-center justify-center gap-3 transition-all active:scale-[0.99] shadow-xs cursor-pointer disabled:opacity-50"
            >
              <GoogleLogo className="w-5 h-5 shrink-0" />
              <span>{isLoading ? "Signing in..." : "Continue with Google"}</span>
            </button>

            {/* Dev Mode Demo Bypass */}
            {import.meta.env.DEV && (
              <button
                type="button"
                onClick={handleDevDemoSignIn}
                disabled={isLoading}
                className="w-full py-2 text-xs font-medium text-muted-foreground hover:text-foreground text-center cursor-pointer transition-colors"
              >
                Developer mode: Continue as Demo Student
              </button>
            )}
          </div>
        </div>

        {/* Footer / Trust & Policy Notice */}
        <div className="pt-8 pb-6 text-center space-y-2">
          <p className="text-[12px] text-muted-foreground leading-relaxed max-w-xs mx-auto">
            By signing in, you agree to Waymate&apos;s{" "}
            <a href="/terms" className="underline underline-offset-2 hover:text-foreground font-medium">Terms</a>
            {" "}and{" "}
            <a href="/privacy" className="underline underline-offset-2 hover:text-foreground font-medium">Privacy Policy</a>.
          </p>
        </div>
      </div>
    </MobileShell>
  )
}
