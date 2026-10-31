import { X } from "lucide-react"
import { createPortal } from "react-dom"

interface ModalShellProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  className?: string
  headerClassName?: string
  hideHandle?: boolean
  hideHeaderBorder?: boolean
}

export function ModalShell({
  isOpen,
  onClose,
  title,
  children,
  className = "",
  headerClassName = "",
  hideHandle = false,
  hideHeaderBorder = false
}: ModalShellProps) {
  if (!isOpen) return null

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
        onClick={onClose}
      />

      {/* Modal Sheet */}
      <div className="fixed inset-x-0 bottom-0 z-[100] mx-auto w-full max-w-md animate-in slide-in-from-bottom-full duration-300">
        <div className={`flex flex-col overflow-hidden rounded-t-[32px] bg-card border-t border-border/60 text-foreground shadow-2xl max-h-[calc(100dvh-env(safe-area-inset-top,0px)-24px)] ${className}`}>

          {/* Handle */}
          {!hideHandle && (
            <div className="flex w-full items-center justify-center pt-3 pb-1">
              <div className="h-1.5 w-12 rounded-full bg-border" />
            </div>
          )}

          {/* Header */}
          <div className={`flex items-center justify-between px-6 pt-5 pb-3 ${hideHeaderBorder ? '' : 'border-b border-border/40'} shrink-0 ${headerClassName}`}>
            {title ? (
              <h2 className="text-[24px] sm:text-[26px] font-black tracking-tight text-foreground">{title}</h2>
            ) : <div />}
            <button
              onClick={onClose}
              className="h-9 w-9 rounded-full bg-muted text-foreground hover:bg-muted/80 transition-colors flex items-center justify-center cursor-pointer"
            >
              <X className="h-5 w-5 stroke-[2.5]" />
            </button>
          </div>

          {/* Content */}
          <div className="px-6 pb-[calc(2rem+env(safe-area-inset-bottom,0px))] pt-1 overflow-y-auto">
            {children}
          </div>

        </div>
      </div>
    </>,
    document.body
  )
}
