import { Calendar, Clock, Users, User } from "lucide-react"
import { Card } from "../ui/card"
import { formatDate, formatTime12h, formatBranchYear } from "../../utils/formatters"

export interface RideData {
  id: string
  from: string
  to: string
  date: string
  departureTime: string
  availableSeats: number
  hostName?: string
  college?: string
  department?: string
  year?: string
  status?: string
}

interface RideCardProps {
  ride: RideData
  onClick?: () => void
}

export function RideCard({ ride, onClick }: RideCardProps) {
  return (
    <Card
      className="overflow-hidden active:scale-[0.99] transition-transform cursor-pointer"
      onClick={onClick}
    >
      <div className="p-4">
        {/* Route */}
        <div className="flex items-stretch space-x-3 mb-4">
          <div className="relative flex flex-col items-center shrink-0 w-3.5 my-0.5">
            <div className="w-3.5 h-3.5 rounded-full bg-[#3B82F6] ring-2 ring-[#3B82F6]/30 shrink-0 z-10" />
            <div className="w-[2px] flex-1 border-l-2 border-dashed border-foreground/30 dark:border-white/40 my-0.5" />
            <div className="w-3.5 h-3.5 rounded-full bg-[#25D366] ring-2 ring-[#25D366]/30 shrink-0 z-10" />
          </div>

          <div className="flex-1 space-y-3">
            <div className="flex items-center justify-between">
              <div className="font-bold text-foreground leading-none">{ride.from}</div>
              {ride.status && (
                <div className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider ${
                  ride.status === "active" ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20" :
                  ride.status === "full" ? "bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/20" :
                  "bg-muted text-muted-foreground border border-border/40"
                }`}>
                  {ride.status}
                </div>
              )}
            </div>
            <div className="font-bold text-foreground leading-none">{ride.to}</div>
          </div>
        </div>

        {/* Details Row */}
        <div className="flex items-center space-x-4 text-sm text-muted-foreground mb-4">
          <div className="flex items-center space-x-1">
            <Calendar className="h-4 w-4" />
            <span>{formatDate(ride.date)}</span>
          </div>
          <div className="flex items-center space-x-1">
            <Clock className="h-4 w-4" />
            <span>{formatTime12h(ride.departureTime)}</span>
          </div>
        </div>

        {/* Host & Seats Row */}
        <div className="flex items-center justify-between pt-4 border-t border-border/60">
          <div className="flex items-center space-x-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted">
              <User className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-medium leading-none text-foreground">{ride.hostName}</span>
              <span className="text-xs text-muted-foreground mt-1">
                {formatBranchYear(ride.department, ride.year, ride.college || "CET")}
              </span>
            </div>
          </div>

          <div className="flex items-center space-x-1 text-sm font-semibold text-foreground bg-muted px-2.5 py-1 rounded-full border border-border/40">
            <Users className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{ride.availableSeats} left</span>
          </div>
        </div>
      </div>
    </Card>
  )
}
