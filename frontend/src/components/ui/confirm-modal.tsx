import { Modal } from "./modal"
import { AlertTriangle } from "lucide-react"
import { Button } from "./button"

interface ConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description: string
  confirmText?: string
  cancelText?: string
  variant?: "default" | "destructive"
  isLoading?: boolean
}

export function ConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = "Confirm",
  cancelText = "Cancel",
  isLoading = false
}: ConfirmModalProps) {
  return (
    <Modal isOpen={isOpen} onClose={() => !isLoading && onClose()}>
      <div className="flex flex-col items-center text-center pt-1 pb-3">
        {/* Warning / Alert Icon */}
        <div className="h-14 w-14 rounded-full bg-destructive/10 border border-destructive/30 flex items-center justify-center text-destructive mb-4 shrink-0 shadow-sm">
          <AlertTriangle className="h-7 w-7 text-destructive stroke-[2.2]" />
        </div>

        {/* Title */}
        <h3 className="text-xl font-extrabold text-foreground mb-2">
          {title}
        </h3>

        {/* Description */}
        <p className="text-sm font-medium text-muted-foreground leading-relaxed max-w-[320px] mb-6">
          {description}
        </p>

        {/* Action Buttons */}
        <div className="flex items-center space-x-3 w-full">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isLoading}
            className="flex-1 font-bold h-12 text-sm rounded-full border-border text-foreground hover:bg-muted active:scale-[0.98] transition-all"
          >
            {cancelText}
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className="flex-1 font-bold h-12 text-sm rounded-full bg-destructive hover:bg-destructive/90 text-destructive-foreground shadow-md active:scale-[0.98] transition-all disabled:opacity-60"
          >
            {isLoading ? "Processing..." : confirmText}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
