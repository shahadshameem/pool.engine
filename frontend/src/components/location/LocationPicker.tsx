import { useState, useEffect, useRef } from "react"
import { MapPin, Navigation, ArrowLeft, Search } from "lucide-react"
import { GoogleMap, useJsApiLoader, Marker } from "@react-google-maps/api"
import { Button } from "../ui/button"
import { Input } from "../ui/input"

export interface LocationValue {
  address: string
  latitude: number
  longitude: number
}

export interface LocationPickerProps {
  label: string
  placeholder: string
  value?: LocationValue
  onChange: (val: LocationValue) => void
  error?: string
}

const libraries: ("places")[] = ["places"]
const DEFAULT_CENTER = { lat: 8.5241, lng: 76.9366 }
const DEFAULT_ZOOM = 11

export function LocationPicker({ label, placeholder, value, onChange, error }: LocationPickerProps) {
  const [isOpen, setIsOpen] = useState(false)
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || ""

  const [authError, setAuthError] = useState(false)

  // Catch Google Maps authentication/billing failures globally
  useEffect(() => {
    // @ts-ignore
    window.gm_authFailure = () => {
      console.error("Google Maps authentication or billing failed.")
      setAuthError(true)
    }
  }, [])

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: apiKey,
    libraries,
  })

  const [map, setMap] = useState<google.maps.Map | null>(null)
  const [tempLocation, setTempLocation] = useState<LocationValue | null>(value || null)
  const [fallbackText, setFallbackText] = useState(value?.address || "")
  const [isLocating, setIsLocating] = useState(false)

  const [searchQuery, setSearchQuery] = useState("")
  const [predictions, setPredictions] = useState<google.maps.places.AutocompletePrediction[]>([])
  const [showPredictions, setShowPredictions] = useState(false)

  const autocompleteService = useRef<google.maps.places.AutocompleteService | null>(null)
  const placesService = useRef<google.maps.places.PlacesService | null>(null)
  const sessionTokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(null)
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (isLoaded && !autocompleteService.current && window.google) {
      autocompleteService.current = new window.google.maps.places.AutocompleteService()
    }
  }, [isLoaded])

  const handleOpen = () => setIsOpen(true)
  const handleClose = () => setIsOpen(false)

  const handleConfirm = () => {
    if (apiKey && tempLocation) {
      if (tempLocation.address.trim().length > 0) {
        onChange({ ...tempLocation, address: tempLocation.address.trim() })
      }
    } else if (!apiKey && fallbackText.trim().length > 0) {
      onChange({ address: fallbackText.trim(), latitude: 0, longitude: 0 })
    }
    setIsOpen(false)
  }

  const getCurrentLocation = () => {
    setIsLocating(true)
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const lat = position.coords.latitude
          const lng = position.coords.longitude
          map?.panTo({ lat, lng })
          map?.setZoom(15)

          if (window.google) {
            const geocoder = new window.google.maps.Geocoder()
            geocoder.geocode({ location: { lat, lng } }, (results, status) => {
              if (status === "OK" && results && results[0]) {
                setTempLocation({
                  latitude: lat,
                  longitude: lng,
                  address: results[0].formatted_address
                })
              }
            })
          }
          setIsLocating(false)
        },
        () => {
          setIsLocating(false)
          alert("Could not get your location. Please check permissions.")
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      )
    } else {
      setIsLocating(false)
    }
  }

  const handleMapClick = (e: google.maps.MapMouseEvent) => {
    if (e.latLng && window.google) {
      const lat = e.latLng.lat()
      const lng = e.latLng.lng()

      const geocoder = new window.google.maps.Geocoder()
      geocoder.geocode({ location: { lat, lng } }, (results, status) => {
        if (status === "OK" && results && results[0]) {
          setTempLocation({
            latitude: lat,
            longitude: lng,
            address: results[0].formatted_address
          })
        }
      })
    }
  }

  const handleSearchInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setSearchQuery(val)

    if (debounceTimer.current) clearTimeout(debounceTimer.current)

    if (val.trim().length > 2) {
      if (!sessionTokenRef.current && window.google) {
        sessionTokenRef.current = new window.google.maps.places.AutocompleteSessionToken()
      }

      debounceTimer.current = setTimeout(() => {
        if (autocompleteService.current) {
          const request: google.maps.places.AutocompletionRequest = {
            input: val,
            componentRestrictions: { country: "in" },
            locationBias: {
              radius: 50000,
              center: { lat: 8.5241, lng: 76.9366 } // Trivandrum bias
            }
          }
          if (sessionTokenRef.current) {
            request.sessionToken = sessionTokenRef.current
          }

          autocompleteService.current.getPlacePredictions(request, (results, status) => {
            if (status === window.google.maps.places.PlacesServiceStatus.OK && results) {
              setPredictions(results)
              setShowPredictions(true)
            } else {
              setPredictions([])
            }
          })
        }
      }, 300)
    }
  }

  const handlePredictionSelect = (prediction: google.maps.places.AutocompletePrediction) => {
    setShowPredictions(false)
    setSearchQuery(prediction.structured_formatting.main_text)

    if (!window.google) return

    if (!placesService.current && map) {
      placesService.current = new window.google.maps.places.PlacesService(map)
    } else if (!placesService.current) {
      placesService.current = new window.google.maps.places.PlacesService(document.createElement('div'))
    }

    const detailRequest: google.maps.places.PlaceDetailsRequest = {
      placeId: prediction.place_id,
      fields: ['name', 'formatted_address', 'geometry']
    }
    if (sessionTokenRef.current) {
      detailRequest.sessionToken = sessionTokenRef.current
    }

    placesService.current.getDetails(detailRequest, (place, status) => {
      // Session token consumed; reset for subsequent user searches to bundle billable requests
      sessionTokenRef.current = null

      if (status === window.google.maps.places.PlacesServiceStatus.OK && place && place.geometry && place.geometry.location) {
        const lat = place.geometry.location.lat()
        const lng = place.geometry.location.lng()
        const address = place.formatted_address || place.name || prediction.description

        setTempLocation({ latitude: lat, longitude: lng, address })
        map?.panTo({ lat, lng })
        map?.setZoom(15)
      }
    })
  }

  const isFailed = !apiKey || loadError || authError

  return (
    <div className="space-y-1.5 w-full">
      <Input
        label={label}
        placeholder={placeholder}
        value={value?.address || ""}
        readOnly
        onClick={handleOpen}
        leftIcon={<MapPin className="h-5 w-5 text-muted-foreground" />}
        error={error}
        className="cursor-pointer bg-card hover:bg-accent/50 transition-colors"
      />

      {isOpen && (
        <div className="fixed inset-0 z-[100] flex flex-col bg-background animate-in slide-in-from-bottom-2">

          {/* Top Search Header */}
          <div className="flex items-center p-3 gap-3 bg-background z-20">
            <button
              onClick={handleClose}
              className="h-[44px] w-[44px] flex items-center justify-center rounded-full bg-transparent text-foreground active:bg-secondary transition-colors shrink-0"
            >
              <ArrowLeft className="h-6 w-6" />
            </button>
            <div className="flex-1 relative">
              <div className="flex items-center bg-secondary h-[52px] rounded-[18px] border border-border px-4 focus-within:border-primary transition-colors">
                <Search className="h-5 w-5 text-primary mr-3 shrink-0" />
                <input
                  type="text"
                  placeholder="Search location..."
                  value={searchQuery}
                  onChange={handleSearchInput}
                  onFocus={() => { if (predictions.length > 0) setShowPredictions(true) }}
                  className="bg-transparent border-none outline-none text-foreground placeholder:text-muted-foreground w-full text-[15px]"
                />
              </div>

              {/* Autocomplete Dropdown */}
              {showPredictions && predictions.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-2 bg-secondary rounded-[16px] border border-border shadow-xl overflow-hidden max-h-[50vh] overflow-y-auto">
                  {predictions.map((prediction) => (
                    <div
                      key={prediction.place_id}
                      className="px-4 py-3 hover:bg-secondary cursor-pointer flex items-center gap-3 border-b border-border last:border-0"
                      onClick={() => handlePredictionSelect(prediction)}
                    >
                      <MapPin className="h-5 w-5 text-primary shrink-0" />
                      <div className="flex flex-col flex-1 min-w-0">
                        <span className="font-semibold text-foreground text-[15px] truncate">
                          {prediction.structured_formatting.main_text}
                        </span>
                        <span className="text-[13px] text-muted-foreground truncate">
                          {prediction.structured_formatting.secondary_text}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Map Area */}
          <div className="flex-1 relative bg-background">
            {isFailed ? (
              <div className="flex flex-col items-center justify-center min-h-full p-6 text-center space-y-4 pb-8">
                <div className="bg-destructive/10 p-4 rounded-full">
                  <MapPin className="h-10 w-10 text-destructive" />
                </div>
                <div>
                  <h3 className="font-bold text-[20px] text-foreground">Map unavailable</h3>
                  <p className="text-muted-foreground text-[15px] mt-2 max-w-[280px] mx-auto">
                    Please check your connection and try again.
                  </p>
                </div>
                <Button variant="secondary" onClick={() => window.location.reload()} className="mt-4 bg-secondary text-foreground">
                  Retry
                </Button>

                {/* Fallback Entry if needed */}
                <div className="w-full max-w-sm bg-secondary p-5 rounded-[20px] border border-border text-left mt-8 space-y-3">
                  <label className="text-[14px] font-semibold text-foreground">Or enter manually</label>
                  <input
                    type="text"
                    value={fallbackText}
                    onChange={(e) => setFallbackText(e.target.value)}
                    placeholder="e.g. CET Campus, Trivandrum"
                    className="flex h-[52px] w-full rounded-[16px] border border-border bg-background px-4 text-[15px] text-foreground focus:border-primary focus:outline-none placeholder:text-muted-foreground"
                  />
                  <Button
                    className="w-full h-[52px] rounded-[16px] bg-primary text-primary-foreground font-bold"
                    disabled={fallbackText.trim().length === 0}
                    onClick={handleConfirm}
                  >
                    Confirm Location
                  </Button>
                </div>
              </div>
            ) : !isLoaded ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full" />
              </div>
            ) : (
              <div className="w-full h-full" onClick={() => setShowPredictions(false)}>
                <GoogleMap
                  mapContainerStyle={{ width: "100%", height: "100%" }}
                  center={tempLocation ? { lat: tempLocation.latitude, lng: tempLocation.longitude } : DEFAULT_CENTER}
                  zoom={tempLocation ? 15 : DEFAULT_ZOOM}
                  onLoad={setMap}
                  onClick={handleMapClick}
                  options={{
                    disableDefaultUI: true,
                    zoomControl: false,
                    clickableIcons: false,
                    backgroundColor: "#FFFFFF"
                  }}
                >
                  {tempLocation && (
                    <Marker
                      position={{ lat: tempLocation.latitude, lng: tempLocation.longitude }}
                      icon={{
                        path: window.google.maps.SymbolPath.CIRCLE,
                        fillColor: "#E52E3D",
                        fillOpacity: 1,
                        strokeWeight: 2,
                        strokeColor: "#FFFFFF",
                        scale: 10
                      }}
                    />
                  )}
                </GoogleMap>

                {/* Current Location Floating Button */}
                <button
                  className={`absolute bottom-4 right-4 h-[44px] w-[44px] flex items-center justify-center rounded-full shadow-lg border border-border bg-background transition-colors active:bg-secondary`}
                  onClick={(e) => { e.stopPropagation(); getCurrentLocation(); }}
                  disabled={isLocating}
                  aria-label="Current Location"
                >
                  <Navigation className={`h-5 w-5 ${isLocating ? "text-primary animate-pulse" : "text-foreground"}`} />
                </button>
              </div>
            )}
          </div>

          {/* Selected Location Bottom Panel */}
          {(!isFailed) && (
            <div className="bg-background rounded-t-[24px] p-5 pb-safe z-20 shadow-[0_-10px_40px_rgba(0,0,0,0.4)]">
              <div className="mb-5">
                <p className="text-[12px] font-semibold text-primary uppercase tracking-wider mb-2">
                  Selected Location
                </p>
                {tempLocation?.address ? (
                  <>
                    <h3 className="font-bold text-[18px] text-foreground leading-tight truncate">
                      {tempLocation.address.split(",")[0]}
                    </h3>
                    <p className="text-[14px] text-muted-foreground mt-1 truncate">
                      {tempLocation.address.split(",").slice(1).join(",").trim() || "Kerala, India"}
                    </p>
                  </>
                ) : (
                  <p className="font-medium text-[16px] text-foreground">
                    Tap on the map or search above
                  </p>
                )}
              </div>
              <button
                className="w-full flex items-center justify-center h-[56px] rounded-[16px] bg-primary text-primary-foreground font-bold text-[16px] disabled:opacity-50 disabled:bg-secondary disabled:text-muted-foreground transition-colors"
                disabled={!tempLocation || !tempLocation.address}
                onClick={handleConfirm}
              >
                Confirm Location
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
