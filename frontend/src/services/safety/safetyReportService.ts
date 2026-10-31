import {
  collection,
  addDoc,
  getDocs,
  query,
  where,
  serverTimestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"
import { userService } from "../user/userService"
import { notificationService } from "../notification/notificationService"

export type SafetyReportCategory =
  | "wrong_profile_information"
  | "phone_misuse"
  | "harassment"
  | "inappropriate_behavior"
  | "impersonation"
  | "safety_concern"
  | "other"

export type SafetyReportStatus =
  | "submitted"
  | "under_review"
  | "resolved"
  | "dismissed"

export interface SafetyReport {
  id?: string
  reporterId: string
  reporterName?: string
  reporterEmail?: string
  reportedUserId: string
  reportedUserName?: string
  rideId?: string
  rideRequestId?: string
  category: SafetyReportCategory
  description?: string
  status: SafetyReportStatus
  adminNotes?: string
  createdAt?: any
  updatedAt?: any
}

export const safetyReportService = {
  /**
   * Submits a safety report for a user or ride interaction.
   */
  async submitReport(data: {
    reporterId: string
    reportedUserId: string
    rideId?: string
    rideRequestId?: string
    category: SafetyReportCategory
    description?: string
  }): Promise<{ success: boolean; reportId?: string; message: string }> {
    try {
      if (!data.reporterId || !data.reportedUserId) {
        return { success: false, message: "Invalid reporter or reported user." }
      }
      if (data.reporterId === data.reportedUserId) {
        return { success: false, message: "You cannot report yourself." }
      }

      const [reporterProfile, reportedProfile] = await Promise.all([
        userService.getUserProfile(data.reporterId),
        userService.getUserProfile(data.reportedUserId)
      ])

      const reportsRef = collection(db, "reports")
      const docRef = await addDoc(reportsRef, {
        reporterId: data.reporterId,
        reporterName: reporterProfile?.name || "Student",
        reporterEmail: reporterProfile?.email || "",
        reportedUserId: data.reportedUserId,
        reportedUserName: reportedProfile?.name || "User",
        rideId: data.rideId || "",
        rideRequestId: data.rideRequestId || "",
        category: data.category,
        description: data.description?.trim() || "",
        status: "submitted",
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })

      // Send confirmation notification to reporter
      notificationService.createNotification({
        userId: data.reporterId,
        type: "request_cancelled", // Uses existing notification delivery pipeline
        title: "Report submitted",
        message: "Your safety report has been received. Our team will review it promptly.",
        rideId: data.rideId
      }).catch(console.error)

      return { success: true, reportId: docRef.id, message: "Report submitted successfully." }
    } catch (e: any) {
      console.error("Failed to submit safety report:", e)
      return { success: false, message: e.message || "Failed to submit report." }
    }
  },

  /**
   * Fetches safety reports filed by a specific user.
   */
  async getMyReports(reporterId: string): Promise<SafetyReport[]> {
    try {
      const q = query(
        collection(db, "reports"),
        where("reporterId", "==", reporterId)
      )
      const snap = await getDocs(q)
      return snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as SafetyReport))
    } catch (e) {
      console.error("Failed to fetch my reports:", e)
      return []
    }
  }
}
