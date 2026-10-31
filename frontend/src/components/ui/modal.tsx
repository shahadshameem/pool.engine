import * as React from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
}

export function Modal({ isOpen, onClose, title, children }: ModalProps) {
  if (!isOpen) return null

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Bottom Sheet Modal */}
      <div className="fixed inset-x-0 bottom-0 z-[100] mx-auto w-full max-w-md animate-in slide-in-from-bottom-full duration-300">
        <div className="flex flex-col overflow-hidden rounded-t-[32px] bg-background shadow-2xl max-h-[calc(100vh-env(safe-area-inset-top,0px)-env(safe-area-inset-bottom,0px)-32px)]">
          {/* Handle */}
          <div className="flex w-full items-center justify-center pt-4 pb-2">
            <div className="h-1.5 w-12 rounded-full bg-muted" />
          </div>

          <div className="flex items-center justify-between px-6 pb-2 shrink-0">
            {title ? (
              <h2 className="text-xl font-bold">{title}</h2>
            ) : <div />}
            <button
              onClick={onClose}
              className="rounded-full p-2 hover:bg-muted active:bg-muted/80 transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="px-6 pb-[calc(2rem+env(safe-area-inset-bottom,0px))] pt-2 overflow-y-auto">
            {children}
          </div>
        </div>
      </div>
    </>,
    document.body
  )
}
