import * as React from "react"
import { cn } from "../../lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, label, error, helperText, leftIcon, rightIcon, ...props }, ref) => {
    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label className="text-[13px] font-semibold text-foreground/80 leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
            {label}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <div className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground z-10 pointer-events-none">
              {leftIcon}
            </div>
          )}
          <input
            type={type}
            className={cn(
              "flex h-[56px] w-full rounded-[16px] border-2 border-transparent bg-input text-foreground px-4 py-2 text-[15px] ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground transition-colors",
              "focus-visible:outline-none focus-visible:bg-background focus-visible:border-primary",
              "disabled:cursor-not-allowed disabled:opacity-50",
              error ? "border-destructive focus-visible:border-destructive bg-destructive/5" : "",
              leftIcon && "pl-11",
              rightIcon && "pr-11",
              className
            )}
            ref={ref}
            {...props}
          />
          {rightIcon && (
            <div className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground z-10">
              {rightIcon}
            </div>
          )}
        </div>
        {error && (
          <p className="text-[13px] font-medium text-destructive mt-1">{error}</p>
        )}
        {helperText && !error && (
          <p className="text-[13px] text-muted-foreground mt-1">{helperText}</p>
        )}
      </div>
    )
  }
)
Input.displayName = "Input"

export { Input }
