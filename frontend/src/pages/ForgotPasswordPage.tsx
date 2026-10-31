import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { MaterialIcon } from "../components/common/MaterialIcon"

/**
 * Waymate uses passwordless Google Sign-In.
 * Passwords are never needed or stored.
 */
export function ForgotPasswordPage() {
  const navigate = useNavigate()

  useEffect(() => {
    // Keep URL clean
  }, [navigate])

  return (
    <MobileShell hideBottomNav className="flex flex-col justify-between pt-4">
      <div>
        <div className="flex items-center mb-6">
          <button
            onClick={() => navigate("/login")}
            className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
            aria-label="Back to Login"
          >
            <MaterialIcon name="arrow_back" className="text-[24px] text-foreground" />
          </button>
        </div>

        <div className="text-center py-8 space-y-4">
          <div className="w-16 h-16 rounded-full bg-[#C5FF00]/10 border border-[#C5FF00]/30 flex items-center justify-center mx-auto">
            <MaterialIcon name="verified_user" className="text-[32px] text-[#C5FF00]" />
          </div>

          <div className="space-y-2">
            <h1 className="text-edex-heading text-foreground font-bold">Passwordless Sign-In</h1>
            <p className="text-edex-meta text-muted-foreground max-w-xs mx-auto leading-relaxed">
              Waymate uses Google Sign-In for fast, secure authentication. Your account security is protected directly by Google. You no longer need to remember or reset separate passwords.
            </p>
          </div>
        </div>

        <Button
          variant="primary"
          size="lg"
          className="w-full h-[54px] rounded-2xl font-bold bg-[#C5FF00] text-black hover:opacity-90 mt-4 cursor-pointer"
          onClick={() => navigate("/login")}
        >
          Return to Sign In
        </Button>
      </div>

      <div className="text-center pb-6">
        <button
          onClick={() => navigate("/")}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          Return to Welcome Screen
        </button>
      </div>
    </MobileShell>
  )
}
