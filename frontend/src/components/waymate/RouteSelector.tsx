import { useState, useRef } from "react"
import { createPortal } from "react-dom"
import {
  MapPin,
  ArrowDownUp,
  Check,
  ChevronDown,
  Search,
  X,
  Loader2
} from "lucide-react"
import type { FixedLocation } from "../../config/locations"
import { cn } from "../../lib/utils"
import {
  searchLocations,
  getCurrentLiveLocation,
  CAMPUS_PRESETS,
  type LocationPoint
} from "../../utils/locationService"
import { cleanLocationDisplayName } from "../../utils/formatters"
import { CurrentLocationIcon } from "./WaymateRideSearch"

export interface RouteSelectorProps {
  fromLocation?: FixedLocation
  toLocation?: FixedLocation
  onFromChange: (loc: FixedLocation) => void
  onToChange: (loc: FixedLocation) => void
  error?: string
}

function pointToFixedLocation(point: LocationPoint): FixedLocation {
  const safeId = point.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "loc-" + Date.now()
  return {
    id: safeId,
    name: point.name,
    address: point.subtext || point.area || point.name,
    latitude: point.lat,
    longitude: point.lng
  }
}

export function RouteSelector({ fromLocation, toLocation, onFromChange, onToChange, error }: RouteSelectorProps) {
  const [activeField, setActiveField] = useState<"from" | "to" | null>(null)

  // Autocomplete state
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<LocationPoint[]>([])
  const [isLoadingSearch, setIsLoadingSearch] = useState(false)
  const [isLocating, setIsLocating] = useState(false)

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Reset modal state when closed
  const closeModal = () => {
    setActiveField(null)
    setSearchQuery("")
    setSearchResults([])
    setIsLoadingSearch(false)
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
  }

  const handleSwap = () => {
    if (fromLocation && toLocation) {
      const temp = fromLocation
      onFromChange(toLocation)
      onToChange(temp)
    }
  }

  const handleSelectLocation = (point: LocationPoint | FixedLocation) => {
    const fixed: FixedLocation = "latitude" in point
      ? point
      : pointToFixedLocation(point as LocationPoint)

    const otherLoc = activeField === "from" ? toLocation : fromLocation
    if (otherLoc && (otherLoc.id === fixed.id || otherLoc.name.trim().toLowerCase() === fixed.name.trim().toLowerCase())) {
      alert("Departure and destination cannot be the same location.")
      return
    }

    if (activeField === "from") {
      onFromChange(fixed)
    } else if (activeField === "to") {
      onToChange(fixed)
    }
    closeModal()
  }

  // Live hybrid search (Campus Presets + OpenStreetMap Photon API)
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setSearchQuery(val)

    if (debounceTimer.current) clearTimeout(debounceTimer.current)

    if (val.trim().length === 0) {
      setSearchResults([])
      setIsLoadingSearch(false)
      return
    }

    setIsLoadingSearch(true)
    debounceTimer.current = setTimeout(async () => {
      try {
        const results = await searchLocations(val)
        setSearchResults(results)
      } catch (err) {
        console.warn("[locationService] Search error:", err)
      } finally {
        setIsLoadingSearch(false)
      }
    }, 300)
  }

  // Use GPS location for active field with campus zone auto-assignment & accuracy filter
  const handleUseCurrentLocation = async (targetField?: "from" | "to") => {
    const fieldToUpdate = targetField || activeField || "from"
    setIsLocating(true)

    try {
      const livePoint = await getCurrentLiveLocation()

      const myLoc: FixedLocation = {
        id: livePoint.matchedZoneId || `gps-${Date.now()}`,
        name: livePoint.name,
        address: livePoint.address || livePoint.name,
        latitude: livePoint.lat,
        longitude: livePoint.lng,
        ...(livePoint.matchedZoneId ? { matchedZoneId: livePoint.matchedZoneId } : {}),
        ...(livePoint.rawGps ? { rawGps: livePoint.rawGps } : {}),
        ...(livePoint.isLowAccuracy !== undefined ? { isLowAccuracy: livePoint.isLowAccuracy } : {}),
        ...(livePoint.accuracyMeters !== undefined ? { accuracyMeters: livePoint.accuracyMeters } : {})
      }

      const otherLoc = fieldToUpdate === "from" ? toLocation : fromLocation
      if (otherLoc && ((otherLoc.matchedZoneId && otherLoc.matchedZoneId === myLoc.matchedZoneId) || (otherLoc.latitude === myLoc.latitude && otherLoc.longitude === myLoc.longitude))) {
        alert("Departure and destination cannot be the same location.")
        setIsLocating(false)
        return
      }

      if (fieldToUpdate === "from") {
        onFromChange(myLoc)
      } else if (fieldToUpdate === "to") {
        onToChange(myLoc)
      }

      if (livePoint.isLowAccuracy) {
        alert(`Low GPS accuracy (±${Math.round(livePoint.accuracyMeters || 0)}m). Please verify or drag your pickup point on the map.`)
      }

      setIsLocating(false)
      closeModal()
    } catch (err: any) {
      console.warn("[RouteSelector] GPS auto-location error:", err)
      setIsLocating(false)
      alert(err?.message || "Unable to acquire GPS location. Please check location permissions.")
    }
  }

  // Preset list based on Trivandrum presets
  const presetPlaces: (FixedLocation & { subtext?: string; category?: string })[] = CAMPUS_PRESETS.map(p => ({
    id: p.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    name: p.name,
    address: p.subtext || p.area || p.name,
    subtext: p.subtext,
    category: p.category || "Campus",
    latitude: p.lat,
    longitude: p.lng
  }))

  return (
    <div className="w-full space-y-3 relative">

      {/* FROM Field */}
      <div
        onClick={() => setActiveField("from")}
        className={cn(
          "w-full h-14 bg-muted border rounded-[16px] px-3.5 flex items-center justify-between cursor-pointer transition-all hover:opacity-90",
          error && !fromLocation ? "border-destructive text-destructive" : "border-border/40"
        )}
      >
        <div className="flex items-center space-x-3 min-w-0 flex-1">
          <MapPin className="h-6 w-6 text-foreground dark:text-[#C5FF00] shrink-0" strokeWidth={1.8} />
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">FROM</span>
            <span className={cn("text-[14px] sm:text-[15px] font-medium truncate", fromLocation ? "text-foreground font-semibold" : "text-muted-foreground")}>
              {fromLocation ? cleanLocationDisplayName(fromLocation.name) : "Select departure"}
            </span>
          </div>
        </div>
        <div className="flex items-center space-x-1 shrink-0 ml-1">
          <button
            type="button"
            title="Use Current Location"
            onClick={(e) => {
              e.stopPropagation()
              handleUseCurrentLocation("from")
            }}
            disabled={isLocating}
            className="p-1.5 rounded-full text-foreground/80 hover:text-foreground hover:bg-card active:scale-90 transition-all cursor-pointer"
          >
            <CurrentLocationIcon className={`h-4.5 w-4.5 ${isLocating ? "animate-spin text-primary dark:text-[#C5FF00]" : "text-foreground hover:text-primary dark:hover:text-[#C5FF00]"}`} />
          </button>
          <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0" />
        </div>
      </div>

      {/* FLOATING SWAP BUTTON */}
      <div className="absolute right-6 top-[45px] z-10">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); handleSwap(); }}
          className={cn(
            "h-9 w-9 bg-card border border-border/80 rounded-full flex items-center justify-center shadow-md transition-transform transition-colors duration-150 text-foreground cursor-pointer",
            (!fromLocation || !toLocation)
              ? "opacity-100 pointer-events-none text-muted-foreground/40 bg-card border-border/60"
              : "hover:bg-muted active:scale-95 hover:border-foreground/40"
          )}
          disabled={!fromLocation || !toLocation}
          aria-label="Swap departure and destination"
        >
          <ArrowDownUp className="h-4 w-4 stroke-[2]" />
        </button>
      </div>

      {/* TO Field */}
      <div
        onClick={() => setActiveField("to")}
        className={cn(
          "w-full h-14 bg-muted border rounded-[16px] px-3.5 flex items-center justify-between cursor-pointer transition-all hover:opacity-90",
          error && !toLocation ? "border-destructive text-destructive" : "border-border/40"
        )}
      >
        <div className="flex items-center space-x-3 min-w-0 flex-1">
          <div className="h-6 w-6 shrink-0 flex items-center justify-center">
            <div className="h-5 w-5 rounded-full border-[5px] border-foreground dark:border-[#C5FF00] bg-card" />
          </div>
          <div className="flex flex-col min-w-0 flex-1 pr-9">
            <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">TO</span>
            <span className={cn("text-[14px] sm:text-[15px] font-medium truncate", toLocation ? "text-foreground font-semibold" : "text-muted-foreground")}>
              {toLocation ? cleanLocationDisplayName(toLocation.name) : "Select destination"}
            </span>
          </div>
        </div>
        <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0 ml-1" />
      </div>

      {/* Error Message */}
      {error && <p className="text-[13px] font-medium text-destructive mt-1 px-1">{error}</p>}

      {/* 1. SELECTION BOTTOM SHEET MODAL */}
      {activeField && createPortal(
        <>
          <div
            className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
            onClick={closeModal}
          />
          <div
            className="fixed inset-x-0 bottom-0 z-[101] mx-auto w-full max-w-md bg-card text-foreground border-t border-border/60 rounded-t-[32px] p-6 pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))] shadow-2xl animate-in slide-in-from-bottom-full duration-300 max-h-[85vh] flex flex-col overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            {/* Header (Sticky / Non-scrolling) (U6) */}
            <div className="flex justify-between items-center mb-4 pb-3 border-b border-border/40 shrink-0">
              <div>
                <h3 className="text-[18px] font-extrabold text-foreground">
                  Select {activeField === "from" ? "Source" : "Destination"}
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Campus presets & live address search
                </p>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="h-8 w-8 rounded-full bg-muted hover:bg-muted/80 flex items-center justify-center font-bold text-muted-foreground transition-colors cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Hybrid Autocomplete Search Bar (Non-scrolling, no autoFocus on mobile) (U5, U6) */}
            <div className="relative mb-3.5 shrink-0">
              <Search className="absolute left-3.5 top-3.5 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={handleSearchChange}
                placeholder="Search campus, junctions, railway station..."
                className="w-full h-11 pl-10 pr-20 bg-muted/60 border border-border/60 rounded-xl text-[14px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[#C5FF00]"
              />
              <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center space-x-1">
                {isLoadingSearch && (
                  <div className="p-1">
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  </div>
                )}
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => { setSearchQuery(""); setSearchResults([]); }}
                    className="p-1 text-muted-foreground hover:text-foreground rounded-md"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
                {activeField === "from" && (
                  <button
                    type="button"
                    title="Use Current Location"
                    onClick={() => handleUseCurrentLocation("from")}
                    disabled={isLocating}
                    className="p-1.5 text-foreground/80 hover:text-foreground hover:bg-muted active:scale-90 rounded-md transition-all cursor-pointer"
                  >
                    <CurrentLocationIcon className={`h-4.5 w-4.5 ${isLocating ? "animate-spin text-primary dark:text-[#C5FF00]" : "text-foreground hover:text-primary dark:hover:text-[#C5FF00]"}`} />
                  </button>
                )}
              </div>
            </div>

            {/* Scrollable Content Container (Only presets and search results scroll) (U6) */}
            <div className="flex-1 min-h-0 overflow-y-auto pr-1 -mr-1">
              {/* Quick Live GPS Location Button (Hidden on Destination when From is already GPS) (U7) */}
              {!searchQuery && !(activeField === "to" && (fromLocation?.id?.startsWith("gps-") || fromLocation?.name?.toLowerCase().includes("current location"))) && (
                <button
                  type="button"
                  onClick={() => handleUseCurrentLocation(activeField || "from")}
                  disabled={isLocating}
                  className="w-full mb-3.5 flex items-center space-x-3 p-3 rounded-2xl border border-primary/30 bg-primary/5 hover:bg-primary/10 transition-colors text-left cursor-pointer active:scale-[0.99]"
                >
                  <div className="h-9 w-9 rounded-full bg-primary/15 flex items-center justify-center shrink-0">
                    <CurrentLocationIcon className={`h-5 w-5 ${isLocating ? "animate-spin text-primary" : "text-primary dark:text-[#C5FF00]"}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-bold text-foreground">
                      {isLocating ? "Detecting current location..." : "Use Current Location"}
                    </p>
                    <p className="text-[12px] text-muted-foreground truncate">
                      Tap to detect your live GPS location in Trivandrum
                    </p>
                  </div>
                </button>
              )}

              {/* Search Results (Live Presets & Photon API) */}
              {searchQuery && (
                <div className="space-y-2 mb-4">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground px-1">
                    Matching Locations
                  </span>
                  <div className="space-y-1.5">
                    {searchResults.map((point, idx) => {
                      const otherLoc = activeField === "from" ? toLocation : fromLocation
                      const isOther = Boolean(
                        otherLoc && (
                          (point.name && otherLoc.name.trim().toLowerCase() === point.name.trim().toLowerCase()) ||
                          (typeof point.lat === "number" && typeof otherLoc.latitude === "number" && Math.abs(point.lat - otherLoc.latitude) < 0.0001 && Math.abs(point.lng - otherLoc.longitude) < 0.0001)
                        )
                      )
                      return (
                        <button
                          key={`${point.name}-${idx}`}
                          type="button"
                          disabled={isOther}
                          onClick={() => handleSelectLocation(point)}
                          className={cn(
                            "w-full flex items-start space-x-3 p-3 rounded-xl border transition-colors text-left cursor-pointer",
                            isOther
                              ? "border-transparent bg-muted opacity-40 cursor-not-allowed"
                              : "border-border/40 hover:bg-muted"
                          )}
                        >
                          <MapPin className={`h-5 w-5 shrink-0 mt-0.5 ${point.isPreset ? "text-primary dark:text-[#C5FF00]" : "text-blue-500"}`} />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center space-x-2">
                              <p className="text-[14px] font-semibold text-foreground truncate">
                                {point.name}
                              </p>
                              {point.category && (
                                <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary dark:text-[#C5FF00] text-[9px] font-extrabold uppercase">
                                  {point.category}
                                </span>
                              )}
                            </div>
                            {(point.subtext || point.address) && (
                              <p className="text-[12px] text-muted-foreground truncate">
                                {point.subtext || point.address}
                              </p>
                            )}
                          </div>
                        </button>
                      )
                    })}

                    {searchResults.length === 0 && !isLoadingSearch && (
                      <p className="text-center text-sm text-muted-foreground py-4">
                        No matching locations found in Trivandrum. Try another landmark.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Default Campus Presets (when no query is active) */}
              {!searchQuery && (
                <div className="space-y-2 pb-4">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground px-1">
                    Trivandrum Presets
                  </span>

                  <div className="space-y-2">
                    {presetPlaces.map(loc => {
                      const otherLoc = activeField === "from" ? toLocation : fromLocation
                      const isSelected = (activeField === "from" ? fromLocation?.id : toLocation?.id) === loc.id
                      const isOther = Boolean(otherLoc && (otherLoc.id === loc.id || otherLoc.name.trim().toLowerCase() === loc.name.trim().toLowerCase()))

                      return (
                        <button
                          key={loc.id}
                          type="button"
                          disabled={isOther}
                          onClick={() => handleSelectLocation(loc)}
                          className={cn(
                            "w-full flex items-center justify-between p-3.5 rounded-[16px] transition-all text-left border cursor-pointer min-h-[44px]",
                            isSelected
                              ? "bg-[#C5FF00] text-black border-transparent shadow-xs font-extrabold"
                              : isOther
                                ? "bg-muted border-transparent opacity-40 cursor-not-allowed text-muted-foreground"
                                : "bg-card border-border/60 hover:bg-muted text-foreground font-medium"
                          )}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center space-x-2">
                              <span className="text-[14px] font-bold block truncate">
                                {loc.name}
                              </span>
                              {loc.category && (
                                <span className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[9px] font-extrabold uppercase tracking-wider shrink-0">
                                  {loc.category}
                                </span>
                              )}
                            </div>
                            {loc.address !== loc.name && (
                              <span className="text-[11px] text-muted-foreground block truncate">
                                {loc.address}
                              </span>
                            )}
                          </div>
                          {isSelected && (
                            <div className="h-6 w-6 rounded-full bg-black text-[#C5FF00] flex items-center justify-center shrink-0 ml-2">
                              <Check className="h-4 w-4" strokeWidth={3} />
                            </div>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  )
}
