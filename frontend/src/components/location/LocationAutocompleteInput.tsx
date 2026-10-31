import React, { useState, useEffect, useRef } from "react"
import {
  MapPin,
  X,
  Navigation,
  Loader2,
  Sparkles
} from "lucide-react"
import {
  CAMPUS_PRESETS,
  searchLocations,
  getCurrentLiveLocation,
  type LocationPoint
} from "../../utils/locationService"

export interface LocationAutocompleteInputProps {
  label?: string
  value?: LocationPoint | null
  placeholder?: string
  onChange: (location: LocationPoint) => void
  error?: string
  className?: string
  iconColor?: string
  showQuickChips?: boolean
}

// Key popular Trivandrum presets for 1-tap quick chips
const QUICK_CHIPS = [
  "College of Engineering Trivandrum",
  "Trivandrum Central Railway Station",
  "Kochuveli Railway Station"
]

export function LocationAutocompleteInput({
  label,
  value,
  placeholder = "Search campus, junction, or landmark...",
  onChange,
  error,
  className = "",
  iconColor = "text-blue-500",
  showQuickChips = true
}: LocationAutocompleteInputProps) {
  const [inputValue, setInputValue] = useState(value?.name || "")
  const [suggestions, setSuggestions] = useState<LocationPoint[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [isLocating, setIsLocating] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (value?.name) {
      setInputValue(value.name)
    }
  }, [value?.name])

  // Click outside to close suggestion dropdown
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setInputValue(val)
    setIsOpen(true)

    if (debounceTimer.current) clearTimeout(debounceTimer.current)

    if (val.trim().length === 0) {
      setSuggestions(CAMPUS_PRESETS.slice(0, 8))
      return
    }

    setIsSearching(true)
    debounceTimer.current = setTimeout(async () => {
      try {
        const results = await searchLocations(val)
        setSuggestions(results)
      } catch (err) {
        console.warn("[LocationAutocompleteInput] Search error:", err)
      } finally {
        setIsSearching(false)
      }
    }, 300)
  }

  const handleSelect = (point: LocationPoint) => {
    setInputValue(point.name)
    onChange(point)
    setIsOpen(false)
  }

  const handleQuickChipClick = (chipName: string) => {
    const match = CAMPUS_PRESETS.find(p => p.name.toLowerCase().includes(chipName.toLowerCase()))
    if (match) {
      handleSelect(match)
    }
  }

  const handleUseCurrentLiveLocation = async () => {
    setIsLocating(true)
    try {
      const livePoint = await getCurrentLiveLocation()
      handleSelect(livePoint)
    } catch (err) {
      alert("Unable to fetch live GPS location. Please check browser permissions.")
    } finally {
      setIsLocating(false)
    }
  }

  return (
    <div ref={containerRef} className={`w-full relative space-y-1.5 ${className}`}>
      {label && (
        <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider block px-1">
          {label}
        </label>
      )}

      {/* Main Input Box */}
      <div className="relative flex items-center">
        <div className={`absolute left-3.5 ${iconColor} pointer-events-none shrink-0`}>
          <MapPin className="h-4 w-4" strokeWidth={2.2} />
        </div>

        <input
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          onFocus={() => {
            setIsOpen(true)
            if (!inputValue) setSuggestions(CAMPUS_PRESETS.slice(0, 8))
          }}
          placeholder={placeholder}
          className={`w-full h-12 pl-10 pr-20 bg-muted/60 border rounded-xl text-[14px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary font-medium transition-all ${
            error ? "border-destructive focus:ring-destructive" : "border-border/60"
          }`}
        />

        <div className="absolute right-2 flex items-center space-x-1">
          {isSearching && (
            <div className="p-1">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
            </div>
          )}

          {inputValue && (
            <button
              type="button"
              onClick={() => {
                setInputValue("")
                setSuggestions(CAMPUS_PRESETS.slice(0, 8))
              }}
              className="p-1.5 text-muted-foreground hover:text-foreground rounded-md transition-colors"
              title="Clear text"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}

          {/* Live GPS Button */}
          <button
            type="button"
            onClick={handleUseCurrentLiveLocation}
            disabled={isLocating}
            className="p-1.5 text-blue-600 dark:text-blue-400 hover:bg-blue-500/10 rounded-md transition-colors cursor-pointer"
            title="Use Current Live Location (GPS)"
          >
            <Navigation className={`h-4 w-4 ${isLocating ? "animate-spin text-blue-500" : ""}`} />
          </button>
        </div>
      </div>

      {error && <p className="text-[12px] font-medium text-destructive px-1">{error}</p>}

      {/* Dropdown Suggestions Menu */}
      {isOpen && (
        <div className="absolute left-0 right-0 top-full mt-1.5 bg-card border border-border/80 rounded-2xl shadow-xl z-50 max-h-72 overflow-y-auto divide-y divide-border/30 animate-in fade-in zoom-in-95 duration-150">

          {/* Top GPS Quick Action */}
          <button
            type="button"
            onClick={handleUseCurrentLiveLocation}
            disabled={isLocating}
            className="w-full p-3 flex items-center space-x-3 text-left bg-blue-500/5 hover:bg-blue-500/10 text-blue-600 dark:text-blue-400 font-semibold text-xs transition-colors cursor-pointer"
          >
            <Navigation className={`h-4 w-4 shrink-0 ${isLocating ? "animate-spin" : ""}`} />
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-bold">Use Current Live Location (GPS)</p>
              <p className="text-[11px] text-muted-foreground">Detect exact street coordinates in Trivandrum</p>
            </div>
          </button>

          {/* Suggestion Items */}
          {suggestions.map((point, idx) => (
            <button
              key={`${point.name}-${idx}`}
              type="button"
              onClick={() => handleSelect(point)}
              className="w-full p-3 flex items-start space-x-3 text-left hover:bg-muted/70 transition-colors cursor-pointer"
            >
              <MapPin className={`h-4 w-4 mt-0.5 shrink-0 ${point.isPreset ? "text-primary dark:text-[#C5FF00]" : "text-muted-foreground"}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center space-x-2">
                  <p className="text-[13px] font-semibold text-foreground truncate">{point.name}</p>
                  {point.category && (
                    <span className="px-1.5 py-0.2 rounded bg-primary/10 text-primary dark:text-[#C5FF00] text-[9px] font-extrabold uppercase shrink-0">
                      {point.category}
                    </span>
                  )}
                </div>
                {point.area && (
                  <p className="text-[11px] text-muted-foreground truncate">{point.area}</p>
                )}
              </div>
            </button>
          ))}

          {suggestions.length === 0 && !isSearching && (
            <p className="p-4 text-center text-xs text-muted-foreground">
              No matching locations found in Trivandrum.
            </p>
          )}
        </div>
      )}

      {/* 1-Tap Quick Chips */}
      {showQuickChips && (
        <div className="flex items-center space-x-1.5 overflow-x-auto no-scrollbar py-1 text-xs">
          <span className="text-[11px] font-semibold text-muted-foreground shrink-0 flex items-center space-x-1 pl-1">
            <Sparkles className="h-3 w-3 text-primary" />
            <span>Hotspots:</span>
          </span>
          {QUICK_CHIPS.map(chip => (
            <button
              key={chip}
              type="button"
              onClick={() => handleQuickChipClick(chip)}
              className="px-2.5 py-1 rounded-full bg-muted/80 hover:bg-muted border border-border/60 text-muted-foreground hover:text-foreground text-[11px] font-medium whitespace-nowrap active:scale-95 transition-all cursor-pointer"
            >
              {chip}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default LocationAutocompleteInput
