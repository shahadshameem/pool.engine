import { Minus, Plus } from "lucide-react"

interface SeatStepperProps {
  value: number
  onChange: (value: number) => void
  min?: number
  max: number
  disabled?: boolean
  label?: string
  className?: string
}

export function SeatStepper({
  value,
  onChange,
  min = 1,
  max,
  disabled = false,
  label = "Seats needed",
  className = ""
}: SeatStepperProps) {
  const handleDecrement = () => {
    if (!disabled && value > min) {
      onChange(value - 1)
    }
  }

  const handleIncrement = () => {
    if (!disabled && value < max) {
      onChange(value + 1)
    }
  }

  return (
    <div className={`space-y-1.5 ${className}`}>
      {label && <label className="text-[13px] font-bold text-foreground block">{label}</label>}
      <div className="flex items-center justify-between bg-muted dark:bg-[#1E1E22] border border-border/60 rounded-[18px] p-2">
        <button
          type="button"
          onClick={handleDecrement}
          disabled={disabled || value <= min}
          className="h-10 w-12 rounded-[14px] bg-card dark:bg-[#2A2A2E] border border-border/60 text-foreground flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed active:scale-95 hover:bg-muted transition-all shadow-xs cursor-pointer"
        >
          <Minus className="h-4 w-4" />
        </button>
        <span className="text-[18px] font-extrabold text-foreground">{value}</span>
        <button
          type="button"
          onClick={handleIncrement}
          disabled={disabled || value >= max}
          className="h-10 w-12 rounded-[14px] bg-card dark:bg-[#2A2A2E] border border-border/60 text-foreground flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed active:scale-95 hover:bg-muted transition-all shadow-xs cursor-pointer"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
