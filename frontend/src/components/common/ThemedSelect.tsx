import React, { useState } from "react"
import { createPortal } from "react-dom"
import { ChevronDown, Check, X } from "lucide-react"
import { cn } from "../../lib/utils"

export interface ThemedSelectOption {
  value: string
  label: string
  badge?: string
}

export interface ThemedSelectProps {
  id?: string
  label: string
  required?: boolean
  value: string
  options: ThemedSelectOption[]
  placeholder: string
  title: string
  icon?: React.ReactNode
  error?: string
  onChange: (value: string) => void
}

export function ThemedSelect({
  label,
  required,
  value,
  options,
  placeholder,
  title,
  icon,
  error,
  onChange
}: ThemedSelectProps) {
  const [isOpen, setIsOpen] = useState(false)

  const selectedOption = options.find((o) => o.value === value)

  const handleSelect = (val: string) => {
    onChange(val)
    setIsOpen(false)
  }

  return (
    <div className="space-y-1.5 w-full">
      {label && (
        <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
          {label} {required && <span className="text-destructive">*</span>}
        </label>
      )}

      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className={cn(
          "w-full h-[54px] bg-card border rounded-2xl px-4 flex items-center justify-between text-left transition-all cursor-pointer",
          error
            ? "border-destructive text-destructive"
            : isOpen
              ? "border-primary dark:border-[#C5FF00] ring-1 ring-primary/30"
              : "border-border/60 hover:border-foreground/30 text-foreground"
        )}
      >
        <div className="flex items-center space-x-3 min-w-0 flex-1">
          {icon && <span className="text-muted-foreground shrink-0">{icon}</span>}
          <div className="truncate">
            {selectedOption ? (
              <span className="text-[15px] font-bold text-foreground">
                {selectedOption.label}
              </span>
            ) : (
              <span className="text-[14px] text-muted-foreground font-medium">
                {placeholder}
              </span>
            )}
          </div>
        </div>
        <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0 ml-2" />
      </button>

      {error && <p className="text-xs text-destructive mt-1">{error}</p>}

      {/* Bottom Sheet Modal */}
      {isOpen &&
        createPortal(
          <>
            <div
              className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
              onClick={() => setIsOpen(false)}
            />
            <div
              className="fixed inset-x-0 bottom-0 z-[101] mx-auto w-full max-w-md bg-card text-foreground border-t border-border/60 rounded-t-[32px] p-6 pb-10 shadow-2xl animate-in slide-in-from-bottom-full duration-300 max-h-[82vh] flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex justify-between items-center mb-4 pb-3 border-b border-border/40 shrink-0">
                <h3 className="text-[18px] font-black text-foreground">{title}</h3>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="h-8 w-8 rounded-full bg-muted hover:bg-muted/80 flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                  aria-label="Close"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Options List */}
              <div className="space-y-2.5 overflow-y-auto pr-1 flex-1 py-1">
                {options.map((opt) => {
                  const isSelected = opt.value === value
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => handleSelect(opt.value)}
                      className={cn(
                        "w-full flex items-center justify-between p-4 rounded-[18px] transition-all text-left border cursor-pointer",
                        isSelected
                          ? "bg-[#C5FF00] text-black border-transparent shadow-xs font-extrabold"
                          : "bg-card border-border/60 hover:bg-muted text-foreground font-medium"
                      )}
                    >
                      <div className="flex items-center space-x-2.5 min-w-0 flex-1 pr-2">
                        {opt.badge && (
                          <span
                            className={cn(
                              "px-2 py-0.5 rounded-md text-[12px] font-black shrink-0",
                              isSelected
                                ? "bg-black/20 text-black font-bold"
                                : "bg-muted text-muted-foreground"
                            )}
                          >
                            {opt.badge}
                          </span>
                        )}
                        <span className="text-[15px] font-bold truncate">
                          {opt.label}
                        </span>
                      </div>
                      {isSelected && (
                        <div className="h-6 w-6 rounded-full bg-black text-[#C5FF00] flex items-center justify-center shrink-0">
                          <Check className="h-4 w-4 stroke-[3]" />
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          </>,
          document.body
        )}
    </div>
  )
}
