import * as React from "react"
import { Search, X } from "lucide-react"
import { cn } from "../../lib/utils"

export interface SearchBarProps extends React.InputHTMLAttributes<HTMLInputElement> {
  onClear?: () => void
  containerClassName?: string
}

const SearchBar = React.forwardRef<HTMLInputElement, SearchBarProps>(
  ({ className, containerClassName, value, onChange, onClear, ...props }, ref) => {
    const hasValue = value && String(value).length > 0

    return (
      <div className={cn("relative w-full", containerClassName)}>
        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-primary">
          <Search className="h-5 w-5" />
        </div>
        <input
          ref={ref}
          value={value}
          onChange={onChange}
          className={cn(
            "flex h-[60px] w-full rounded-[18px] border-2 border-border bg-card px-12 py-3 text-[16px] font-medium text-foreground",
            "placeholder:text-muted-foreground focus:outline-none focus:border-primary focus:bg-background transition-all",
            className
          )}
          {...props}
        />
        {hasValue && onClear && (
          <button
            type="button"
            onClick={onClear}
            className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-1 rounded-[18px] hover:bg-accent transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    )
  }
)
SearchBar.displayName = "SearchBar"

export { SearchBar }
