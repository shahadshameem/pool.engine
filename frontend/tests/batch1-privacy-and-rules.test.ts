import { describe, it, expect, beforeAll, afterAll } from "vitest"
import {
  collection,
  doc,
  getDoc,
  setDoc,
  deleteDoc,
  updateDoc
} from "firebase/firestore"
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword
} from "firebase/auth"
import { auth, db } from "../src/config/firebase"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import { notificationService } from "../src/services/notification/notificationService"

describe("BATCH 1: Privacy and Rules Hardening (NEW-4, NEW-7, NEW-8)", () => {
  const ts = Date.now()
  const password = "Password123!@"
  const hostEmail = `batch1.host.${ts}@cet.ac.in`
  const riderEmail = `batch1.rider.${ts}@cet.ac.in`
  const strangerEmail = `batch1.stranger.${ts}@cet.ac.in`

  let hostUid = ""
  let riderUid = ""
  let strangerUid = ""

  const hostPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`
  const riderPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`
  const strangerPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`

  const cleanupRides: string[] = []
  const cleanupRequests: string[] = []
  const cleanupUsers: string[] = []
  const cleanupContacts: string[] = []

  beforeAll(async () => {
    // 1. Create Host User
    const hCred = await createUserWithEmailAndPassword(auth, hostEmail, password)
    hostUid = hCred.user.uid
    cleanupUsers.push(hostUid)
    await userService.createUserProfile(hostUid, {
      name: "Batch1 Host",
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "4th Year",
      phone: hostPhone
    })

    // 2. Create Rider User
    const rCred = await createUserWithEmailAndPassword(auth, riderEmail, password)
    riderUid = rCred.user.uid
    cleanupUsers.push(riderUid)
    await userService.createUserProfile(riderUid, {
      name: "Batch1 Rider",
      gender: "male",
      college: "CET",
      department: "CSE",
      year: "2nd Year",
      phone: riderPhone
    })

    // 3. Create Stranger User
    const sCred = await createUserWithEmailAndPassword(auth, strangerEmail, password)
    strangerUid = sCred.user.uid
    cleanupUsers.push(strangerUid)
    await userService.createUserProfile(strangerUid, {
      name: "Batch1 Stranger",
      gender: "male",
      college: "CET",
      department: "ME",
      year: "1st Year",
      phone: strangerPhone
    })
  }, 30000)

  afterAll(async () => {
    for (const id of cleanupContacts) {
      await deleteDoc(doc(db, "rideContacts", id)).catch(() => {})
    }
    for (const id of cleanupRequests) {
      await deleteDoc(doc(db, "rideRequests", id)).catch(() => {})
    }
    for (const id of cleanupRides) {
      await deleteDoc(doc(db, "rides", id)).catch(() => {})
    }
    for (const id of cleanupUsers) {
      await deleteDoc(doc(db, "users", id, "private", "contact")).catch(() => {})
      await deleteDoc(doc(db, "users", id)).catch(() => {})
    }
  })

  // -------------------------------------------------------------
  // Item 1: Phone numbers in private/contact, NOT in root users/{uid}
  // -------------------------------------------------------------
  it("B1-1: Root users/{uid} doc must NOT expose phone, and private/contact must store it", async () => {
    // As stranger, read host user doc
    await signInWithEmailAndPassword(auth, strangerEmail, password)
    const hostDocSnap = await getDoc(doc(db, "users", hostUid))
    expect(hostDocSnap.exists()).toBe(true)
    const hostData = hostDocSnap.data()

    // SKEPTICAL ASSERTION: phone must be undefined on the root users doc!
    expect(hostData?.phone).toBeUndefined()

    // Stranger attempts to read host's private/contact document -> MUST BE PERMISSION DENIED
    let strangerReadForbidden = false
    try {
      await getDoc(doc(db, "users", hostUid, "private", "contact"))
    } catch (err: any) {
      strangerReadForbidden = true
    }
    expect(strangerReadForbidden).toBe(true)

    // Owner reads own private/contact document -> MUST SUCCEED
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const ownContactSnap = await getDoc(doc(db, "users", hostUid, "private", "contact"))
    expect(ownContactSnap.exists()).toBe(true)
    expect(ownContactSnap.data()?.phone).toBe(hostPhone)
  })

  // -------------------------------------------------------------
  // Item 2: Rides collection must NOT store driverPhone
  // -------------------------------------------------------------
  it("B1-2: rides/{rideId} must NOT contain driverPhone", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const rideId = await rideService.createRide(hostUid, {
      from: "College of Engineering Trivandrum",
      to: "Thampanoor Railway Station",
      fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
      toLocation: { name: "Thampanoor", address: "Thampanoor", latitude: 8.4875, longitude: 76.9528 },
      date: "2026-10-25",
      departureTime: "10:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(rideId)

    // Stranger reads the ride document
    await signInWithEmailAndPassword(auth, strangerEmail, password)
    const rideSnap = await getDoc(doc(db, "rides", rideId))
    expect(rideSnap.exists()).toBe(true)
    const rideData = rideSnap.data()

    // SKEPTICAL ASSERTION: driverPhone must NOT exist on public ride doc
    expect(rideData?.driverPhone).toBeUndefined()
  })

  // -------------------------------------------------------------
  // Item 3: Contact access ONLY for accepted host/rider pair of same ride
  // -------------------------------------------------------------
  it("B1-3: Contact exchange: no phone before accept; visible ONLY to accepted pair", async () => {
    // 1. Host creates a ride
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET Gate",
      to: "Central Station",
      fromLocation: { name: "CET Gate", address: "CET Gate", latitude: 8.5456, longitude: 76.9056 },
      toLocation: { name: "Central", address: "Central", latitude: 8.4875, longitude: 76.9528 },
      date: "2026-10-25",
      departureTime: "11:00 AM",
      totalSeats: 2,
      availableSeats: 2
    })
    cleanupRides.push(rideId)

    // 2. Rider requests the ride -> creates rideRequest & pending rideContacts
    await signInWithEmailAndPassword(auth, riderEmail, password)
    const rideDocSnap = await getDoc(doc(db, "rides", rideId))
    const fullRide = { id: rideId, ...rideDocSnap.data() } as any
    const reqRes = await rideRequestService.createRideRequest(
      fullRide,
      riderUid,
      1
    )
    expect(reqRes.success).toBe(true)
    const requestId = reqRes.requestId!
    cleanupRequests.push(requestId)
    cleanupContacts.push(requestId)

    // 3. BEFORE ACCEPTANCE:
    // Host checks contact info -> MUST BE NULL
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const hostCheckBeforeAccept = await userService.getContactInfo(riderUid, hostUid, rideId)
    expect(hostCheckBeforeAccept?.phone).toBeNull()

    // Rider checks host contact info before accept -> MUST BE NULL
    await signInWithEmailAndPassword(auth, riderEmail, password)
    const riderCheckBeforeAccept = await userService.getContactInfo(hostUid, riderUid, rideId)
    expect(riderCheckBeforeAccept?.phone).toBeNull()

    // Stranger checks contact info -> MUST BE NULL
    await signInWithEmailAndPassword(auth, strangerEmail, password)
    const strangerCheckBeforeAccept = await userService.getContactInfo(hostUid, strangerUid, rideId)
    expect(strangerCheckBeforeAccept?.phone).toBeNull()

    // Stranger tries direct Firestore read on rideContacts/{requestId} -> PERMISSION DENIED
    let strangerDirectReadForbidden = false
    try {
      await getDoc(doc(db, "rideContacts", requestId))
    } catch {
      strangerDirectReadForbidden = true
    }
    expect(strangerDirectReadForbidden).toBe(true)

    // 4. HOST ACCEPTS THE RIDE REQUEST
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const acceptRes = await rideRequestService.acceptRideRequest(requestId, hostUid)
    expect(acceptRes.success).toBe(true)

    // 5. AFTER ACCEPTANCE:
    // Host checks rider contact info -> MUST BE RIDER'S PHONE
    const hostContactAfterAccept = await userService.getContactInfo(riderUid, hostUid, rideId)
    expect(hostContactAfterAccept?.phone).toBe(riderPhone)

    // Rider checks host contact info -> MUST BE HOST'S PHONE
    await signInWithEmailAndPassword(auth, riderEmail, password)
    const riderContactAfterAccept = await userService.getContactInfo(hostUid, riderUid, rideId)
    expect(riderContactAfterAccept?.phone).toBe(hostPhone)

    // Stranger checks host or rider contact -> MUST STILL BE NULL
    await signInWithEmailAndPassword(auth, strangerEmail, password)
    const strangerContactAfterAccept = await userService.getContactInfo(hostUid, strangerUid, rideId)
    expect(strangerContactAfterAccept?.phone).toBeNull()
  }, 35000)

  // -------------------------------------------------------------
  // Item 4: Rules evaluation stability (NEW-7, NEW-8)
  // -------------------------------------------------------------
  it("B1-4: Notifications create without actorId must NOT throw rule evaluation error", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    // Create notification where actorId is omitted
    const created = await notificationService.createNotification({
      userId: hostUid,
      type: "ride_request",
      title: "Test Notification",
      message: "Testing rules without actorId",
      rideId: "test-ride"
    })
    expect(created).toBe(true)
  })

  // -------------------------------------------------------------
  // Item 5: Privilege escalation prevention (users collection)
  // -------------------------------------------------------------
  it("B1-5: Normal user cannot create or update user doc with role='admin' or admin=true", async () => {
    await signInWithEmailAndPassword(auth, strangerEmail, password)

    // Try to update role to 'admin'
    let roleEscalationBlocked = false
    try {
      await updateDoc(doc(db, "users", strangerUid), {
        role: "admin"
      })
    } catch {
      roleEscalationBlocked = true
    }
    expect(roleEscalationBlocked).toBe(true)

    // Try to update admin to true
    let adminEscalationBlocked = false
    try {
      await updateDoc(doc(db, "users", strangerUid), {
        admin: true
      })
    } catch {
      adminEscalationBlocked = true
    }
    expect(adminEscalationBlocked).toBe(true)

    // Try to update collegeVerified to true
    let verifiedEscalationBlocked = false
    try {
      await updateDoc(doc(db, "users", strangerUid), {
        collegeVerified: true
      })
    } catch {
      verifiedEscalationBlocked = true
    }
    expect(verifiedEscalationBlocked).toBe(true)

    // Try to change gender from male to female
    let genderChangeBlocked = false
    try {
      await updateDoc(doc(db, "users", strangerUid), {
        gender: "female"
      })
    } catch {
      genderChangeBlocked = true
    }
    expect(genderChangeBlocked).toBe(true)
  })

  // -------------------------------------------------------------
  // Item 6: Hardcoded admin email removal
  // -------------------------------------------------------------
  it("B1-6: Hardcoded test admin email without custom claim is NOT recognized as admin", async () => {
    const fakeAdminEmail = `admin.testrunner@waymate.internal`
    let fakeAdminUid = ""
    try {
      const cred = await createUserWithEmailAndPassword(auth, fakeAdminEmail, password)
      fakeAdminUid = cred.user.uid
    } catch (e: any) {
      if (e.code === "auth/email-already-in-use") {
        const cred = await signInWithEmailAndPassword(auth, fakeAdminEmail, password)
        fakeAdminUid = cred.user.uid
      }
    }

    // Try to write to admin-only collection `waymate_places`
    let adminWriteForbidden = false
    try {
      await setDoc(doc(db, "waymate_places", "unauthorized-place"), {
        name: "Hacked Place",
        latitude: 8.5,
        longitude: 76.9
      })
    } catch {
      adminWriteForbidden = true
    }
    expect(adminWriteForbidden).toBe(true)

    if (fakeAdminUid) {
      await deleteDoc(doc(db, "users", fakeAdminUid)).catch(() => {})
    }
  })
})
