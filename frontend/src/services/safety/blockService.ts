import {
  collection,
  doc,
  setDoc,
  deleteDoc,
  getDocs,
  serverTimestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"

export interface BlockRecord {
  id?: string
  blockerId: string
  blockedId: string
  reason?: string
  createdAt?: any
}

// In-memory cache for quick lookup of blocked IDs per user
const blockCache = new Map<string, { blockedIds: Set<string>; timestamp: number }>()
const CACHE_TTL_MS = 2 * 60 * 1000 // 2 minutes cache TTL

export const blockService = {
  /**
   * Blocks a target user so neither party can see/interact in ride matching.
   */
  async blockUser(currentUserId: string, targetUserId: string, reason?: string): Promise<{ success: boolean; message: string }> {
    if (!currentUserId || !targetUserId) return { success: false, message: "Invalid user identifiers." }
    if (currentUserId === targetUserId) return { success: false, message: "You cannot block yourself." }

    try {
      const blockRef = doc(db, `users/${currentUserId}/blockedUsers`, targetUserId)

      await setDoc(blockRef, {
        blockerId: currentUserId,
        blockedId: targetUserId,
        reason: reason || "User blocked",
        createdAt: serverTimestamp()
      }, { merge: true })

      // Invalidate cache
      blockCache.delete(currentUserId)
      blockCache.delete(targetUserId)

      return { success: true, message: "User has been blocked." }
    } catch (e: any) {
      console.error("Failed to block user:", e)
      return { success: false, message: e.message || "Failed to block user." }
    }
  },

  /**
   * Unblocks a previously blocked user.
   */
  async unblockUser(currentUserId: string, targetUserId: string): Promise<{ success: boolean; message: string }> {
    if (!currentUserId || !targetUserId) return { success: false, message: "Invalid user identifiers." }

    try {
      const blockRef = doc(db, `users/${currentUserId}/blockedUsers`, targetUserId)
      await deleteDoc(blockRef)

      blockCache.delete(currentUserId)
      blockCache.delete(targetUserId)

      return { success: true, message: "User has been unblocked." }
    } catch (e: any) {
      console.error("Failed to unblock user:", e)
      return { success: false, message: e.message || "Failed to unblock user." }
    }
  },

  /**
   * Returns a set of user IDs blocked by currentUserId.
   */
  async getBlockedUserIds(currentUserId: string, forceRefresh = false): Promise<Set<string>> {
    if (!currentUserId) return new Set()

    const now = Date.now()
    const cached = blockCache.get(currentUserId)
    if (!forceRefresh && cached && (now - cached.timestamp < CACHE_TTL_MS)) {
      return cached.blockedIds
    }

    try {
      const colRef = collection(db, `users/${currentUserId}/blockedUsers`)
      const snap = await getDocs(colRef)
      const blockedSet = new Set<string>()

      snap.docs.forEach(d => {
        blockedSet.add(d.id)
        if (d.data()?.blockedId) {
          blockedSet.add(d.data().blockedId)
        }
      })

      blockCache.set(currentUserId, { blockedIds: blockedSet, timestamp: now })
      return blockedSet
    } catch (e) {
      console.error("Failed to fetch blocked user IDs:", e)
      return new Set()
    }
  },

  /**
   * Checks if either user A has blocked user B, or user B has blocked user A.
   */
  async isBlockedRelationship(userAId: string, userBId: string): Promise<boolean> {
    if (!userAId || !userBId || userAId === userBId) return false

    try {
      const [blockedByA, blockedByB] = await Promise.all([
        this.getBlockedUserIds(userAId),
        this.getBlockedUserIds(userBId)
      ])

      return blockedByA.has(userBId) || blockedByB.has(userAId)
    } catch (e) {
      console.error("Failed to check blocked relationship:", e)
      return false
    }
  }
}
