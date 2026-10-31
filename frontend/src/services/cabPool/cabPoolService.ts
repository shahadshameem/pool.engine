import {
  collection,
  getDocs,
  addDoc,
  doc,
  getDoc,
  updateDoc,
  serverTimestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"
import { notificationService } from "../notification/notificationService"
import { userService, type UserProfile } from "../user/userService"

export interface CabPoolMember {
  uid: string
  name: string
  college?: string
  department?: string
  phone?: string
  joinedAt: string
}

export type CabPoolStatus = "forming" | "matched" | "completed" | "cancelled"

export interface CabPool {
  id?: string
  originRideId: string
  origin: string
  destination: string
  date: string
  departureTime: string
  members: CabPoolMember[]
  maxCapacity: number
  status: CabPoolStatus
  createdAt?: any
  updatedAt?: any
}

/**
 * Pure helper function to chunk an array of items into groups of specified size (default: 4).
 */
export function chunkArray<T>(array: T[], chunkSize = 4): T[][] {
  const chunks: T[][] = []
  for (let i = 0; i < array.length; i += chunkSize) {
    chunks.push(array.slice(i, i + chunkSize))
  }
  return chunks
}

export const cabPoolService = {
  /**
   * Automatically groups rejected passenger requests into peer cab-sharing pools of up to 4 passengers each.
   */
  async createCabPoolsFromRejectedRequests(
    rideId: string,
    origin: string,
    destination: string,
    date: string,
    departureTime: string,
    rejectedRequests: Array<{ requesterId: string }>
  ): Promise<{ success: boolean; poolsCreated: number; pools: CabPool[] }> {
    if (!rejectedRequests || rejectedRequests.length === 0) {
      return { success: true, poolsCreated: 0, pools: [] }
    }

    // Deduplicate user UIDs
    const uniqueUids = Array.from(new Set(rejectedRequests.map((r) => r.requesterId)))

    // Chunk into pools of max 4 passengers
    const chunks = chunkArray(uniqueUids, 4)
    const createdPools: CabPool[] = []

    for (const chunk of chunks) {
      // Fetch member profiles
      const memberProfiles = await Promise.all(
        chunk.map(async (uid) => {
          try {
            const profile = await userService.getUserProfile(uid)
            return {
              uid,
              name: profile?.name || "Passenger",
              college: profile?.college || "",
              department: profile?.department || "",
              joinedAt: new Date().toISOString()
            } as CabPoolMember
          } catch (e) {
            return {
              uid,
              name: "Passenger",
              joinedAt: new Date().toISOString()
            } as CabPoolMember
          }
        })
      )

      const poolData: Omit<CabPool, "id"> = {
        originRideId: rideId,
        origin,
        destination,
        date,
        departureTime,
        members: memberProfiles,
        maxCapacity: 4,
        status: memberProfiles.length === 4 ? "matched" : "forming",
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      }

      try {
        const poolDocRef = await addDoc(collection(db, "cabPools"), poolData)
        const newPool: CabPool = { id: poolDocRef.id, ...poolData }
        createdPools.push(newPool)

        // Notify each member of their new cab sharing pool
        for (const member of memberProfiles) {
          const coPassengers = memberProfiles
            .filter((m) => m.uid !== member.uid)
            .map((m) => m.name)
            .join(", ")

          const message = coPassengers
            ? `Your ride was full, so we grouped you with ${coPassengers} into a Cab Sharing Pool for ${origin} → ${destination}!`
            : `Your ride was full. We created a Cab Sharing Pool for ${origin} → ${destination} as more passengers join.`

          notificationService.createNotification({
            userId: member.uid,
            type: "cab_pool_invite",
            title: "🚕 Taxi Pool Group Found!",
            message,
            rideId,
            cabPoolId: poolDocRef.id,
            rideSnapshot: {
              from: origin,
              to: destination,
              date,
              time: departureTime,
              seats: memberProfiles.length
            }
          }).catch(console.error)
        }
      } catch (err) {
        console.error("[cabPoolService] Error creating cab pool:", err)
      }
    }

    return {
      success: true,
      poolsCreated: createdPools.length,
      pools: createdPools
    }
  },

  /**
   * Fetches all active cab pools that a user belongs to.
   */
  async getCabPoolsForUser(userId: string): Promise<CabPool[]> {
    try {
      const snap = await getDocs(collection(db, "cabPools"))
      const pools: CabPool[] = []
      snap.docs.forEach((docSnap) => {
        const data = docSnap.data() as CabPool
        if (Array.isArray(data.members) && data.members.some((m) => m.uid === userId)) {
          pools.push({ id: docSnap.id, ...data })
        }
      })
      return pools
    } catch (e) {
      console.error("[cabPoolService] Error fetching pools for user:", e)
      return []
    }
  },

  /**
   * Adds a user to an existing open cab pool if capacity permits (< 4).
   */
  async joinCabPool(poolId: string, userProfile: UserProfile): Promise<{ success: boolean; message: string }> {
    try {
      const poolRef = doc(db, "cabPools", poolId)
      const poolSnap = await getDoc(poolRef)
      if (!poolSnap.exists()) return { success: false, message: "Cab pool not found." }

      const pool = poolSnap.data() as CabPool
      if (pool.members.length >= pool.maxCapacity) {
        return { success: false, message: "Cab pool is already full (max 4 passengers)." }
      }

      if (pool.members.some((m) => m.uid === userProfile.uid)) {
        return { success: false, message: "You are already a member of this cab pool." }
      }

      const newMember: CabPoolMember = {
        uid: userProfile.uid,
        name: userProfile.name || "Passenger",
        college: userProfile.college || "",
        department: userProfile.department || "",
        joinedAt: new Date().toISOString()
      }

      const updatedMembers = [...pool.members, newMember]
      const newStatus: CabPoolStatus = updatedMembers.length === pool.maxCapacity ? "matched" : "forming"

      await updateDoc(poolRef, {
        members: updatedMembers,
        status: newStatus,
        updatedAt: serverTimestamp()
      })

      // Notify existing pool members about the new member
      if (Array.isArray(pool.members) && pool.members.length > 0) {
        pool.members.forEach((member) => {
          if (member.uid && member.uid !== userProfile.uid) {
            notificationService.createNotification({
              userId: member.uid,
              type: "cab_pool_invite",
              title: "New member joined your Taxi Pool!",
              message: `${userProfile.name || "A new member"} has joined your Taxi Pool for ${pool.origin} → ${pool.destination}!`,
              cabPoolId: poolId,
              actorId: userProfile.uid,
              actorSnapshot: {
                name: userProfile.name,
                college: userProfile.college,
                department: userProfile.department,
                year: userProfile.year,
                verified: !!userProfile.collegeVerified
              },
              rideSnapshot: {
                from: pool.origin,
                to: pool.destination,
                date: pool.date,
                time: pool.departureTime,
                seats: updatedMembers.length
              }
            }).catch(console.error)
          }
        })
      }

      return { success: true, message: "Joined cab pool successfully!" }
    } catch (e: any) {
      return { success: false, message: e.message || "Failed to join cab pool." }
    }
  }
}
