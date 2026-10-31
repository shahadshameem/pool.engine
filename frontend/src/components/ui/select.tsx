import * as React from "react"
import { cn } from "../../lib/utils"
import { ChevronDown } from "lucide-react"

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
  helperText?: string
  options: { value: string; label: string }[]
  placeholder?: string
}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, helperText, options, placeholder, ...props }, ref) => {
    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label className="text-[13px] font-semibold text-foreground/80 leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            className={cn(
              "flex h-[56px] w-full appearance-none rounded-[16px] border-2 border-transparent bg-input px-4 py-2 text-[15px] ring-offset-background",
              "focus-visible:outline-none focus-visible:bg-background focus-visible:border-primary",
              "disabled:cursor-not-allowed disabled:opacity-50",
              error ? "border-destructive focus-visible:border-destructive bg-destructive/5" : "",
              className
            )}
            ref={ref}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none">
            <ChevronDown className="h-5 w-5" />
          </div>
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
Select.displayName = "Select"

export { Select }
