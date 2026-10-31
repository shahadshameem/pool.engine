import {
  collection,
  addDoc,
  getDocs,
  doc,
  query,
  where,
  orderBy,
  limit,
  serverTimestamp,
  updateDoc
} from "firebase/firestore"
import { db } from "../../config/firebase"
import { userService } from "../user/userService"

export interface VerificationHelpRequest {
  id?: string
  userId: string
  userName: string
  userEmail: string
  userCollege?: string
  userDepartment?: string
  reason: string
  status: "pending" | "reviewed" | "resolved"
  createdAt?: any
  updatedAt?: any
  adminNotes?: string
}

export const verificationHelpService = {
  /**
   * Submits a verification help escalation request for an administrator to review.
   */
  async submitHelpRequest(userId: string, reason: string): Promise<{ success: boolean; message: string; id?: string }> {
    try {
      if (!userId) return { success: false, message: "User identity missing." }
      if (!reason.trim()) return { success: false, message: "Please enter a reason for your help request." }

      const profile = await userService.getUserProfile(userId, true)
      if (!profile) return { success: false, message: "User profile not found." }

      // Check if user already has a pending help request
      const qPending = query(
        collection(db, "verificationHelpRequests"),
        where("userId", "==", userId),
        where("status", "==", "pending")
      )
      const pendingSnap = await getDocs(qPending).catch(() => null)
      if (pendingSnap && !pendingSnap.empty) {
        return {
          success: false,
          message: "You already have a verification help request under review by campus admins."
        }
      }

      const reqData: Omit<VerificationHelpRequest, "id"> = {
        userId,
        userName: profile.name || "Student",
        userEmail: profile.email || "",
        userCollege: profile.college || "",
        userDepartment: profile.department || "",
        reason: reason.trim(),
        status: "pending",
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      }

      const docRef = await addDoc(collection(db, "verificationHelpRequests"), reqData)
      return {
        success: true,
        id: docRef.id,
        message: "Verification help request submitted. An admin will review your credentials shortly."
      }
    } catch (e: any) {
      console.error("[verificationHelpService] Submit failed:", e)
      return { success: false, message: e?.message || "Failed to submit verification help request." }
    }
  },

  /**
   * Fetches the user's latest verification help request.
   */
  async getUserLatestRequest(userId: string): Promise<VerificationHelpRequest | null> {
    try {
      const q = query(
        collection(db, "verificationHelpRequests"),
        where("userId", "==", userId),
        orderBy("createdAt", "desc"),
        limit(1)
      )
      const snap = await getDocs(q)
      if (snap.empty) return null
      return { id: snap.docs[0].id, ...snap.docs[0].data() } as VerificationHelpRequest
    } catch (e) {
      return null
    }
  },

  /**
   * Admin fetches all pending verification help escalation requests.
   */
  async getPendingHelpRequests(): Promise<VerificationHelpRequest[]> {
    try {
      const q = query(
        collection(db, "verificationHelpRequests"),
        where("status", "==", "pending"),
        orderBy("createdAt", "desc")
      )
      const snap = await getDocs(q)
      return snap.docs.map(d => ({ id: d.id, ...d.data() } as VerificationHelpRequest))
    } catch (e) {
      return []
    }
  },

  /**
   * Admin resolves or closes a verification help request.
   */
  async resolveHelpRequest(requestId: string, status: "reviewed" | "resolved", adminNotes?: string): Promise<boolean> {
    try {
      const ref = doc(db, "verificationHelpRequests", requestId)
      await updateDoc(ref, {
        status,
        adminNotes: adminNotes || "",
        updatedAt: serverTimestamp()
      })
      return true
    } catch (e) {
      console.error("[verificationHelpService] Resolve failed:", e)
      return false
    }
  }
}
