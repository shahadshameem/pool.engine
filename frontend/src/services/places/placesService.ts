import { useState, useEffect } from "react"
import { collection, getDocs, onSnapshot } from "firebase/firestore"
import { db } from "../../config/firebase"
import { FIXED_LOCATIONS, type FixedLocation } from "../../config/locations"

export interface WaymatePlace {
  id: string
  name: string
  address: string
  latitude: number
  longitude: number
  category?: string
  priority?: number
  verified?: boolean
  searchable?: boolean
}

// In-memory cache for fast renders
let cachedPlaces: FixedLocation[] = [...FIXED_LOCATIONS]

export const placesService = {
  /**
   * Fetches all campus places from Firestore waymate_places,
   * merged with predefined FIXED_LOCATIONS to ensure zero breakage.
   */
  async getPlaces(): Promise<FixedLocation[]> {
    try {
      const snap = await getDocs(collection(db, "waymate_places"))
      if (snap.empty) {
        return FIXED_LOCATIONS
      }

      const firestorePlaces: FixedLocation[] = snap.docs
        .map(d => {
          const data = d.data()
          if (data.searchable === false) return null

          return {
            id: d.id,
            name: data.name || "Campus Location",
            address: data.address || data.name || "",
            latitude: typeof data.latitude === "number" ? data.latitude : 8.5458,
            longitude: typeof data.longitude === "number" ? data.longitude : 76.9032
          } as FixedLocation
        })
        .filter(Boolean) as FixedLocation[]

      // Merge with FIXED_LOCATIONS ensuring unique IDs
      const mergedMap = new Map<string, FixedLocation>()
      for (const loc of FIXED_LOCATIONS) {
        mergedMap.set(loc.id, loc)
      }
      for (const loc of firestorePlaces) {
        mergedMap.set(loc.id, loc)
      }

      cachedPlaces = Array.from(mergedMap.values())
      return cachedPlaces
    } catch (e) {
      console.warn("[placesService] Firestore fetch error, returning fallback places:", e)
      return FIXED_LOCATIONS
    }
  }
}

/**
   * React hook to subscribe to dynamic campus places.
   */
export function usePlaces() {
  const [places, setPlaces] = useState<FixedLocation[]>(cachedPlaces)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let unsubscribe = () => {}

    try {
      unsubscribe = onSnapshot(
        collection(db, "waymate_places"),
        (snap) => {
          if (!snap.empty) {
            const list: FixedLocation[] = snap.docs
              .map(d => {
                const data = d.data()
                if (data.searchable === false) return null
                return {
                  id: d.id,
                  name: data.name || "Campus Location",
                  address: data.address || data.name || "",
                  latitude: typeof data.latitude === "number" ? data.latitude : 8.5458,
                  longitude: typeof data.longitude === "number" ? data.longitude : 76.9032
                } as FixedLocation
              })
              .filter(Boolean) as FixedLocation[]

            const mergedMap = new Map<string, FixedLocation>()
            for (const loc of FIXED_LOCATIONS) {
              mergedMap.set(loc.id, loc)
            }
            for (const loc of list) {
              mergedMap.set(loc.id, loc)
            }

            const merged = Array.from(mergedMap.values())
            cachedPlaces = merged
            setPlaces(merged)
          } else {
            setPlaces(FIXED_LOCATIONS)
          }
          setLoading(false)
        },
        (err) => {
          console.warn("[usePlaces] Live places subscription error:", err)
          setPlaces(FIXED_LOCATIONS)
          setLoading(false)
        }
      )
    } catch (e) {
      setPlaces(FIXED_LOCATIONS)
      setLoading(false)
    }

    return () => unsubscribe()
  }, [])

  return { places, loading }
}
