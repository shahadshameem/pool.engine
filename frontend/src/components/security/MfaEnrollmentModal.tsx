import { useState, useEffect } from "react"
import { Modal } from "../ui/modal"
import { Button } from "../ui/button"
import { Input } from "../ui/input"
import { MaterialIcon } from "../common/MaterialIcon"
import { useToast } from "../feedback/ToastContext"
import { useAuth } from "../../hooks/useAuth"
import { mfaService, createRecaptchaVerifier, formatToE164 } from "../../services/auth/mfaService"

interface MfaEnrollmentModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  isCurrentlyEnrolled: boolean
  currentPhoneMasked?: string
}

export function MfaEnrollmentModal({
  isOpen,
  onClose,
  onSuccess,
  isCurrentlyEnrolled,
  currentPhoneMasked
}: MfaEnrollmentModalProps) {
  const { user, profile } = useAuth()
  const { showToast } = useToast()

  const [mode, setMode] = useState<"enroll" | "unenroll">(isCurrentlyEnrolled ? "unenroll" : "enroll")
  const [step, setStep] = useState<"phone" | "otp">("phone")
  const [phoneNumber, setPhoneNumber] = useState("")
  const [verificationId, setVerificationId] = useState("")
  const [otpCode, setOtpCode] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [countdown, setCountdown] = useState(0)

  useEffect(() => {
    if (isOpen) {
      setMode(isCurrentlyEnrolled ? "unenroll" : "enroll")
      setStep("phone")
      setOtpCode("")
      setVerificationId("")
      // Pre-fill phone from user profile or auth
      const raw = profile?.phone || user?.phoneNumber || ""
      const digits = raw.replace(/\D/g, "").slice(-10)
      setPhoneNumber(digits ? `+91${digits}` : "+91")
    }
  }, [isOpen, isCurrentlyEnrolled, profile, user])

  // Countdown timer for resend OTP
  useEffect(() => {
    if (countdown > 0) {
      const timer = setTimeout(() => setCountdown(c => c - 1), 1000)
      return () => clearTimeout(timer)
    }
  }, [countdown])

  const handleSendOtp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!user) return

    const e164 = formatToE164(phoneNumber)
    if (!e164 || e164.length < 11) {
      showToast("Please enter a valid phone number with country code (e.g. +91 9876543210)", "error")
      return
    }

    setIsLoading(true)
    try {
      const verifier = createRecaptchaVerifier("mfa-enroll-recaptcha-container", true)
      const res = await mfaService.startPhoneEnrollment(user, e164, verifier)
      setVerificationId(res.verificationId)
      setStep("otp")
      setCountdown(30)
      showToast(`Verification SMS sent to ${res.formattedPhone}`, "info")
    } catch (err: any) {
      console.error("[MFA] Send enrollment OTP error:", err)
      showToast(err?.message || "Failed to send SMS verification code. Please try again.", "error")
    } finally {
      setIsLoading(false)
    }
  }

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!user || !verificationId) return
    if (!otpCode.trim() || otpCode.trim().length < 6) {
      showToast("Please enter the 6-digit SMS verification code", "error")
      return
    }

    setIsLoading(true)
    try {
      await mfaService.finishPhoneEnrollment(user, verificationId, otpCode.trim())
      showToast("SMS Multi-Factor Authentication successfully enabled!", "success")
      onSuccess()
      onClose()
    } catch (err: any) {
      console.error("[MFA] Finish enrollment error:", err)
      if (err?.code === "auth/invalid-verification-code") {
        showToast("Invalid code. Please check your SMS and try again.", "error")
      } else {
        showToast(err?.message || "Verification failed. Please try again.", "error")
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleUnenroll = async () => {
    if (!user) return
    setIsLoading(true)
    try {
      await mfaService.unenrollMfa(user)
      showToast("SMS Multi-Factor Authentication disabled.", "info")
      onSuccess()
      onClose()
    } catch (err: any) {
      console.error("[MFA] Unenroll error:", err)
      showToast(err?.message || "Failed to disable MFA. Please try again.", "error")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        mode === "unenroll"
          ? "Manage Two-Factor Authentication"
          : step === "otp"
            ? "Enter Verification Code"
            : "Set Up SMS Authentication"
      }
    >
      <div id="mfa-enroll-recaptcha-container" />

      {mode === "unenroll" ? (
        <div className="space-y-4 pt-2">
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 flex items-start gap-3">
            <MaterialIcon name="warning" className="text-xl text-amber-500 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-200/90 space-y-1">
              <p className="font-bold text-amber-400 text-sm">SMS 2FA is currently active</p>
              <p className="text-muted-foreground leading-relaxed">
                Enrolled Phone: <span className="font-mono text-foreground font-semibold">{currentPhoneMasked || "Registered Device"}</span>
              </p>
              <p className="text-muted-foreground leading-relaxed pt-1">
                Disabling SMS multi-factor authentication removes the second security step. You will only need your password to log in.
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-2 pt-2">
            <Button
              variant="danger"
              size="lg"
              className="w-full font-bold"
              disabled={isLoading}
              onClick={handleUnenroll}
            >
              {isLoading ? "Disabling..." : "Disable SMS 2FA"}
            </Button>
            <Button
              variant="secondary"
              size="default"
              className="w-full text-xs font-semibold"
              disabled={isLoading}
              onClick={() => {
                setMode("enroll")
                setStep("phone")
              }}
            >
              Change Phone Number
            </Button>
            <Button
              variant="outline"
              size="default"
              className="w-full text-xs"
              onClick={onClose}
            >
              Keep 2FA Enabled
            </Button>
          </div>
        </div>
      ) : step === "phone" ? (
        <form onSubmit={handleSendOtp} className="space-y-4 pt-2">
          <div className="bg-muted/50 border border-border/60 rounded-2xl p-4 space-y-2 text-xs">
            <div className="flex items-center gap-2 text-foreground font-bold text-sm">
              <MaterialIcon name="sms" className="text-lg text-emerald-500 dark:text-[#C5FF00]" />
              <span>Step 1: Enter your mobile phone</span>
            </div>
            <p className="text-muted-foreground leading-relaxed">
              We will send a 6-digit confirmation code via SMS to verify ownership of this number.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-foreground block">Phone Number (E.164 with Country Code)</label>
            <Input
              type="tel"
              placeholder="+91 98765 43210"
              value={phoneNumber}
              onChange={(e) => setPhoneNumber(e.target.value)}
              className="h-12 rounded-xl font-mono text-base tracking-wide"
              leftIcon={<MaterialIcon name="phone" className="text-base text-muted-foreground" />}
              autoFocus
            />
            <p className="text-[11px] text-muted-foreground">Standard carrier SMS rates may apply.</p>
          </div>

          <div className="flex flex-col gap-2 pt-2">
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full font-bold bg-[#C5FF00] text-black hover:opacity-90"
              disabled={isLoading || !phoneNumber.trim()}
            >
              {isLoading ? "Sending SMS..." : "Send Verification Code"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="default"
              className="w-full text-xs"
              onClick={onClose}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleVerifyOtp} className="space-y-4 pt-2">
          <div className="bg-muted/50 border border-border/60 rounded-2xl p-4 space-y-2 text-xs">
            <div className="flex items-center gap-2 text-foreground font-bold text-sm">
              <MaterialIcon name="mark_email_read" className="text-lg text-emerald-500 dark:text-[#C5FF00]" />
              <span>Step 2: Enter 6-digit SMS Code</span>
            </div>
            <p className="text-muted-foreground leading-relaxed">
              A text message with a 6-digit code has been sent to{" "}
              <span className="font-mono text-foreground font-semibold">{phoneNumber}</span>.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-foreground block">6-Digit Code</label>
            <Input
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="123456"
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
              className="h-14 rounded-xl font-mono text-2xl tracking-[0.4em] text-center"
              autoFocus
            />
          </div>

          <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
            <span>Didn&apos;t receive code?</span>
            <button
              type="button"
              disabled={countdown > 0 || isLoading}
              onClick={() => handleSendOtp()}
              className="font-bold text-foreground dark:text-[#C5FF00] hover:underline disabled:opacity-50 cursor-pointer"
            >
              {countdown > 0 ? `Resend in ${countdown}s` : "Resend Code"}
            </button>
          </div>

          <div className="flex flex-col gap-2 pt-2">
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full font-bold bg-[#C5FF00] text-black hover:opacity-90"
              disabled={isLoading || otpCode.trim().length < 6}
            >
              {isLoading ? "Verifying..." : "Confirm & Enable 2FA"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="default"
              className="w-full text-xs"
              onClick={() => setStep("phone")}
            >
              Change Phone Number
            </Button>
          </div>
        </form>
      )}
    </Modal>
  )
}
