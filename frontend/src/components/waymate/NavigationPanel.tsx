
import { ArrowUpLeft, X, Play, Pause, Navigation2 } from "lucide-react"
import { cn } from "../../lib/utils"
import { Button } from "../ui/button"

export interface NavigationPanelProps {
  instruction: string
  distanceToInstruction: string
  eta: string
  distanceRemaining: string
  arrivalTime: string
  transportMode?: "Car" | "Transit" | "Walking"
  status: "idle" | "active" | "paused" | "completed"
  onStart?: () => void
  onPause?: () => void
  onEnd?: () => void
  className?: string
}

export function NavigationPanel({
  instruction,
  distanceToInstruction,
  eta,
  distanceRemaining,
  arrivalTime,
  transportMode = "Car",
  status,
  onStart,
  onPause,
  onEnd,
  className
}: NavigationPanelProps) {

  if (status === "idle") return null

  return (
    <div className={cn("absolute inset-0 pointer-events-none z-50 flex flex-col justify-between", className)}>

      {/* Top Instruction Banner */}
      <div className="w-full p-4 pt-safe pointer-events-auto">
        <div className="bg-primary text-primary-foreground rounded-[20px] shadow-lg p-5 flex items-center space-x-5 animate-in slide-in-from-top-4">
          <div className="h-12 w-12 rounded-full bg-white/20 flex items-center justify-center shrink-0">
            <ArrowUpLeft className="h-7 w-7" strokeWidth={3} />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-[24px] font-bold leading-none truncate">{instruction}</h2>
            <p className="text-[15px] font-medium opacity-80 mt-1">In {distanceToInstruction}</p>
          </div>
        </div>
      </div>

      {/* Bottom Info Sheet */}
      <div className="w-full bg-card rounded-t-[24px] shadow-[0_-10px_40px_rgba(0,0,0,0.1)] p-5 pb-safe pointer-events-auto animate-in slide-in-from-bottom-4">

        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-[32px] font-black text-success leading-none">{eta}</h2>
            <div className="flex items-center text-[15px] text-muted-foreground font-medium mt-2">
              <span>{distanceRemaining}</span>
              <span className="mx-2">·</span>
              <span>{arrivalTime} arrival</span>
            </div>
          </div>

          <div className="h-12 w-12 bg-accent rounded-full flex items-center justify-center text-primary shrink-0">
            {transportMode === "Car" && <Navigation2 className="h-6 w-6 fill-current" />}
          </div>
        </div>

        <div className="flex gap-3">
          {status === "active" ? (
            <Button variant="secondary" size="icon" className="shrink-0 h-[56px] w-[56px] rounded-[16px]" onClick={onPause}>
              <Pause className="h-6 w-6" />
            </Button>
          ) : (
            <Button variant="primary" size="icon" className="shrink-0 h-[56px] w-[56px] rounded-[16px]" onClick={onStart}>
              <Play className="h-6 w-6" />
            </Button>
          )}

          <Button variant="danger" className="flex-1 font-bold h-[56px] rounded-[16px]" onClick={onEnd}>
            <X className="mr-2 h-5 w-5" />
            End Trip
          </Button>
        </div>
      </div>

    </div>
  )
}
