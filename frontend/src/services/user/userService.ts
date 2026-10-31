import { doc, setDoc, getDoc, updateDoc, serverTimestamp, deleteDoc, collection, query, where, getDocs, writeBatch, addDoc, documentId } from "firebase/firestore"
import { deleteUser } from "firebase/auth"
import { db, auth } from "../../config/firebase"
import { isRideExpired } from "../../config/matchingConfig"

export interface NotificationPreferences {
  enabled: boolean
  rideRequests: boolean
  requestUpdates: boolean
  rideCancellations: boolean
  requestCancellations: boolean
}

export const defaultNotificationPreferences: NotificationPreferences = {
  enabled: true,
  rideRequests: true,
  requestUpdates: true,
  rideCancellations: true,
  requestCancellations: true
}

export type Gender = "male" | "female"
export type VerificationStatus = "unverified" | "pending" | "verified" | "rejected"
export type AccountStatus = "active" | "restricted" | "suspended"

export interface UserProfile {
  uid: string
  name: string
  email: string
  phone?: string
  college: string
  department: string
  year: string
  gender?: Gender
  emailVerified: boolean
  collegeVerified: boolean
  genderVerificationStatus?: VerificationStatus
  accountStatus?: AccountStatus
  notificationPreferences?: NotificationPreferences
  role?: "admin" | "user"
  admin?: boolean
  homeLocation?: string
  createdAt?: any
  updatedAt?: any
}

// In-memory User Profile Cache to drastically reduce Firestore Reads
const profileCache = new Map<string, { profile: UserProfile | null; timestamp: number }>()
const CACHE_TTL_MS = 5 * 60 * 1000 // 5 minutes cache TTL

export const userService = {
  /**
   * Checks if a phone number is available (not claimed by another user).
   */
  async checkPhoneAvailability(phone: string, currentUid?: string): Promise<boolean> {
    const cleanPhone = phone.replace(/\D/g, "").slice(-10)
    if (!cleanPhone || cleanPhone.length < 10) return false

    const phoneRef = doc(db, "phoneNumbers", cleanPhone)
    const phoneSnap = await getDoc(phoneRef)
    if (!phoneSnap.exists()) return true
    return phoneSnap.data()?.uid === currentUid
  },

  /**
   * Claims or re-assigns a phone number in the phoneNumbers registry.
   */
  async claimPhoneNumber(phone: string, uid: string, previousPhone?: string): Promise<string> {
    const cleanPhone = phone.replace(/\D/g, "").slice(-10)
    if (!cleanPhone || cleanPhone.length < 10) {
      throw new Error("Invalid phone number. Must be a valid 10-digit number.")
    }

    const phoneRef = doc(db, "phoneNumbers", cleanPhone)
    const phoneSnap = await getDoc(phoneRef)
    if (phoneSnap.exists() && phoneSnap.data()?.uid !== uid) {
      throw new Error("This phone number is already registered to another account.")
    }

    // Claim the phone number
    await setDoc(phoneRef, {
      uid,
      phoneNumber: cleanPhone,
      updatedAt: serverTimestamp(),
      createdAt: phoneSnap.exists() ? (phoneSnap.data()?.createdAt || serverTimestamp()) : serverTimestamp(),
    }, { merge: true })

    // If previously claimed a different phone number, release the old one
    if (previousPhone) {
      const cleanPrev = previousPhone.replace(/\D/g, "").slice(-10)
      if (cleanPrev && cleanPrev !== cleanPhone) {
        await deleteDoc(doc(db, "phoneNumbers", cleanPrev)).catch(console.warn)
      }
    }

    return cleanPhone
  },

  /**
   * Releases a phone number registration.
   */
  async releasePhoneNumber(phone: string, uid: string): Promise<void> {
    const cleanPhone = phone.replace(/\D/g, "").slice(-10)
    if (!cleanPhone) return
    const phoneRef = doc(db, "phoneNumbers", cleanPhone)
    const snap = await getDoc(phoneRef)
    if (snap.exists() && snap.data()?.uid === uid) {
      await deleteDoc(phoneRef).catch(console.warn)
    }
  },

  async createUserProfile(uid: string, data: Omit<UserProfile, "uid" | "emailVerified" | "collegeVerified" | "createdAt" | "updatedAt">): Promise<void> {
    const userRef = doc(db, "users", uid)
    let cleanPhone = ""
    if (data.phone) {
      const rawClean = data.phone.replace(/\D/g, "").slice(-10)
      if (rawClean && rawClean !== "0000000000") {
        cleanPhone = await this.claimPhoneNumber(rawClean, uid)
      }
    }

    const newProfileData: Record<string, any> = {
      ...data,
      emailVerified: false,
      collegeVerified: false,
      genderVerificationStatus: data.genderVerificationStatus || "pending",
      accountStatus: data.accountStatus || "active",
      notificationPreferences: defaultNotificationPreferences,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    }
    delete newProfileData.phone

    await setDoc(userRef, newProfileData, { merge: true })

    // DPDPA 2023 & WayMate Constitution: Store phone exclusively in private/contact
    if (cleanPhone) {
      const contactRef = doc(db, "users", uid, "private", "contact")
      await setDoc(contactRef, {
        uid,
        phone: cleanPhone,
        updatedAt: serverTimestamp()
      }, { merge: true }).catch(console.warn)
    }

    // DPDPA 2023: Persist private profile fields in protected private subcollection
    const privateRef = doc(db, "users", uid, "private", "profile")
    await setDoc(privateRef, {
      uid,
      phone: cleanPhone,
      email: data.email || auth.currentUser?.email || "",
      homeLocation: (data as any).homeLocation || null,
      updatedAt: serverTimestamp()
    }, { merge: true }).catch(console.warn)

    // Also register email in emails registry if provided
    if (data.email) {
      const emailLower = data.email.trim().toLowerCase()
      await setDoc(doc(db, "emails", emailLower), {
        uid,
        email: emailLower,
        createdAt: serverTimestamp()
      }, { merge: true }).catch(console.warn)
    }

    profileCache.delete(uid) // Invalidate cache
  },

  async getUserProfile(uid: string, forceRefresh = false): Promise<UserProfile | null> {
    if (!uid) return null

    const cached = profileCache.get(uid)
    const now = Date.now()

    if (!forceRefresh && cached && (now - cached.timestamp < CACHE_TTL_MS)) {
      return cached.profile
    }

    const userRef = doc(db, "users", uid)
    const docSnap = await getDoc(userRef)

    if (docSnap.exists()) {
      const rawData = docSnap.data()
      let profile = {
        uid,
        ...rawData,
        genderVerificationStatus: rawData.genderVerificationStatus || "verified",
        accountStatus: rawData.accountStatus || "active"
      } as UserProfile

      // If owner is querying their own profile, ensure private subcollection data is merged
      if (auth.currentUser?.uid === uid) {
        try {
          const contactSnap = await getDoc(doc(db, "users", uid, "private", "contact"))
          if (contactSnap.exists()) {
            profile = {
              ...profile,
              phone: contactSnap.data().phone || profile.phone
            }
          }
        } catch {}
        try {
          const privSnap = await getDoc(doc(db, "users", uid, "private", "profile"))
          if (privSnap.exists()) {
            const privData = privSnap.data()
            profile = {
              ...profile,
              phone: profile.phone || privData.phone,
              homeLocation: privData.homeLocation || profile.homeLocation
            }
          }
        } catch {
          // Ignore private doc fetch failure
        }
      } else {
        delete (profile as any).phone
      }

      profileCache.set(uid, { profile, timestamp: now })
      return profile
    }

    profileCache.set(uid, { profile: null, timestamp: now })
    return null
  },

  /**
   * Fetches multiple user profiles in batches of 30 using documentId() in queries,
   * leveraging the in-memory cache and strictly stripping phone numbers for DPDPA privacy compliance.
   */
  async getUserProfilesBatch(uids: string[]): Promise<Record<string, UserProfile>> {
    const uniqueUids = Array.from(new Set(uids.filter(Boolean)))
    if (uniqueUids.length === 0) return {}

    const result: Record<string, UserProfile> = {}
    const missingUids: string[] = []

    const now = Date.now()
    for (const uid of uniqueUids) {
      const cached = profileCache.get(uid)
      if (cached && now - cached.timestamp < CACHE_TTL_MS) {
        if (cached.profile) result[uid] = cached.profile
      } else {
        missingUids.push(uid)
      }
    }

    if (missingUids.length === 0) return result

    // Firestore 'in' query allows up to 30 items per query
    const CHUNK_SIZE = 30
    const chunks: string[][] = []
    for (let i = 0; i < missingUids.length; i += CHUNK_SIZE) {
      chunks.push(missingUids.slice(i, i + CHUNK_SIZE))
    }

    await Promise.all(
      chunks.map(async (chunk) => {
        try {
          const q = query(collection(db, "users"), where(documentId(), "in", chunk))
          const snap = await getDocs(q)
          snap.docs.forEach((d) => {
            const rawData = d.data()
            const profile: UserProfile = {
              uid: d.id,
              ...rawData,
              genderVerificationStatus: rawData.genderVerificationStatus || "verified",
              accountStatus: rawData.accountStatus || "active"
            } as UserProfile
            // DPDPA 2023 & Security: Never leak phone number in search profiles
            if (auth.currentUser?.uid !== d.id) {
              delete (profile as any).phone
            }
            profileCache.set(d.id, { profile, timestamp: now })
            result[d.id] = profile
          })
        } catch (err) {
          console.error("[userService] Error in getUserProfilesBatch:", err)
        }
      })
    )

    return result
  },

  async updateUserProfile(uid: string, data: Partial<UserProfile>): Promise<void> {
    const userRef = doc(db, "users", uid)
    const updatePayload: Record<string, any> = { ...data }

    // Fetch existing profile to enforce protected fields
    const currentProfile = await this.getUserProfile(uid, true)

    // Non-admin users cannot directly alter protected safety/verification fields
    const isAdminUser = currentProfile?.admin || currentProfile?.role === "admin"
    if (!isAdminUser) {
      delete updatePayload.genderVerificationStatus
      delete updatePayload.accountStatus
      delete updatePayload.collegeVerified
      delete updatePayload.emailVerified
      delete updatePayload.role
      delete updatePayload.admin

      // Gender is immutable once set via onboarding; change must go through requestGenderChange
      if (currentProfile?.gender && updatePayload.gender && updatePayload.gender !== currentProfile.gender) {
        delete updatePayload.gender
      }
    }

    // Ensure email is attached if authenticated user email is present
    if (!("email" in updatePayload) && auth.currentUser?.email) {
      updatePayload.email = auth.currentUser.email
    }

    // If phone number is being changed or updated
    if ("phone" in data) {
      const rawPhone = data.phone || ""
      const cleanPhone = rawPhone.replace(/\D/g, "").slice(-10)
      const prevPhone = currentProfile?.phone

      if (cleanPhone && cleanPhone !== "0000000000") {
        const claimed = await this.claimPhoneNumber(cleanPhone, uid, prevPhone)
        await setDoc(doc(db, "users", uid, "private", "contact"), {
          uid,
          phone: claimed,
          updatedAt: serverTimestamp()
        }, { merge: true }).catch(console.warn)
      } else {
        // Clearing phone number
        if (prevPhone) {
          await this.releasePhoneNumber(prevPhone, uid)
        }
        await setDoc(doc(db, "users", uid, "private", "contact"), {
          uid,
          phone: "",
          updatedAt: serverTimestamp()
        }, { merge: true }).catch(console.warn)
      }
      delete updatePayload.phone
    }

    updatePayload.updatedAt = serverTimestamp()

    await setDoc(userRef, updatePayload, { merge: true })

    // DPDPA 2023: Sync private fields into protected private subcollection
    if ("phone" in data || "homeLocation" in data) {
      const privatePayload: Record<string, any> = { updatedAt: serverTimestamp() }
      if ("phone" in updatePayload) privatePayload.phone = updatePayload.phone
      if ("homeLocation" in updatePayload) privatePayload.homeLocation = updatePayload.homeLocation
      setDoc(doc(db, "users", uid, "private", "profile"), privatePayload, { merge: true }).catch(console.warn)
    }

    // Update in-memory cache directly
    const cached = profileCache.get(uid)
    if (cached?.profile) {
      profileCache.set(uid, {
        profile: { ...cached.profile, ...updatePayload },
        timestamp: Date.now()
      })
    } else {
      profileCache.delete(uid)
    }
  },

  /**
   * Submits a formal gender change request for moderation review instead of direct profile mutation.
   */
  async requestGenderChange(uid: string, targetGender: Gender, reason: string): Promise<{ success: boolean; message: string }> {
    try {
      const userProfile = await this.getUserProfile(uid, true)
      if (!userProfile) return { success: false, message: "User profile not found." }

      const reportsRef = collection(db, "reports")
      await addDoc(reportsRef, {
        reporterId: uid,
        reporterName: userProfile.name,
        reporterEmail: userProfile.email,
        reportedUserId: uid,
        reportedUserName: userProfile.name,
        category: "wrong_profile_information",
        description: `Gender change request to ${targetGender}. Reason: ${reason}`,
        status: "submitted",
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp(),
      })

      // Update local profile genderVerificationStatus to pending
      const userRef = doc(db, "users", uid)
      await setDoc(userRef, {
        genderVerificationStatus: "pending",
        updatedAt: serverTimestamp()
      }, { merge: true })

      profileCache.delete(uid)
      return { success: true, message: "Gender change request submitted for verification." }
    } catch (e: any) {
      return { success: false, message: e.message || "Failed to submit request." }
    }
  },

  /**
   * Checks if user has active upcoming rides as host or accepted passenger.
   */
  async checkActiveRidesForUser(uid: string): Promise<{ hasActiveRides: boolean; message?: string }> {
    try {
      // Check rides owned by user
      const qHostRides = query(
        collection(db, "rides"),
        where("ownerId", "==", uid),
        where("status", "in", ["active", "full"])
      )
      const hostSnap = await getDocs(qHostRides)
      if (!hostSnap.empty) {
        return {
          hasActiveRides: true,
          message: "You have active rides scheduled as a host. Please cancel your upcoming rides first before deleting your account."
        }
      }

      // Check accepted requests by user
      const qPassenger = query(
        collection(db, "rideRequests"),
        where("requesterId", "==", uid),
        where("status", "==", "accepted")
      )
      const passengerSnap = await getDocs(qPassenger)
      if (!passengerSnap.empty) {
        return {
          hasActiveRides: true,
          message: "You have accepted requests on upcoming rides. Please cancel your seat requests first before deleting your account."
        }
      }

      return { hasActiveRides: false }
    } catch (e) {
      console.error("Error checking active rides:", e)
      return { hasActiveRides: false }
    }
  },

  /**
   * Deletes user account safely (deleting user document, notifications, and auth credentials,
   * while preserving past ride history for the other party with anonymized 'Deleted User' name).
   */
  async deleteUserAccount(uid: string): Promise<{ success: boolean; message: string }> {
    // 1. Check for active rides
    const activeCheck = await this.checkActiveRidesForUser(uid)
    if (activeCheck.hasActiveRides) {
      return { success: false, message: activeCheck.message || "Cannot delete account with active rides." }
    }

    // 2. Direct Client-side Deletion Procedure
    try {
      // Delete Notifications
      try {
        const qNotifs = query(collection(db, "notifications"), where("userId", "==", uid))
        const notifsSnap = await getDocs(qNotifs)
        if (!notifsSnap.empty) {
          const batch = writeBatch(db)
          notifsSnap.docs.forEach(d => batch.delete(d.ref))
          await batch.commit()
        }
      } catch (e) {
        console.warn("Could not delete notifications during account removal:", e)
      }

      // Delete Phone & Email Reservations
      try {
        const userSnap = await getDoc(doc(db, "users", uid))
        if (userSnap.exists()) {
          const udata = userSnap.data()
          if (udata.phone) {
            const cleanPhone = udata.phone.replace(/\D/g, "").slice(-10)
            if (cleanPhone) {
              await deleteDoc(doc(db, "phoneNumbers", cleanPhone)).catch(console.warn)
            }
          }
          if (udata.email) {
            await deleteDoc(doc(db, "emails", udata.email.trim().toLowerCase())).catch(console.warn)
          }
        }
      } catch (e) {
        console.warn("Could not clean up phone/email reservations during account removal:", e)
      }

      // Delete User Profile Document & Private Subcollection
      try {
        await deleteDoc(doc(db, "users", uid, "private", "profile")).catch(() => {})
        await deleteDoc(doc(db, "users", uid))
      } catch (e) {
        console.warn("Could not delete user doc directly:", e)
      }

      // Delete Auth Record
      if (auth.currentUser) {
        try {
          await deleteUser(auth.currentUser)
        } catch (authErr: any) {
          if (authErr.code === "auth/requires-recent-login") {
            return {
              success: false,
              message: "For security reasons, please log out and sign in again before deleting your account."
            }
          }
          console.error("Auth record deletion error:", authErr)
        }
      }

      return { success: true, message: "Account deleted successfully." }
    } catch (e: any) {
      console.error("Failed client account deletion:", e)
      return { success: false, message: e.message || "Failed to delete account." }
    }
  },

  /**
   * Securely fetches phone contact details ONLY if an accepted ride relationship exists
   * between currentUserId and targetUserId for the specified rideId (or if checking own profile).
   * Reads from the secure rideContacts document protected by Firestore Security Rules.
   */
  async getContactInfo(targetUserId: string, currentUserId: string, rideId: string): Promise<{ phone: string | null; name: string } | null> {
    if (!targetUserId || !currentUserId || !rideId) return null

    if (targetUserId === currentUserId) {
      const priv = await getDoc(doc(db, "users", currentUserId, "private", "contact")).catch(() => null)
      const ownPhone = priv?.exists() ? priv.data()?.phone : null
      const profile = await this.getUserProfile(currentUserId)
      return { phone: ownPhone || null, name: profile?.name || "You" }
    }

    try {
      const targetProfile = await this.getUserProfile(targetUserId)

      // Privacy rule (DPDPA 2023 & Campus Safety):
      // Contact details are strictly active-ride only for live trip coordination.
      // Once a ride has completed, cancelled, or expired, contact details are sealed.
      const rideRef = doc(db, "rides", rideId)
      const rideSnap = await getDoc(rideRef).catch(() => null)
      const rideData = rideSnap?.exists() ? rideSnap.data() : null

      if (!rideData || rideData.status === "completed" || rideData.status === "cancelled") {
        return { phone: null, name: targetProfile?.name || "Student" }
      }
      if (isRideExpired(rideData.date, rideData.departureTime || (rideData as any).time, rideData.status)) {
        return { phone: null, name: targetProfile?.name || "Student" }
      }

      // Query rideRequests connecting the two users for this ride where status == 'accepted' only
      const qReq = query(
        collection(db, "rideRequests"),
        where("rideId", "==", rideId),
        where("status", "==", "accepted")
      )
      const reqSnap = await getDocs(qReq).catch(() => ({ docs: [] } as any))
      const matchedReq = reqSnap.docs.find((d: any) => {
        const data = d.data()
        return (data.requesterId === currentUserId && data.rideOwnerId === targetUserId) ||
               (data.requesterId === targetUserId && data.rideOwnerId === currentUserId)
      })

      if (!matchedReq) {
        return { phone: null, name: targetProfile?.name || "Student" }
      }

      // Read from secure rideContacts/{requestId}
      const contactSnap = await getDoc(doc(db, "rideContacts", matchedReq.id)).catch(() => null)
      if (!contactSnap?.exists()) {
        return { phone: null, name: targetProfile?.name || "Student" }
      }

      const contactData = contactSnap.data()
      if (contactData.status !== "accepted") {
        return { phone: null, name: targetProfile?.name || "Student" }
      }

      let phone = currentUserId === contactData.hostId ? contactData.passengerPhone : contactData.hostPhone

      // Auto-fallback if rideContacts has empty phone for target user
      if (!phone) {
        const priv = await getDoc(doc(db, "users", targetUserId, "private", "contact")).catch(() => null)
        phone = priv?.exists() ? priv.data()?.phone : null
        if (!phone) {
          const uDoc = await getDoc(doc(db, "users", targetUserId)).catch(() => null)
          phone = uDoc?.exists() ? (uDoc.data()?.phone || (uDoc.data() as any)?.phoneNumber) : null
        }
        if (!phone && targetProfile?.phone) {
          phone = targetProfile.phone
        }
        if (phone && matchedReq?.id) {
          const updateField = currentUserId === contactData.hostId ? "passengerPhone" : "hostPhone"
          updateDoc(doc(db, "rideContacts", matchedReq.id), {
            [updateField]: phone,
            updatedAt: serverTimestamp()
          }).catch(() => {})
        }
      }

      return { phone: phone || null, name: targetProfile?.name || "Student" }
    } catch (e) {
      console.warn("Failed to fetch contact info:", e)
    }

    return null
  },

  /**
   * Securely fetches phone contact details for a specific rideRequest ID
   * ONLY if its status is 'accepted' and currentUserId is a participant (requester or host).
   */
  async getContactInfoForRequest(requestId: string, currentUserId: string): Promise<{ phone: string | null; name: string } | null> {
    if (!requestId || !currentUserId) return null
    try {
      const contactSnap = await getDoc(doc(db, "rideContacts", requestId))
      if (!contactSnap.exists()) return null
      const contactData = contactSnap.data()
      if (contactData.status !== "accepted") return null

      if (currentUserId === contactData.hostId) {
        return { phone: contactData.passengerPhone || null, name: contactData.passengerName || "Passenger" }
      } else if (currentUserId === contactData.passengerId) {
        return { phone: contactData.hostPhone || null, name: contactData.hostName || "Host" }
      }
      return null
    } catch (e) {
      console.warn("Error in getContactInfoForRequest:", e)
      return null
    }
  }
}
