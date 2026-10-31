import {
  collection,
  doc,
  setDoc,
  deleteDoc,
  getDocs,
  onSnapshot,
  serverTimestamp,
  Timestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"

export interface LiveUserLocation {
  rideId: string
  userId: string
  userName: string
  isCreator?: boolean         // True if the student posted the trip
  role?: string               // Optional legacy compat field
  lat: number
  lng: number
  heading?: number | null     // Heading in degrees (0-360) for orientation
  speed?: number | null       // Speed in m/s
  accuracy?: number           // GPS Accuracy in meters
  updatedAt?: Timestamp | any // Timestamp of position
  isSharing: boolean         // Whether this participant is currently actively broadcasting
}

/**
 * Computes compass bearing (heading in degrees from 0 to 360) between two points
 */
export function calculateBearing(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const phi1 = (lat1 * Math.PI) / 180
  const phi2 = (lat2 * Math.PI) / 180

  const y = Math.sin(dLng) * Math.cos(phi2)
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLng)

  const brng = (Math.atan2(y, x) * 180) / Math.PI
  return (brng + 360) % 360
}

export const liveLocationService = {
  /**
   * Updates or creates the current user's live position in the ride's liveLocations subcollection.
   */
  async updateLiveLocation(
    rideId: string,
    locationData: Omit<LiveUserLocation, "updatedAt">
  ): Promise<void> {
    if (!rideId || !locationData.userId) return
    const locRef = doc(db, "rides", rideId, "liveLocations", locationData.userId)
    await setDoc(locRef, {
      ...locationData,
      updatedAt: serverTimestamp()
    }, { merge: true })
  },

  /**
   * Removes a specific user's live position document when they stop sharing.
   */
  async deleteLiveLocation(rideId: string, userId: string): Promise<void> {
    if (!rideId || !userId) return
    try {
      const locRef = doc(db, "rides", rideId, "liveLocations", userId)
      await deleteDoc(locRef)
    } catch (err) {
      console.warn(`[liveLocationService] Failed to delete location for user ${userId}:`, err)
    }
  },

  /**
   * Cleans up all live location documents for a ride when it finishes or cancels.
   */
  async cleanupAllLiveLocations(rideId: string): Promise<void> {
    if (!rideId) return
    try {
      const colRef = collection(db, "rides", rideId, "liveLocations")
      const snap = await getDocs(colRef)
      const deletes = snap.docs.map(d => deleteDoc(d.ref))
      await Promise.all(deletes)
    } catch (err) {
      console.warn(`[liveLocationService] Failed to cleanup live locations for ride ${rideId}:`, err)
    }
  },

  /**
   * Subscribes to real-time location broadcasts for all participants in a ride.
   */
  subscribeToLiveLocations(
    rideId: string,
    onUpdate: (locations: Record<string, LiveUserLocation>) => void,
    onError?: (err: Error) => void
  ): () => void {
    if (!rideId) return () => {}

    const colRef = collection(db, "rides", rideId, "liveLocations")
    return onSnapshot(
      colRef,
      (snapshot) => {
        const locationsMap: Record<string, LiveUserLocation> = {}
        snapshot.docs.forEach((docSnap) => {
          const data = docSnap.data() as LiveUserLocation
          if (data && typeof data.lat === "number" && typeof data.lng === "number") {
            locationsMap[docSnap.id] = {
              ...data,
              userId: docSnap.id
            }
          }
        })
        onUpdate(locationsMap)
      },
      (error) => {
        console.warn(`[liveLocationService] onSnapshot error on ride ${rideId}:`, error)
        if (onError) onError(error)
      }
    )
  }
}
