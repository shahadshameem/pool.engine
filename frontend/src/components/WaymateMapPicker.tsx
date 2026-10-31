import { useState, useEffect, useRef, useMemo } from "react"
import { MapContainer, TileLayer, Marker, Circle, Polyline, Polygon, useMap, useMapEvents } from "react-leaflet"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import {
  MapPin,
  Navigation,
  X,
  ArrowDownUp,
  Sliders,
  Route as RouteIcon,
  Clock,
  CheckCircle2,
  Loader2,
  Layers
} from "lucide-react"
import {
  CAMPUS_PRESETS,
  searchLocations,
  reverseGeocode,
  getCurrentLiveLocation,
  fetchDrivingRoute,
  getH3DiskPolygons,
  type LocationPoint,
  type RouteSummary
} from "../utils/locationService"

export interface SelectedRouteState {
  source: LocationPoint & { radius: number }
  destination: LocationPoint & { radius: number }
  routeSummary?: RouteSummary
}

export interface WaymateMapPickerProps {
  initialSource?: Partial<LocationPoint>
  initialDestination?: Partial<LocationPoint>
  initialSourceRadius?: number
  initialDestRadius?: number
  onRouteSelected?: (state: SelectedRouteState) => void
  onConfirm?: (state: SelectedRouteState) => void
  className?: string
  showRadiusControls?: boolean
  showConfirmButton?: boolean
  confirmButtonText?: string
}

// Crisp HTML/SVG DivIcons for Leaflet (eliminates broken PNG asset paths in Vite)
const sourceMarkerIcon = L.divIcon({
  className: "custom-source-pin",
  html: `<div style="background-color: #2563eb; color: white; width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; box-shadow: 0 4px 12px rgba(37,99,235,0.45); border: 2.5px solid white;">S</div>`,
  iconSize: [34, 34],
  iconAnchor: [17, 17]
})

const destMarkerIcon = L.divIcon({
  className: "custom-dest-pin",
  html: `<div style="background-color: #16a34a; color: white; width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; box-shadow: 0 4px 12px rgba(22,163,74,0.45); border: 2.5px solid white;">D</div>`,
  iconSize: [34, 34],
  iconAnchor: [17, 17]
})

// Controller to auto-pan and fit bounds dynamically
function MapAutoBounds({
  source,
  destination,
  routeCoords
}: {
  source?: LocationPoint | null
  destination?: LocationPoint | null
  routeCoords?: [number, number][]
}) {
  const map = useMap()

  useEffect(() => {
    if (routeCoords && routeCoords.length > 1) {
      map.fitBounds(L.latLngBounds(routeCoords), { padding: [50, 50], maxZoom: 15 })
    } else if (source && destination) {
      const bounds = L.latLngBounds([
        [source.lat, source.lng],
        [destination.lat, destination.lng]
      ])
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 14 })
    } else if (source) {
      map.flyTo([source.lat, source.lng], 14, { duration: 0.8 })
    } else if (destination) {
      map.flyTo([destination.lat, destination.lng], 14, { duration: 0.8 })
    }
  }, [source, destination, routeCoords, map])

  return null
}

// Click listener on map to drop or reposition points
function MapClickListener({
  onMapSelect
}: {
  onMapSelect: (lat: number, lng: number) => void
}) {
  useMapEvents({
    click(e) {
      onMapSelect(e.latlng.lat, e.latlng.lng)
    }
  })
  return null
}

export function WaymateMapPicker({
  initialSource,
  initialDestination,
  initialSourceRadius = 1000,
  initialDestRadius = 1000,
  onRouteSelected,
  onConfirm,
  className = "",
  showRadiusControls = true,
  showConfirmButton = false,
  confirmButtonText
}: WaymateMapPickerProps) {
  // Source & Destination state
  const [source, setSource] = useState<LocationPoint>(() => ({
    name: initialSource?.name || "CET Main Gate, Sreekaryam",
    lat: initialSource?.lat ?? 8.5459,
    lng: initialSource?.lng ?? 76.9063,
    isPreset: true
  }))

  const [destination, setDestination] = useState<LocationPoint>(() => ({
    name: initialDestination?.name || "Kazhakootam Railway Station",
    lat: initialDestination?.lat ?? 8.5666,
    lng: initialDestination?.lng ?? 76.8765,
    isPreset: true
  }))

  // Radius values (in meters)
  const [sourceRadius, setSourceRadius] = useState<number>(initialSourceRadius)
  const [destRadius, setDestRadius] = useState<number>(initialDestRadius)

  // Autocomplete UI inputs
  const [sourceInput, setSourceInput] = useState(source.name)
  const [destInput, setDestInput] = useState(destination.name)
  const [activeSearchField, setActiveSearchField] = useState<"source" | "destination" | null>(null)

  const [suggestions, setSuggestions] = useState<LocationPoint[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [isLocating, setIsLocating] = useState(false)

  // Driving route
  const [routeSummary, setRouteSummary] = useState<RouteSummary | null>(null)
  const [isLoadingRoute, setIsLoadingRoute] = useState(false)

  // Sliders and Uber H3 toggle
  const [showSliders, setShowSliders] = useState(showRadiusControls)
  const [showH3Hexagons, setShowH3Hexagons] = useState(true)

  // Compute Uber H3 Resolution 8 Hexagon Boundary Polygons
  const sourceH3Polygons = useMemo(() => {
    if (!showH3Hexagons || !source.lat || !source.lng) return []
    try {
      return getH3DiskPolygons(source.lat, source.lng, sourceRadius)
    } catch (e) {
      console.warn("H3 source polygons error:", e)
      return []
    }
  }, [showH3Hexagons, source.lat, source.lng, sourceRadius])

  const destH3Polygons = useMemo(() => {
    if (!showH3Hexagons || !destination.lat || !destination.lng) return []
    try {
      return getH3DiskPolygons(destination.lat, destination.lng, destRadius)
    } catch (e) {
      console.warn("H3 dest polygons error:", e)
      return []
    }
  }, [showH3Hexagons, destination.lat, destination.lng, destRadius])

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch OSRM driving route when source or destination changes
  useEffect(() => {
    let isCancelled = false
    async function updateRoute() {
      setIsLoadingRoute(true)
      const summary = await fetchDrivingRoute(source, destination)
      if (!isCancelled) {
        setRouteSummary(summary)
        setIsLoadingRoute(false)
        if (onRouteSelected) {
          onRouteSelected({
            source: { ...source, radius: sourceRadius },
            destination: { ...destination, radius: destRadius },
            routeSummary: summary
          })
        }
      }
    }

    updateRoute()
    return () => {
      isCancelled = true
    }
  }, [source.lat, source.lng, destination.lat, destination.lng, sourceRadius, destRadius])

  // Handle Autocomplete Search with 300ms debounce
  const handleInputChange = (field: "source" | "destination", value: string) => {
    if (field === "source") setSourceInput(value)
    else setDestInput(value)

    setActiveSearchField(field)

    if (debounceTimer.current) clearTimeout(debounceTimer.current)

    if (value.trim().length === 0) {
      setSuggestions(CAMPUS_PRESETS)
      return
    }

    debounceTimer.current = setTimeout(async () => {
      setIsSearching(true)
      const results = await searchLocations(value)
      setSuggestions(results)
      setIsSearching(false)
    }, 300)
  }

  // Handle Selection from suggestions
  const handleSelectLocation = (point: LocationPoint) => {
    if (activeSearchField === "source") {
      setSource(point)
      setSourceInput(point.name)
    } else {
      setDestination(point)
      setDestInput(point.name)
    }
    setActiveSearchField(null)
    setSuggestions([])
  }

  // GPS My Location with Campus Zone auto-assignment
  const handleUseCurrentLocation = async () => {
    setIsLocating(true)
    try {
      const myLoc = await getCurrentLiveLocation()
      setSource(myLoc)
      setSourceInput(myLoc.name)
      if (myLoc.isLowAccuracy) {
        alert(`Low GPS accuracy (±${Math.round(myLoc.accuracyMeters || 0)}m). Please verify or drag your pin on the map.`)
      }
    } catch (err: any) {
      console.warn("GPS error:", err)
      alert(err?.message || "Unable to acquire live GPS position.")
    } finally {
      setIsLocating(false)
    }
  }

  // Map Click to fine-tune
  const handleMapClick = async (lat: number, lng: number) => {
    const targetField = activeSearchField || "destination"
    const address = await reverseGeocode(lat, lng)
    const newPoint: LocationPoint = {
      name: address,
      lat,
      lng,
      isPreset: false,
      address
    }

    if (targetField === "source") {
      setSource(newPoint)
      setSourceInput(address)
    } else {
      setDestination(newPoint)
      setDestInput(address)
    }
  }

  // Swap Locations
  const handleSwap = () => {
    const prevSrc = source
    const prevDst = destination
    setSource(prevDst)
    setSourceInput(prevDst.name)
    setDestination(prevSrc)
    setDestInput(prevSrc.name)
  }

  const defaultCenter: [number, number] = useMemo(() => [8.5459, 76.9063], [])

  return (
    <div className={`w-full bg-card rounded-2xl border border-border/70 overflow-hidden shadow-sm flex flex-col ${className}`}>

      {/* 1. INPUTS HEADER */}
      <div className="p-4 space-y-3 bg-card border-b border-border/40 relative z-20">

        {/* Source Input */}
        <div className="relative">
          <div className="flex items-center space-x-2">
            <div className="h-9 w-9 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0">
              <MapPin className="h-5 w-5" strokeWidth={2.2} />
            </div>
            <div className="flex-1 relative">
              <input
                type="text"
                value={sourceInput}
                onFocus={() => {
                  setActiveSearchField("source")
                  setSuggestions(CAMPUS_PRESETS)
                }}
                onChange={(e) => handleInputChange("source", e.target.value)}
                placeholder="Pickup (e.g. CET Main Gate, Sreekaryam)"
                className="w-full h-11 px-3.5 pr-20 rounded-xl bg-muted/60 border border-border/50 text-[14px] text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500 font-medium"
              />
              <div className="absolute right-2 top-2 flex items-center space-x-1">
                {sourceInput && (
                  <button
                    type="button"
                    onClick={() => { setSourceInput(""); setSuggestions(CAMPUS_PRESETS); }}
                    className="p-1.5 text-muted-foreground hover:text-foreground rounded-md"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
                <button
                  type="button"
                  title="Use My Current Location"
                  onClick={handleUseCurrentLocation}
                  disabled={isLocating}
                  className="p-1.5 text-blue-600 hover:bg-blue-500/10 rounded-md transition-colors"
                >
                  <Navigation className={`h-4 w-4 ${isLocating ? "animate-spin" : ""}`} />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Swap Button Divider */}
        <div className="flex items-center justify-between px-2">
          <div className="h-px bg-border/40 flex-1 ml-11 mr-3" />
          <button
            type="button"
            onClick={handleSwap}
            title="Swap Source and Destination"
            className="h-7 px-2.5 rounded-full bg-muted/80 hover:bg-muted border border-border/60 text-xs font-semibold flex items-center space-x-1 text-muted-foreground hover:text-foreground active:scale-95 transition-all shadow-xs"
          >
            <ArrowDownUp className="h-3 w-3 stroke-[2.5]" />
            <span>Swap</span>
          </button>
        </div>

        {/* Destination Input */}
        <div className="relative">
          <div className="flex items-center space-x-2">
            <div className="h-9 w-9 rounded-xl bg-green-500/10 text-green-600 dark:text-green-400 flex items-center justify-center shrink-0">
              <div className="h-3.5 w-3.5 rounded-full border-[3px] border-green-600 bg-white dark:bg-black" />
            </div>
            <div className="flex-1 relative">
              <input
                type="text"
                value={destInput}
                onFocus={() => {
                  setActiveSearchField("destination")
                  setSuggestions(CAMPUS_PRESETS)
                }}
                onChange={(e) => handleInputChange("destination", e.target.value)}
                placeholder="Destination (e.g. Kazhakootam, LuLu Mall)"
                className="w-full h-11 px-3.5 pr-9 rounded-xl bg-muted/60 border border-border/50 text-[14px] text-foreground focus:outline-none focus:ring-2 focus:ring-green-500 font-medium"
              />
              {destInput && (
                <button
                  type="button"
                  onClick={() => { setDestInput(""); setSuggestions(CAMPUS_PRESETS); }}
                  className="absolute right-2.5 top-2.5 p-1 text-muted-foreground hover:text-foreground rounded-md"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Suggestion Dropdown Overlay */}
        {activeSearchField && (
          <div className="absolute left-4 right-4 top-full mt-1 bg-card border border-border/80 rounded-2xl shadow-xl z-50 max-h-64 overflow-y-auto divide-y divide-border/30">
            <div className="p-2.5 bg-muted/40 flex items-center justify-between text-xs font-semibold text-muted-foreground">
              <span>{isSearching ? "Searching OSM / Photon..." : "Suggestions (Presets & Live Search)"}</span>
              <button
                type="button"
                onClick={() => setActiveSearchField(null)}
                className="text-xs text-primary hover:underline"
              >
                Close
              </button>
            </div>
            {suggestions.map((item, idx) => (
              <button
                key={`${item.name}-${idx}`}
                type="button"
                onClick={() => handleSelectLocation(item)}
                className="w-full p-3 flex items-start space-x-3 text-left hover:bg-muted/70 transition-colors cursor-pointer"
              >
                <MapPin className={`h-4 w-4 mt-0.5 shrink-0 ${item.isPreset ? "text-primary" : "text-muted-foreground"}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center space-x-2">
                    <p className="text-[14px] font-semibold text-foreground truncate">{item.name}</p>
                    {item.isPreset && (
                      <span className="px-1.5 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-extrabold tracking-wider uppercase">
                        {item.category || "Campus"}
                      </span>
                    )}
                  </div>
                  {item.address && item.address !== item.name && (
                    <p className="text-[12px] text-muted-foreground truncate">{item.address}</p>
                  )}
                </div>
              </button>
            ))}
            {suggestions.length === 0 && !isSearching && (
              <p className="p-4 text-center text-xs text-muted-foreground">
                No matching locations found. You can also tap anywhere on the map to set coordinates.
              </p>
            )}
          </div>
        )}
      </div>

      {/* 2. ROUTE SUMMARY BAR */}
      {routeSummary && (
        <div className="px-4 py-2 bg-muted/30 border-b border-border/30 flex items-center justify-between text-xs font-medium text-foreground">
          <div className="flex items-center space-x-3">
            <span className="flex items-center space-x-1 text-primary">
              {isLoadingRoute ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
              ) : (
                <RouteIcon className="h-3.5 w-3.5" />
              )}
              <span className="font-bold">{routeSummary.distanceKm} km</span>
            </span>
            <span className="flex items-center space-x-1 text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>~{routeSummary.durationMins} mins</span>
            </span>
          </div>
          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={() => setShowH3Hexagons(!showH3Hexagons)}
              className={`flex items-center space-x-1 text-xs px-2 py-0.5 rounded-md transition-colors ${
                showH3Hexagons ? "bg-blue-500/15 text-blue-600 dark:text-blue-400 font-bold" : "text-muted-foreground hover:text-foreground"
              }`}
              title="Toggle Uber H3 Hexagonal Spatial Index Grid"
            >
              <Layers className="h-3 w-3" />
              <span>H3 Hex Grid</span>
            </button>
            <button
              type="button"
              onClick={() => setShowSliders(!showSliders)}
              className="flex items-center space-x-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <Sliders className="h-3 w-3" />
              <span>{showSliders ? "Hide Radii" : "Radius Circles"}</span>
            </button>
          </div>
        </div>
      )}

      {/* 3. INTERACTIVE LEAFLET MAP CONTAINER */}
      <div className="relative w-full h-72 sm:h-84 bg-muted/40 z-10">
        <MapContainer
          center={defaultCenter}
          zoom={13}
          scrollWheelZoom={false}
          className="w-full h-full"
        >
          {/* OpenStreetMap Standard Tiles (Zero Key Required) */}
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          <MapAutoBounds
            source={source}
            destination={destination}
            routeCoords={routeSummary?.coordinates}
          />

          <MapClickListener
            onMapSelect={handleMapClick}
          />

          {/* UBER H3 HEXAGONAL SPATIAL GRID (SOURCE) */}
          {showH3Hexagons && sourceH3Polygons.map((polyCoords, i) => (
            <Polygon
              key={`src-h3-${i}`}
              positions={polyCoords}
              pathOptions={{
                color: "#2563eb",
                weight: 1.5,
                dashArray: "3, 4",
                fillColor: "#3b82f6",
                fillOpacity: 0.08
              }}
            />
          ))}

          {/* UBER H3 HEXAGONAL SPATIAL GRID (DESTINATION) */}
          {showH3Hexagons && destH3Polygons.map((polyCoords, i) => (
            <Polygon
              key={`dst-h3-${i}`}
              positions={polyCoords}
              pathOptions={{
                color: "#16a34a",
                weight: 1.5,
                dashArray: "3, 4",
                fillColor: "#22c55e",
                fillOpacity: 0.08
              }}
            />
          ))}

          {/* SOURCE MARKER & CIRCLE */}
          {source && (
            <>
              <Marker
                position={[source.lat, source.lng]}
                icon={sourceMarkerIcon}
                draggable={true}
                eventHandlers={{
                  async dragend(e) {
                    const marker = e.target
                    const pos = marker.getLatLng()
                    const addr = await reverseGeocode(pos.lat, pos.lng)
                    const updated = { ...source, lat: pos.lat, lng: pos.lng, name: addr }
                    setSource(updated)
                    setSourceInput(addr)
                  }
                }}
              />
              <Circle
                center={[source.lat, source.lng]}
                radius={sourceRadius}
                pathOptions={{
                  color: "#2563eb",
                  fillColor: "#2563eb",
                  fillOpacity: 0.12,
                  weight: 2,
                  dashArray: "4, 6"
                }}
              />
            </>
          )}

          {/* DESTINATION MARKER & CIRCLE */}
          {destination && (
            <>
              <Marker
                position={[destination.lat, destination.lng]}
                icon={destMarkerIcon}
                draggable={true}
                eventHandlers={{
                  async dragend(e) {
                    const marker = e.target
                    const pos = marker.getLatLng()
                    const addr = await reverseGeocode(pos.lat, pos.lng)
                    const updated = { ...destination, lat: pos.lat, lng: pos.lng, name: addr }
                    setDestination(updated)
                    setDestInput(addr)
                  }
                }}
              />
              <Circle
                center={[destination.lat, destination.lng]}
                radius={destRadius}
                pathOptions={{
                  color: "#16a34a",
                  fillColor: "#16a34a",
                  fillOpacity: 0.12,
                  weight: 2,
                  dashArray: "4, 6"
                }}
              />
            </>
          )}

          {/* DRIVING ROUTE POLYLINE (OSRM) */}
          {routeSummary && routeSummary.coordinates.length > 0 && (
            <Polyline
              positions={routeSummary.coordinates}
              pathOptions={{
                color: "#6366f1",
                weight: 4,
                opacity: 0.85
              }}
            />
          )}
        </MapContainer>

        {/* Legend Tag */}
        <div className="absolute bottom-2.5 left-2.5 z-[400] bg-background/90 backdrop-blur-xs px-2.5 py-1.5 rounded-lg border border-border/50 text-[11px] font-semibold text-foreground flex items-center space-x-3 shadow-sm pointer-events-none">
          <span className="flex items-center space-x-1">
            <span className="h-2 w-2 rounded-full bg-blue-600 inline-block" />
            <span>Pickup Circle {showH3Hexagons ? "(H3)" : ""}</span>
          </span>
          <span className="flex items-center space-x-1">
            <span className="h-2 w-2 rounded-full bg-green-600 inline-block" />
            <span>Drop Circle {showH3Hexagons ? "(H3)" : ""}</span>
          </span>
          {showH3Hexagons && (
            <span className="text-[10px] text-muted-foreground border-l border-border/60 pl-2">
              Uber H3 Res 8
            </span>
          )}
        </div>
      </div>

      {/* 4. CIRCLE RADIUS SLIDERS */}
      {showSliders && (
        <div className="p-4 bg-muted/20 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <div className="flex justify-between items-center text-xs font-semibold text-foreground">
              <span className="flex items-center space-x-1 text-blue-600 dark:text-blue-400">
                <span className="h-2 w-2 rounded-full bg-blue-600" />
                <span>Pickup Matching Radius</span>
              </span>
              <span className="font-bold">{sourceRadius >= 1000 ? `${(sourceRadius / 1000).toFixed(1)} km` : `${sourceRadius} m`}</span>
            </div>
            <input
              type="range"
              min="200"
              max="5000"
              step="100"
              value={sourceRadius}
              onChange={(e) => setSourceRadius(Number(e.target.value))}
              className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>200m (Strict)</span>
              <span>1 km</span>
              <span>5 km (Wide)</span>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex justify-between items-center text-xs font-semibold text-foreground">
              <span className="flex items-center space-x-1 text-green-600 dark:text-green-400">
                <span className="h-2 w-2 rounded-full bg-green-600" />
                <span>Drop-off Matching Radius</span>
              </span>
              <span className="font-bold">{destRadius >= 1000 ? `${(destRadius / 1000).toFixed(1)} km` : `${destRadius} m`}</span>
            </div>
            <input
              type="range"
              min="200"
              max="5000"
              step="100"
              value={destRadius}
              onChange={(e) => setDestRadius(Number(e.target.value))}
              className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-green-600"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>200m (Strict)</span>
              <span>1 km</span>
              <span>5 km (Wide)</span>
            </div>
          </div>
        </div>
      )}

      {/* 5. CONFIRM ROUTE BUTTON */}
      {(showConfirmButton || Boolean(onConfirm)) && (
        <div className="p-3 bg-card border-t border-border/40">
          <button
            type="button"
            onClick={() => {
              if (onConfirm) {
                onConfirm({
                  source: { ...source, radius: sourceRadius },
                  destination: { ...destination, radius: destRadius },
                  routeSummary: routeSummary || undefined
                })
              }
            }}
            className="w-full h-12 bg-[#C5FF00] text-black font-extrabold rounded-xl flex items-center justify-center space-x-2 shadow-sm hover:opacity-95 active:scale-[0.99] transition-all cursor-pointer"
          >
            <CheckCircle2 className="h-4 w-4" />
            <span>{confirmButtonText || "Confirm Route"}</span>
          </button>
        </div>
      )}
    </div>
  )
}
export default WaymateMapPicker
