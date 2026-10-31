/**
 * DPDP Consent Service
 * Manages per-purpose consent records as required by the Digital Personal Data
 * Protection Act (DPDPA) 2023, India.
 *
 * ⚠️ LEGAL REVIEW REQUIRED: Purpose descriptions, retention periods, and
 *    withdrawal procedures must be verified by qualified legal counsel before
 *    publishing to end users.
 */
import {
  doc,
  setDoc,
  getDoc,
  serverTimestamp,
  collection,
  addDoc,
  query,
  getDocs,
  orderBy,
  limit,
} from "firebase/firestore"
import { db } from "../../config/firebase"

/** All distinct processing purposes the app uses. Extend if new ones are added. */
export type ConsentPurpose =
  | "essential"         // Strictly necessary for service delivery (legal basis: contract)
  | "analytics"         // Firebase Analytics / crash reporting
  | "notifications"     // Push notifications via FCM
  | "location"          // Hostel / location for ride-matching
  | "marketing"         // Future: re-engagement emails / promotions

/** A single per-purpose consent record */
export interface ConsentRecord {
  uid: string
  purpose: ConsentPurpose
  granted: boolean
  /** ISO 8601 timestamp of when consent was given/revoked */
  timestamp: string
  /** Semver of the Privacy Notice the user consented to */
  privacyPolicyVersion: string
  /** Browser / device info for audit trail */
  userAgent?: string
  /** IP is NOT stored — only a flag that we recorded the event client-side */
  source: "signup" | "onboarding" | "consent_banner" | "settings" | "withdrawal_form"
}

/** Aggregated view of all purposes for one user */
export type ConsentMap = Record<ConsentPurpose, boolean>

/** Current published version of the Privacy Notice */
export const CURRENT_PRIVACY_POLICY_VERSION = "1.0.0-dpdp"

/** Purposes that are essential and cannot be declined */
export const ESSENTIAL_PURPOSES: ConsentPurpose[] = ["essential"]

/** Non-essential purposes that require explicit opt-in */
export const OPTIONAL_PURPOSES: ConsentPurpose[] = [
  "analytics",
  "notifications",
  "location",
  "marketing",
]

export const PURPOSE_LABELS: Record<ConsentPurpose, string> = {
  essential:     "Core Service (required)",
  analytics:     "Performance & Crash Analytics",
  notifications: "Push Notifications",
  location:      "Hostel / Stay Location for Ride Matching",
  marketing:     "Promotional Communications",
}

export const PURPOSE_DESCRIPTIONS: Record<ConsentPurpose, string> = {
  essential:
    "Required to operate the WayMate carpooling service: account management, ride creation, ride requests, and safety features.",
  analytics:
    "Helps us understand app usage and fix crashes faster via Firebase Analytics. No personally identifiable data is shared with third parties for advertising.",
  notifications:
    "Sends you real-time alerts for ride requests, acceptances, and cancellations via Firebase Cloud Messaging.",
  location:
    "Stores your home locality text (not GPS coordinates) to improve ride-matching with nearby students.",
  marketing:
    "Occasional product updates, feature announcements, and tips. You can withdraw at any time.",
}

// ---------------------------------------------------------------------------
// Firestore helpers
// ---------------------------------------------------------------------------

/** Path: users/{uid}/consentRecords/{auto-id} */
const consentLogRef = (uid: string) =>
  collection(db, "users", uid, "consentRecords")

/** Path: users/{uid}/consentState (latest aggregate) */
const consentStateRef = (uid: string) =>
  doc(db, "users", uid, "consentState", "current")

/**
 * Record a consent event and update the user's aggregate consent state.
 * Logs every change for audit trail (DPDPA §6).
 */
export async function recordConsent(
  uid: string,
  purpose: ConsentPurpose,
  granted: boolean,
  source: ConsentRecord["source"]
): Promise<void> {
  const record: Omit<ConsentRecord, "uid"> = {
    purpose,
    granted,
    timestamp: new Date().toISOString(),
    privacyPolicyVersion: CURRENT_PRIVACY_POLICY_VERSION,
    userAgent: navigator?.userAgent?.slice(0, 200) ?? "unknown",
    source,
  }

  // Append to audit log
  await addDoc(consentLogRef(uid), record)

  // Update aggregate state
  await setDoc(
    consentStateRef(uid),
    {
      [purpose]: granted,
      updatedAt: serverTimestamp(),
      privacyPolicyVersion: CURRENT_PRIVACY_POLICY_VERSION,
    },
    { merge: true }
  )
}

/**
 * Bulk-record multiple consents at once (e.g., during signup).
 */
export async function recordBulkConsent(
  uid: string,
  consents: Partial<Record<ConsentPurpose, boolean>>,
  source: ConsentRecord["source"]
): Promise<void> {
  const entries = Object.entries(consents) as [ConsentPurpose, boolean][]
  await Promise.all(
    entries.map(([purpose, granted]) =>
      recordConsent(uid, purpose, granted, source)
    )
  )
}

/**
 * Fetch the latest aggregate consent state for a user.
 * Returns null if no consent has been recorded yet.
 */
export async function getConsentState(uid: string): Promise<ConsentMap | null> {
  if (!uid) return null
  const snap = await getDoc(consentStateRef(uid))
  if (!snap.exists()) return null

  const data = snap.data()
  const result: Partial<ConsentMap> = {}
  const allPurposes: ConsentPurpose[] = [
    "essential",
    "analytics",
    "notifications",
    "location",
    "marketing",
  ]
  for (const p of allPurposes) {
    result[p] = data[p] ?? false
  }
  return result as ConsentMap
}

/**
 * Fetch the full consent audit log for a user (most recent 50 entries).
 * Used for the data-rights "access" response.
 */
export async function getConsentAuditLog(
  uid: string,
  maxEntries = 50
): Promise<(ConsentRecord & { id: string })[]> {
  const q = query(
    consentLogRef(uid),
    orderBy("timestamp", "desc"),
    limit(maxEntries)
  )
  const snap = await getDocs(q)
  return snap.docs.map((d) => ({
    id: d.id,
    uid,
    ...(d.data() as Omit<ConsentRecord, "uid">),
  }))
}

/**
 * Check whether the user has already been shown the consent banner.
 */
export async function hasConsentBeenRecorded(uid: string): Promise<boolean> {
  const snap = await getDoc(consentStateRef(uid))
  return snap.exists()
}
