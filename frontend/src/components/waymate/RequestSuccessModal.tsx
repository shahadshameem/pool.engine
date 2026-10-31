import { useEffect } from "react"
import { Check } from "lucide-react"
import { ModalShell } from "../common/ModalShell"

export interface RequestSuccessModalProps {
  isOpen: boolean
  onClose: () => void
  hostName: string
}

export function RequestSuccessModal({ isOpen, onClose, hostName }: RequestSuccessModalProps) {
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => {
        onClose()
      }, 2500)
      return () => clearTimeout(timer)
    }
  }, [isOpen, onClose])

  return (
    <ModalShell isOpen={isOpen} onClose={onClose}>
      <div className="flex flex-col items-center py-4 text-center space-y-4">
        {/* Animated Checkmark Circle */}
        <div className="my-2 flex h-20 w-20 items-center justify-center rounded-full bg-[#E52E3D] text-white shadow-[0_4px_20px_rgba(229,46,61,0.3)] animate-in zoom-in duration-300">
          <Check className="h-10 w-10 stroke-[3]" />
        </div>

        {/* Heading */}
        <div className="space-y-1">
          <h2 className="text-[22px] font-extrabold tracking-tight text-[#111111]">
            Request Sent
          </h2>
          <p className="text-[14px] font-medium text-[#777777] max-w-[280px] leading-snug mx-auto">
            Your request has been sent to <span className="font-extrabold text-[#111111]">{hostName}</span>.
          </p>
        </div>

        {/* Done Button */}
        <button
          onClick={onClose}
          className="w-full h-13 bg-[#E52E3D] text-white font-extrabold text-[15px] rounded-full hover:bg-[#D02533] active:scale-[0.98] transition-all shadow-xs cursor-pointer mt-2"
        >
          Done
        </button>
      </div>
    </ModalShell>
  )
}
