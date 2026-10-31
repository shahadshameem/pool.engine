import React from "react"
import { cn } from "../../lib/utils"
import { BottomNavigation } from "../waymate/BottomNavigation"

interface MobileShellProps {
  children: React.ReactNode
  className?: string
  hideBottomNav?: boolean
  hasStickyHeader?: boolean
  footer?: React.ReactNode
}

export function MobileShell({
  children,
  className,
  hideBottomNav = false,
  hasStickyHeader = false,
  footer
}: MobileShellProps) {
  // Reset window scroll when on-screen keyboard closes (U2)
  React.useEffect(() => {
    const handleResetScroll = () => {
      // Delay slightly for virtual keyboard dismiss animation
      setTimeout(() => {
        if (typeof window !== "undefined" && window.scrollY > 0) {
          window.scrollTo({ top: 0, left: 0, behavior: "instant" })
        }
      }, 100)
    }

    const vv = typeof window !== "undefined" ? window.visualViewport : null
    if (vv) {
      vv.addEventListener("resize", handleResetScroll)
    }
    window.addEventListener("focusout", handleResetScroll)

    return () => {
      if (vv) {
        vv.removeEventListener("resize", handleResetScroll)
      }
      window.removeEventListener("focusout", handleResetScroll)
    }
  }, [])

  return (
    <div className="mx-auto flex h-[100dvh] min-h-[100dvh] w-full max-w-md flex-col bg-background text-foreground shadow-sm sm:border-x border-border/40 overflow-x-hidden relative pl-[env(safe-area-inset-left,0px)] pr-[env(safe-area-inset-right,0px)]">
      <main
        className={cn(
          "flex-1 overflow-y-auto",
          hasStickyHeader
            ? "pt-0 px-0"
            : "pt-[calc(0.75rem+env(safe-area-inset-top,0px))] px-4",
          hideBottomNav
            ? (footer ? "pb-[calc(10rem+env(safe-area-inset-bottom,16px))]" : "pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))]")
            : "pb-[calc(5.5rem+env(safe-area-inset-bottom,0px))]",
          className
        )}
      >
        {children}
      </main>

      {footer}
      {!hideBottomNav && <BottomNavigation />}
    </div>
  )
}
