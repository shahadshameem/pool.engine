import React from "react"
import { cn } from "../../lib/utils"

interface MaterialIconProps {
  name: string
  className?: string
  onClick?: (e: React.MouseEvent<HTMLSpanElement>) => void
  ariaLabel?: string
}

export function MaterialIcon({ name, className, onClick, ariaLabel }: MaterialIconProps) {
  return (
    <span
      className={cn(
        "material-icons-outlined select-none text-[22px] leading-none inline-flex items-center justify-center shrink-0",
        onClick && "cursor-pointer hover:opacity-80 transition-opacity",
        className
      )}
      onClick={onClick}
      aria-label={ariaLabel || name}
      role={onClick ? "button" : undefined}
    >
      {name}
    </span>
  )
}
