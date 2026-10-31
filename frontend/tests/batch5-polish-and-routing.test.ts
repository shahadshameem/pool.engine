import { describe, it, expect, beforeAll, afterAll } from "vitest"
import {
  collection,
  doc,
  getDoc,
  setDoc,
  deleteDoc,
  getDocs,
  query,
  where
} from "firebase/firestore"
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword
} from "firebase/auth"
import { auth, db } from "../src/config/firebase"
import { getSafeRedirectPath } from "../src/utils/redirectUrl"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import fs from "fs"
import path from "path"

describe("BATCH 5: Polish & Deep Linking (NEW-9, NEW-10, NEW-11)", () => {
  const ts = Date.now()
  const password = "Password123!@"

  // Host and 2 users for batch loading & index tests
  const hostEmail = `b5.host.${ts}@cet.ac.in`
  let hostUid = ""
  const hostPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`

  const user1Email = `b5.user1.${ts}@cet.ac.in`
  let user1Uid = ""
  const user1Phone = `9846${Math.floor(100000 + Math.random() * 900000)}`

  const user2Email = `b5.user2.${ts}@cet.ac.in`
  let user2Uid = ""
  const user2Phone = `9845${Math.floor(100000 + Math.random() * 900000)}`

  const cleanupRides: string[] = []
  const cleanupUsers: string[] = []
  const cleanupRequests: string[] = []

  beforeAll(async () => {
    // 1. Host
    const hCred = await createUserWithEmailAndPassword(auth, hostEmail, password)
    hostUid = hCred.user.uid
    cleanupUsers.push(hostUid)
    await userService.createUserProfile(hostUid, {
      name: "B5 Host",
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "4th Year",
      phone: hostPhone
    })

    // 2. User 1
    const u1Cred = await createUserWithEmailAndPassword(auth, user1Email, password)
    user1Uid = u1Cred.user.uid
    cleanupUsers.push(user1Uid)
    await userService.createUserProfile(user1Uid, {
      name: "B5 User 1",
      gender: "male",
      college: "CET",
      department: "CSE",
      year: "3rd Year",
      phone: user1Phone
    })

    // 3. User 2
    const u2Cred = await createUserWithEmailAndPassword(auth, user2Email, password)
    user2Uid = u2Cred.user.uid
    cleanupUsers.push(user2Uid)
    await userService.createUserProfile(user2Uid, {
      name: "B5 User 2",
      gender: "female",
      college: "CET",
      department: "EEE",
      year: "2nd Year",
      phone: user2Phone
    })
  }, 35000)

  afterAll(async () => {
    for (const rId of cleanupRequests) {
      await deleteDoc(doc(db, "rideRequests", rId)).catch(() => {})
      await deleteDoc(doc(db, "rideContacts", rId)).catch(() => {})
    }
    for (const id of cleanupRides) {
      await deleteDoc(doc(db, "rides", id)).catch(() => {})
    }
    for (const id of cleanupUsers) {
      await deleteDoc(doc(db, "users", id, "private", "contact")).catch(() => {})
      await deleteDoc(doc(db, "users", id)).catch(() => {})
    }
  })

  // --------------------------------------------------------------------------
  // 1. Deep Link Preservation & Open-Redirect Defense (NEW-9)
  // --------------------------------------------------------------------------
  describe("1. Deep Link Preservation & Open Redirect Defense (NEW-9)", () => {
    it("B5-1A: Allows valid same-origin relative redirect paths", () => {
      expect(getSafeRedirectPath("/ride/abc123")).toBe("/ride/abc123")
      expect(getSafeRedirectPath("/rides")).toBe("/rides")
      expect(getSafeRedirectPath("/home?tab=requests")).toBe("/home?tab=requests")
      expect(getSafeRedirectPath("/offer-ride")).toBe("/offer-ride")
      expect(getSafeRedirectPath("/find?from=CET&to=Palayam")).toBe("/find?from=CET&to=Palayam")
    })

    it("B5-1B: Blocks absolute URLs and external domains (Open Redirect Defense)", () => {
      expect(getSafeRedirectPath("https://evil.com")).toBe("/home")
      expect(getSafeRedirectPath("http://attacker.org/phish")).toBe("/home")
      expect(getSafeRedirectPath("https://waymate-fake.com/ride/123")).toBe("/home")
    })

    it("B5-1C: Blocks protocol-relative URLs (//attacker.com bypass)", () => {
      expect(getSafeRedirectPath("//evil.com")).toBe("/home")
      expect(getSafeRedirectPath("//evil.com/ride/123")).toBe("/home")
      expect(getSafeRedirectPath("///evil.com")).toBe("/home")
    })

    it("B5-1D: Blocks backslash bypasses (Windows path confusion)", () => {
      expect(getSafeRedirectPath("/\\evil.com")).toBe("/home")
      expect(getSafeRedirectPath("\\evil.com")).toBe("/home")
      expect(getSafeRedirectPath("/path\\sub")).toBe("/home")
    })

    it("B5-1E: Blocks JavaScript and Data URI schemes", () => {
      expect(getSafeRedirectPath("javascript:alert(1)")).toBe("/home")
      expect(getSafeRedirectPath("data:text/html,<script>alert(1)</script>")).toBe("/home")
      expect(getSafeRedirectPath("vbscript:msgbox(1)")).toBe("/home")
    })

    it("B5-1F: Handles empty, null, undefined and custom fallback cleanly", () => {
      expect(getSafeRedirectPath(null)).toBe("/home")
      expect(getSafeRedirectPath(undefined)).toBe("/home")
      expect(getSafeRedirectPath("")).toBe("/home")
      expect(getSafeRedirectPath("   ")).toBe("/home")
      expect(getSafeRedirectPath("https://evil.com", "/welcome")).toBe("/welcome")
      expect(getSafeRedirectPath(null, "/login")).toBe("/login")
    })
  })

  // --------------------------------------------------------------------------
  // 2. Batch Host Profile Loading & Search Privacy (NEW-10)
  // --------------------------------------------------------------------------
  describe("2. Batch Host Profile Loading (NEW-10)", () => {
    it("B5-2A: Loads host profiles in batch without phone numbers in search results", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      // Query profiles for user1 and user2
      const profiles = await userService.getUserProfilesBatch([user1Uid, user2Uid])
      expect(profiles[user1Uid]).toBeDefined()
      expect(profiles[user2Uid]).toBeDefined()

      expect(profiles[user1Uid].name).toBe("B5 User 1")
      expect(profiles[user1Uid].college).toBe("CET")
      expect(profiles[user1Uid].department).toBe("CSE")

      expect(profiles[user2Uid].name).toBe("B5 User 2")
      expect(profiles[user2Uid].college).toBe("CET")
      expect(profiles[user2Uid].department).toBe("EEE")

      // DPDPA 2023 & Privacy assertion:
      // Search profile results must NOT contain phone numbers!
      expect(profiles[user1Uid].phone).toBeUndefined()
      expect(profiles[user2Uid].phone).toBeUndefined()
    })

    it("B5-2B: Second call uses cache and returns profiles seamlessly", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const cachedProfiles = await userService.getUserProfilesBatch([user1Uid, user2Uid])
      expect(cachedProfiles[user1Uid]).toBeDefined()
      expect(cachedProfiles[user2Uid]).toBeDefined()
      expect(cachedProfiles[user1Uid].name).toBe("B5 User 1")
    })

    it("B5-2C: Handles empty list and deduplicates UIDs safely", async () => {
      const empty = await userService.getUserProfilesBatch([])
      expect(Object.keys(empty).length).toBe(0)

      const dedup = await userService.getUserProfilesBatch([user1Uid, user1Uid, user1Uid])
      expect(Object.keys(dedup).length).toBe(1)
      expect(dedup[user1Uid].name).toBe("B5 User 1")
    })
  })

  // --------------------------------------------------------------------------
  // 3. Composite Index Configuration & Query Execution (NEW-11)
  // --------------------------------------------------------------------------
  describe("3. Composite Indexes Configuration (NEW-11)", () => {
    it("B5-3A: firestore.indexes.json defines required composite index for rideRequests", () => {
      const indexPath = path.resolve(__dirname, "../firestore.indexes.json")
      expect(fs.existsSync(indexPath)).toBe(true)

      const indexContent = JSON.parse(fs.readFileSync(indexPath, "utf8"))
      const indexes = indexContent.indexes || []

      // Check for index with rideId, rideOwnerId, status
      const hasTripleIndex = indexes.some((idx: any) => {
        if (idx.collectionGroup !== "rideRequests") return false
        const fields = idx.fields.map((f: any) => f.fieldPath)
        return fields.includes("rideId") && fields.includes("rideOwnerId") && fields.includes("status")
      })
      expect(hasTripleIndex).toBe(true)

      // Check for index with rideId, status
      const hasDoubleIndex = indexes.some((idx: any) => {
        if (idx.collectionGroup !== "rideRequests") return false
        const fields = idx.fields.map((f: any) => f.fieldPath)
        return fields.includes("rideId") && fields.includes("status")
      })
      expect(hasDoubleIndex).toBe(true)
    })

    it("B5-3B: cancelRide query executes without Firestore composite index errors", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Kollam Beach",
        date: tomorrow,
        departureTime: "08:00 AM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car"
      })
      cleanupRides.push(rideId)

      // User 1 requests a seat
      await signInWithEmailAndPassword(auth, user1Email, password)
      const req = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Kollam", date: tomorrow, departureTime: "08:00 AM" },
        user1Uid,
        1
      )
      expect(req.success).toBe(true)
      if (req.requestId) cleanupRequests.push(req.requestId)

      // Host cancels ride — which executes the composite query
      await signInWithEmailAndPassword(auth, hostEmail, password)
      const cancelRes = await rideService.cancelRide(rideId, hostUid, "Weather warning")
      expect(cancelRes.success).toBe(true)

      const updatedRide = await getDoc(doc(db, "rides", rideId))
      expect(updatedRide.data()?.status).toBe("cancelled")
    })
  })
})
