import { Calendar, Clock, MapPin, Car } from "lucide-react"
import { cn } from "../../lib/utils"
import { Button } from "../ui/button"
import { formatDate, formatTime12h } from "../../utils/formatters"

export interface TripCardProps {
  destination: string
  date: string
  time: string

  duration?: string
  state: "upcoming" | "active" | "completed" | "cancelled"
  onAction?: () => void
  className?: string
}

export function TripCard({
  destination,
  date,
  time,

  duration,
  state,
  onAction,
  className
}: TripCardProps) {

  const statusConfig = {
    upcoming: { color: "text-primary bg-primary/10", label: "Upcoming" },
    active: { color: "text-success bg-success/10", label: "Active Now" },
    completed: { color: "text-muted-foreground bg-secondary", label: "Completed" },
    cancelled: { color: "text-destructive bg-destructive/10", label: "Cancelled" }
  }

  const currentStatus = statusConfig[state]

  return (
    <div className={cn("w-full rounded-[20px] border border-border bg-card p-5 shadow-[0_4px_12px_rgba(0,0,0,0.02)]", className)}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center space-x-2 text-muted-foreground mb-1">
            <span className={cn("px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider", currentStatus.color)}>
              {currentStatus.label}
            </span>
          </div>
          <h3 className="font-semibold text-[18px] text-foreground leading-tight">
            {destination}
          </h3>
        </div>
        <div className="bg-secondary p-2.5 rounded-full text-primary shrink-0 ml-3">
          <Car className="h-5 w-5" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-y-2 gap-x-4 mb-5">
        <div className="flex items-center text-[13px] text-muted-foreground">
          <Calendar className="h-4 w-4 mr-2 opacity-70" />
          <span className="font-medium text-foreground">{formatDate(date)}</span>
        </div>
        <div className="flex items-center text-[13px] text-muted-foreground">
          <Clock className="h-4 w-4 mr-2 opacity-70" />
          <span className="font-medium text-foreground">{formatTime12h(time)}</span>
        </div>
        {duration && (
          <div className="flex items-center text-[13px] text-muted-foreground col-span-2">
            <MapPin className="h-4 w-4 mr-2 opacity-70" />
            <span>Duration: {duration}</span>
          </div>
        )}
      </div>

      {onAction && (
        <Button
          variant={state === "active" ? "primary" : (state === "cancelled" ? "ghost" : "secondary")}
          className="w-full h-[52px] rounded-full font-bold shadow-sm"
          onClick={onAction}
        >
          {state === "active" ? "View Live Trip" : "View Details"}
        </Button>
      )}
    </div>
  )
}
