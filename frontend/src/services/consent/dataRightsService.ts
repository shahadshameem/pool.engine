/**
 * Data Rights Service
 * Handles DPDPA §12-14 data-principal rights:
 *   - Access/Portability (§12)
 *   - Correction & Erasure (§13)
 *   - Grievance & Withdrawal (§14)
 *
 * ⚠️ LEGAL REVIEW REQUIRED: Request handling SLAs, escalation paths, and
 *    board notification procedures must be confirmed by qualified legal counsel.
 */
import {
  collection,
  addDoc,
  serverTimestamp,
  query,
  where,
  getDocs,
  orderBy,
  limit,
} from "firebase/firestore"
import { db } from "../../config/firebase"

export type DataRightsRequestType =
  | "access"       // §12: Request copy of personal data
  | "correction"   // §13(1): Request to correct inaccurate data
  | "erasure"      // §13(2): Request to erase data
  | "withdrawal"   // §14: Withdraw consent
  | "grievance"    // §13(3): File a complaint with Grievance Officer
  | "nomination"   // §14(4): Nominate someone to exercise rights on death/incapacity

export interface DataRightsRequest {
  uid: string
  email: string
  name: string
  type: DataRightsRequestType
  details: string
  submittedAt: string  // ISO 8601
  status: "pending" | "in_review" | "completed" | "rejected"
  /** Ticket ID for communication */
  ticketId?: string
}

/** Grievance officer contact (DPDPA §13(3)) — ⚠️ LAWYER REVIEW: update before go-live */
export const GRIEVANCE_OFFICER = {
  name: "Grievance Officer – WayMate", // ⚠️ LEGAL: Real person name required
  email: "icvalley@proton.me",
  address: "WayMate, Trivandrum, Kerala, India", // ⚠️ LEGAL: Full postal address required
  responseTimeDays: 30,  // DPDPA §13(3): 30 days response time
  escalationAuthority: "Data Protection Board of India (https://dpboard.gov.in)",
}

/**
 * Submit a data rights request.
 * Returns the auto-generated Firestore document ID as the ticket ID.
 */
export async function submitDataRightsRequest(
  uid: string,
  email: string,
  name: string,
  type: DataRightsRequestType,
  details: string
): Promise<string> {
  const request: Omit<DataRightsRequest, "ticketId"> = {
    uid,
    email,
    name,
    type,
    details,
    submittedAt: new Date().toISOString(),
    status: "pending",
  }

  const docRef = await addDoc(
    collection(db, "dataRightsRequests"),
    {
      ...request,
      createdAt: serverTimestamp(),
    }
  )

  return docRef.id
}

/**
 * Fetch all pending data rights requests for a given user.
 */
export async function getUserDataRightsRequests(
  uid: string
): Promise<(DataRightsRequest & { id: string })[]> {
  const q = query(
    collection(db, "dataRightsRequests"),
    where("uid", "==", uid),
    orderBy("submittedAt", "desc"),
    limit(20)
  )
  const snap = await getDocs(q)
  return snap.docs.map((d) => ({
    id: d.id,
    ...(d.data() as DataRightsRequest),
  }))
}

/** Human-readable labels for request types */
export const REQUEST_TYPE_LABELS: Record<DataRightsRequestType, string> = {
  access:     "Request a copy of my data",
  correction: "Correct my personal data",
  erasure:    "Erase my personal data",
  withdrawal: "Withdraw consent",
  grievance:  "File a grievance",
  nomination: "Nominate a representative",
}

export const REQUEST_TYPE_DESCRIPTIONS: Record<DataRightsRequestType, string> = {
  access:
    "Receive a summary of the personal data WayMate holds about you (name, email, phone, college, ride history, and consent records).",
  correction:
    "Ask us to correct inaccurate or incomplete personal data we hold about you.",
  erasure:
    "Request deletion of your account and all associated personal data. Note: anonymised ride history may be retained for safety audits.",
  withdrawal:
    "Withdraw previously granted consent for optional data processing. Essential processing required for the service cannot be stopped without account deletion.",
  grievance:
    "File a formal complaint with our Grievance Officer if you believe your data rights have been violated.",
  nomination:
    "Nominate a person to exercise your data rights on your behalf in case of death or incapacity, as provided under DPDPA §14(4).",
}
