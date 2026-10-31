import { cn } from "../../lib/utils"

export type StatusType = "joined" | "hosting" | "completed" | "cancelled" | "pending" | "accepted" | string
export type StatusBadgeType = StatusType

interface StatusBadgeProps {
  status: StatusType
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalized = status.toLowerCase()

  let badgeStyle = "bg-zinc-200 text-zinc-900 border border-zinc-300 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-700 font-extrabold"
  let label = status

  if (normalized === "joined" || normalized === "accepted" || normalized === "confirmed") {
    // EDEX Green (#25D366)
    badgeStyle = "bg-[#25D366]/20 text-[#0e5227] border border-[#25D366]/40 dark:bg-[#25D366]/20 dark:text-[#25D366] dark:border-[#25D366]/50 font-extrabold"
    label = "Joined"
  } else if (normalized === "hosting" || normalized === "host") {
    // EDEX Lime (#C5FF00)
    badgeStyle = "bg-[#C5FF00] text-black border border-black/20 font-extrabold shadow-2xs"
    label = "Hosting"
  } else if (normalized === "started" || normalized === "in_progress" || normalized === "ongoing") {
    // Accent Blue Tint
    badgeStyle = "bg-blue-500/15 text-blue-700 border border-blue-500/35 dark:bg-blue-500/25 dark:text-blue-300 dark:border-blue-500/50 font-extrabold"
    label = "Started"
  } else if (normalized === "cancelled" || normalized === "canceled") {
    // EDEX Red (#E52E3D)
    badgeStyle = "bg-[#E52E3D]/15 text-[#99111E] border border-[#E52E3D]/35 dark:bg-[#E52E3D]/25 dark:text-[#FF5C6A] dark:border-[#E52E3D]/50 font-extrabold"
    label = "Cancelled"
  } else if (normalized === "rejected" || normalized === "declined") {
    // EDEX Red Tint (#E52E3D)
    badgeStyle = "bg-[#E52E3D]/15 text-[#99111E] border border-[#E52E3D]/35 dark:bg-[#E52E3D]/25 dark:text-[#FF5C6A] dark:border-[#E52E3D]/50 font-extrabold"
    label = "Declined"
  } else if (normalized === "completed" || normalized === "expired") {
    // EDEX Neutral UI Grayscale (Distinct high-contrast pill container for both Light & Dark modes)
    badgeStyle = "bg-zinc-200 text-zinc-900 border border-zinc-300 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-700 font-extrabold"
    label = "Completed"
  } else if (normalized === "pending" || normalized === "requested") {
    // High-contrast Amber tint for pending requests
    badgeStyle = "bg-amber-500/15 text-amber-800 border border-amber-500/35 dark:bg-amber-500/25 dark:text-amber-300 dark:border-amber-500/50 font-extrabold"
    label = "Requested"
  } else if (normalized === "full" || normalized === "booked") {
    // EDEX Red Tint
    badgeStyle = "bg-[#E52E3D]/15 text-[#99111E] border border-[#E52E3D]/35 dark:bg-[#E52E3D]/25 dark:text-[#FF5C6A] dark:border-[#E52E3D]/50 font-extrabold"
    label = "Full"
  }

  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-full px-3 py-1 text-[13px] leading-none transition-colors",
        badgeStyle,
        className
      )}
    >
      {label}
    </span>
  )
}
