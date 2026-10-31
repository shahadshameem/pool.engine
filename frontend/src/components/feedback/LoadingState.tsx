import React from "react"
import { cn } from "../../lib/utils"

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "inline-block h-6 w-6 animate-spin rounded-full border-4 border-solid border-current border-e-transparent align-[-0.125em] text-primary motion-reduce:animate-[spin_1.5s_linear_infinite]",
        className
      )}
      role="status"
    />
  )
}

export function FullPageLoader({ className }: { className?: string } = {}) {
  return (
    <div className={cn("flex min-h-screen w-full flex-col items-center justify-center space-y-4 bg-background text-foreground transition-colors duration-150", className)}>
      <Spinner className="h-10 w-10 text-primary" />
      <p className="text-sm font-medium text-muted-foreground animate-pulse">Loading...</p>
    </div>
  )
}

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  )
}
