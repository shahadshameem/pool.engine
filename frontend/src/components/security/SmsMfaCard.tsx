import { useState, useEffect, useCallback } from "react"
import { useAuth } from "../../hooks/useAuth"
import { mfaService } from "../../services/auth/mfaService"
import { MfaEnrollmentModal } from "./MfaEnrollmentModal"

interface SmsMfaCardProps {
  className?: string
  showAsAdminOps?: boolean
}

export function SmsMfaCard({ className = "", showAsAdminOps = false }: SmsMfaCardProps) {
  const { user } = useAuth()
  const [isEnrolled, setIsEnrolled] = useState<boolean>(false)
  const [phoneMasked, setPhoneMasked] = useState<string>("")
  const [isModalOpen, setIsModalOpen] = useState(false)

  const checkMfaStatus = useCallback(() => {
    if (!user) {
      setIsEnrolled(false)
      setPhoneMasked("")
      return
    }

    const enrolled = mfaService.isMfaEnrolled(user)
    setIsEnrolled(enrolled)

    const factors = mfaService.getEnrolledFactors(user)
    if (factors.length > 0) {
      const phone = (factors[0] as any).phoneNumber || ""
      if (phone) {
        // Mask e.g. +91 98••••5432
        const masked = phone.replace(/(\+\d{2})\s*(\d{2})(\d+)(\d{4})/, "$1 $2••••$4")
        setPhoneMasked(masked)
      } else {
        setPhoneMasked("Registered Phone")
      }
    } else {
      setPhoneMasked("")
    }
  }, [user])

  useEffect(() => {
    checkMfaStatus()
  }, [checkMfaStatus])

  return (
    <>
      <div
        className={`bg-[#1c1c1f] dark:bg-[#151619] border border-border/60 rounded-[20px] p-5 md:p-6 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm transition-all ${className}`}
      >
        <div className="space-y-1.5 flex-1 min-w-0 pr-2">
          {/* Title */}
          <h3 className="text-[17px] font-bold text-white tracking-tight">
            SMS multi-factor authentication
          </h3>

          {/* Status */}
          <div className="flex items-center gap-1.5 text-[14px]">
            <span className="text-zinc-400 font-medium">Status:</span>
            <span
              className={`font-semibold ${
                isEnrolled ? "text-[#22c55e]" : "text-zinc-400"
              }`}
            >
              {isEnrolled ? "Enabled" : "Disabled"}
            </span>
            {isEnrolled && phoneMasked && (
              <span className="text-xs text-zinc-500 font-mono ml-1">
                ({phoneMasked})
              </span>
            )}
          </div>

          {/* Explanatory Body */}
          <p className="text-[13px] md:text-[14px] text-zinc-400 leading-relaxed max-w-2xl pt-0.5">
            {showAsAdminOps
              ? "Require two-step SMS verification for administrative actions and campus console access. Once configured, administrators sign in with a one-time SMS security code."
              : "Allow your users to add an extra layer of security to their account. Once it's enabled, integrated and configured, users can sign in to their account in two steps using SMS."}{" "}
            <a
              href="https://firebase.google.com/docs/auth/web/multi-factor"
              target="_blank"
              rel="noreferrer"
              className="text-[#60a5fa] hover:text-[#93c5fd] inline-flex items-center gap-0.5 underline underline-offset-2 ml-1"
            >
              <span>Learn more</span>
              <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </p>
        </div>

        {/* Change / Enable Pill Button */}
        <div className="shrink-0 pt-1 md:pt-0">
          <button
            type="button"
            onClick={() => setIsModalOpen(true)}
            className="w-full md:w-auto px-6 py-2 rounded-full border border-zinc-700 bg-zinc-800/90 hover:bg-zinc-700 text-white font-medium text-[14px] shadow-xs active:scale-95 transition-all cursor-pointer flex items-center justify-center gap-1.5"
          >
            {isEnrolled ? "Change" : "Enable"}
          </button>
        </div>
      </div>

      <MfaEnrollmentModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={checkMfaStatus}
        isCurrentlyEnrolled={isEnrolled}
        currentPhoneMasked={phoneMasked}
      />
    </>
  )
}
