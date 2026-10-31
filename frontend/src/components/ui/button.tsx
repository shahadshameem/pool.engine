import * as React from "react"
import { cn } from "../../lib/utils"

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "tertiary" | "accent" | "danger" | "ghost" | "default" | "outline" | "destructive" | "link"
  size?: "default" | "sm" | "lg" | "icon"
  isLoading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "default", isLoading, children, ...props }, ref) => {

    let variantClass = "bg-[#C5FF00] text-black font-extrabold hover:opacity-90 active:scale-[0.98] transition-all shadow-xs"

    if (variant === "secondary") {
      variantClass = "bg-card text-foreground border border-border/60 hover:bg-muted active:scale-[0.98] transition-all"
    }
    if (variant === "accent") {
      variantClass = "bg-[#C5FF00] text-black font-extrabold hover:opacity-90 active:scale-[0.98] transition-all shadow-xs"
    }
    if (variant === "tertiary" || variant === "ghost") {
      variantClass = "bg-transparent text-foreground hover:bg-muted active:scale-[0.98] transition-all"
    }
    if (variant === "danger" || variant === "destructive") {
      variantClass = "bg-destructive/10 text-destructive border border-destructive/40 hover:bg-destructive/20 active:scale-[0.98] transition-all font-bold"
    }
    if (variant === "outline") {
      variantClass = "bg-card text-foreground border border-border/60 hover:bg-muted transition-all"
    }
    if (variant === "link") {
      variantClass = "bg-transparent text-foreground underline underline-offset-4 hover:opacity-80 p-0 h-auto"
    }
    if (variant === "default") {
      variantClass = "bg-[#C5FF00] text-black font-extrabold hover:opacity-90 transition-all shadow-xs"
    }

    let sizeClass = "h-[54px] px-6 text-[16px]"
    if (size === "sm") sizeClass = "h-[40px] px-4 text-[14px]"
    if (size === "lg") sizeClass = "h-[60px] px-8 text-[18px]"
    if (size === "icon") sizeClass = "h-[48px] w-[48px] p-0"

    return (
      <button
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-full font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40 cursor-pointer select-none",
          variantClass,
          sizeClass,
          className
        )}
        ref={ref}
        disabled={isLoading || props.disabled}
        {...props}
      >
        {isLoading ? (
          <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : null}
        {children}
      </button>
    )
  }
)

Button.displayName = "Button"

export { Button }
