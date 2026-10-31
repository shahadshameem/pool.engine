import React from "react"
import { Button } from "../ui/button"

interface EmptyStateProps {
  icon?: React.ReactNode
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
  actionVariant?: "primary" | "secondary" | "outline" | "ghost"
}

export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
  actionVariant = "primary"
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center p-8 text-center bg-card border border-border/60 rounded-[24px] shadow-xs animate-in fade-in zoom-in duration-300">
      {icon && (
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted text-[#C5FF00] shadow-2xs">
          {icon}
        </div>
      )}
      <p className="mb-4 text-[15px] font-semibold text-muted-foreground">
        {title}
      </p>
      {description && (
        <p className="mb-4 max-w-[280px] text-[14px] text-muted-foreground/80 leading-relaxed">
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <Button
          onClick={onAction}
          variant={actionVariant}
          className="px-6 py-2.5 h-auto rounded-full bg-[#C5FF00] text-black hover:bg-[#b5eb00] font-bold text-[14px] shadow-xs cursor-pointer"
        >
          {actionLabel}
        </Button>
      )}
    </div>
  )
}