import { describe, it, expect, beforeAll, afterAll } from "vitest"
import {
  collection,
  doc,
  getDoc,
  setDoc,
  deleteDoc,
  getDocs,
  query,
  where,
  serverTimestamp,
  Timestamp
} from "firebase/firestore"
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword
} from "firebase/auth"
import { auth, db } from "../src/config/firebase"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"

describe("BATCH 4: Requests, Cancellations, Lifecycle and Gender Policy", () => {
  const ts = Date.now()
  const password = "Password123!@"

  // 1. Male Host
  const hostEmail = `b4.host.${ts}@cet.ac.in`
  let hostUid = ""
  const hostPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`

  // 2. Male Rider
  const maleRiderEmail = `b4.malerider.${ts}@cet.ac.in`
  let maleRiderUid = ""
  const maleRiderPhone = `9846${Math.floor(100000 + Math.random() * 900000)}`

  // 3. Female Rider
  const femaleRiderEmail = `b4.femalerider.${ts}@cet.ac.in`
  let femaleRiderUid = ""
  const femaleRiderPhone = `9845${Math.floor(100000 + Math.random() * 900000)}`

  // 4. Second Male Rider (for concurrency / capacity tests)
  const maleRider2Email = `b4.malerider2.${ts}@cet.ac.in`
  let maleRider2Uid = ""
  const maleRider2Phone = `9844${Math.floor(100000 + Math.random() * 900000)}`

  const cleanupRides: string[] = []
  const cleanupUsers: string[] = []
  const cleanupRequests: string[] = []

  beforeAll(async () => {
    // Create Male Host
    const hCred = await createUserWithEmailAndPassword(auth, hostEmail, password)
    hostUid = hCred.user.uid
    cleanupUsers.push(hostUid)
    await userService.createUserProfile(hostUid, {
      name: "B4 Host",
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "4th Year",
      phone: hostPhone
    })

    // Create Male Rider 1
    const mCred = await createUserWithEmailAndPassword(auth, maleRiderEmail, password)
    maleRiderUid = mCred.user.uid
    cleanupUsers.push(maleRiderUid)
    await userService.createUserProfile(maleRiderUid, {
      name: "B4 Male Rider 1",
      gender: "male",
      college: "CET",
      department: "CSE",
      year: "3rd Year",
      phone: maleRiderPhone
    })

    // Create Female Rider
    const fCred = await createUserWithEmailAndPassword(auth, femaleRiderEmail, password)
    femaleRiderUid = fCred.user.uid
    cleanupUsers.push(femaleRiderUid)
    await userService.createUserProfile(femaleRiderUid, {
      name: "B4 Female Rider",
      gender: "female",
      college: "CET",
      department: "EEE",
      year: "2nd Year",
      phone: femaleRiderPhone
    })

    // Create Male Rider 2
    const m2Cred = await createUserWithEmailAndPassword(auth, maleRider2Email, password)
    maleRider2Uid = m2Cred.user.uid
    cleanupUsers.push(maleRider2Uid)
    await userService.createUserProfile(maleRider2Uid, {
      name: "B4 Male Rider 2",
      gender: "male",
      college: "CET",
      department: "Civil",
      year: "1st Year",
      phone: maleRider2Phone
    })
  }, 40000)

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
  // 1. Expired Ride Request Rejection (NEW-6)
  // --------------------------------------------------------------------------
  describe("1. Expired Ride Requests Rejection (NEW-6)", () => {
    it("B4-1A: createRideRequest rejects seat requests on expired rides", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      // Direct write to seed a ride whose date/time is 1 hour ago (without future timestamp so creation succeeds)
      const expiredRideId = `test-expired-ride-${ts}`
      const pastDate = new Date(Date.now() - 3600 * 1000)
      await setDoc(doc(db, "rides", expiredRideId), {
        ownerId: hostUid,
        driverName: "B4 Host",
        from: "CET Engineering College, Trivandrum",
        to: "Trivandrum Central Railway Station",
        date: pastDate.toISOString().split("T")[0],
        departureTime: "08:00 AM",
        genderPolicy: "any",
        seats: 2,
        totalSeats: 2,
        availableSeats: 2,
        vehicleType: "car",
        status: "active",
        createdAt: serverTimestamp()
      })
      cleanupRides.push(expiredRideId)

      // Rider attempts to request a seat
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const res = await rideRequestService.createRideRequest(
        {
          id: expiredRideId,
          ownerId: hostUid,
          status: "active",
          availableSeats: 2,
          from: "CET",
          to: "Station",
          date: pastDate.toISOString().split("T")[0],
          departureTime: "08:00 AM"
        },
        maleRiderUid,
        1
      )

      expect(res.success).toBe(false)
      expect(res.code).toBe("RIDE_EXPIRED")
    })

    it("B4-1B: Direct Firestore write to request an expired ride is blocked by Security Rules", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const expiredRideId = `test-expired-rules-${ts}`
      await setDoc(doc(db, "rides", expiredRideId), {
        ownerId: hostUid,
        driverName: "B4 Host",
        from: "CET Engineering College, Trivandrum",
        to: "Trivandrum Central Railway Station",
        date: "2026-10-20",
        departureTime: "08:00 AM",
        genderPolicy: "any",
        seats: 2,
        totalSeats: 2,
        availableSeats: 2,
        vehicleType: "car",
        status: "expired",
        createdAt: serverTimestamp()
      })
      cleanupRides.push(expiredRideId)

      // Male Rider attempts direct Firestore addDoc / setDoc bypassing service
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      let blocked = false
      try {
        await setDoc(doc(db, "rideRequests", `req-expired-hack-${Date.now()}`), {
          rideId: expiredRideId,
          requesterId: maleRiderUid,
          rideOwnerId: hostUid,
          seatsRequested: 1,
          status: "pending",
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        })
      } catch (err: any) {
        blocked = err?.code === "permission-denied" || err?.message?.includes("permission")
      }

      expect(blocked).toBe(true)
    })
  })

  // --------------------------------------------------------------------------
  // 2. Duplicate, Self, Full & Cancelled Request Rejections
  // --------------------------------------------------------------------------
  describe("2. Request State & Eligibility Enforcement", () => {
    it("B4-2A: Rejects duplicate active request for the same ride", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Kollam Beach",
        date: tomorrow,
        departureTime: "10:00 AM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car"
      })
      cleanupRides.push(rideId)

      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const req1 = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Kollam", date: tomorrow, departureTime: "10:00 AM" },
        maleRiderUid,
        1
      )
      expect(req1.success).toBe(true)
      if (req1.requestId) cleanupRequests.push(req1.requestId)

      // Attempt second request
      const req2 = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Kollam", date: tomorrow, departureTime: "10:00 AM" },
        maleRiderUid,
        1
      )
      expect(req2.success).toBe(false)
      expect(req2.code).toBe("DUPLICATE_REQUEST")
    })

    it("B4-2B: Rejects user requesting their own ride (in code and rules)", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Varkala Cliff",
        date: tomorrow,
        departureTime: "11:00 AM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car"
      })
      cleanupRides.push(rideId)

      // Host tries to request their own ride via service
      const req = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Varkala", date: tomorrow, departureTime: "11:00 AM" },
        hostUid,
        1
      )
      expect(req.success).toBe(false)
      expect(req.code).toBe("SELF_REQUEST")

      // Direct Firestore write attempt
      let blocked = false
      try {
        await setDoc(doc(db, "rideRequests", `req-self-hack-${Date.now()}`), {
          rideId,
          requesterId: hostUid,
          rideOwnerId: hostUid,
          seatsRequested: 1,
          status: "pending",
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        })
      } catch (err: any) {
        blocked = err?.code === "permission-denied" || err?.message?.includes("permission")
      }
      expect(blocked).toBe(true)
    })

    it("B4-2C: Rejects requests on cancelled rides (in code and rules)", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Technopark Phase 1",
        date: tomorrow,
        departureTime: "02:00 PM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car"
      })
      cleanupRides.push(rideId)

      // Host cancels the ride
      await rideService.cancelRide(rideId, hostUid, "Trip cancelled due to rain")

      // Male Rider attempts to request
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const res = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "cancelled", availableSeats: 2, from: "CET", to: "Technopark", date: tomorrow, departureTime: "02:00 PM" },
        maleRiderUid,
        1
      )
      expect(res.success).toBe(false)
      expect(res.code).toBe("RIDE_NOT_ACTIVE")

      // Direct write attempt to cancelled ride blocked by rules
      let blocked = false
      try {
        await setDoc(doc(db, "rideRequests", `req-cancelled-hack-${Date.now()}`), {
          rideId,
          requesterId: maleRiderUid,
          rideOwnerId: hostUid,
          seatsRequested: 1,
          status: "pending",
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        })
      } catch (err: any) {
        blocked = err?.code === "permission-denied" || err?.message?.includes("permission")
      }
      expect(blocked).toBe(true)
    })
  })

  // --------------------------------------------------------------------------
  // 3. Host Cancellation Cascade & Notifications
  // --------------------------------------------------------------------------
  describe("3. Host Cancellation Cascade", () => {
    it("B4-3: Host cancels ride -> all pending & accepted requests marked cancelled and riders notified", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Lulu Mall, Kochi",
        date: tomorrow,
        departureTime: "06:00 AM",
        seats: 3,
        totalSeats: 3,
        vehicleType: "car"
      })
      cleanupRides.push(rideId)

      // Rider 1 requests seat (will remain pending)
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const req1 = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 3, from: "CET", to: "Lulu Mall", date: tomorrow, departureTime: "06:00 AM" },
        maleRiderUid,
        1
      )
      expect(req1.success).toBe(true)
      const req1Id = req1.requestId!
      cleanupRequests.push(req1Id)

      // Rider 2 requests seat (will be accepted)
      await signInWithEmailAndPassword(auth, maleRider2Email, password)
      const req2 = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 3, from: "CET", to: "Lulu Mall", date: tomorrow, departureTime: "06:00 AM" },
        maleRider2Uid,
        1
      )
      expect(req2.success).toBe(true)
      const req2Id = req2.requestId!
      cleanupRequests.push(req2Id)

      // Host accepts Rider 2
      await signInWithEmailAndPassword(auth, hostEmail, password)
      const acceptRes = await rideRequestService.acceptRideRequest(req2Id, hostUid)
      expect(acceptRes.success).toBe(true)

      // Now Host cancels the entire ride
      const cancelReason = "Car has a flat tire"
      const cancelRes = await rideService.cancelRide(rideId, hostUid, cancelReason)
      expect(cancelRes.success).toBe(true)

      // Verify ride document
      const rideSnap = await getDoc(doc(db, "rides", rideId))
      const rideData = rideSnap.data()!
      expect(rideData.status).toBe("cancelled")
      expect(rideData.cancelledBy).toBe(hostUid)
      expect(rideData.cancellationReason).toBe(cancelReason)

      // Verify both requests transitioned to cancelled
      const req1Snap = await getDoc(doc(db, "rideRequests", req1Id))
      expect(req1Snap.data()?.status).toBe("cancelled")
      expect(req1Snap.data()?.cancelledBy).toBe(hostUid)
      expect(req1Snap.data()?.cancellationReason).toBe(cancelReason)

      const req2Snap = await getDoc(doc(db, "rideRequests", req2Id))
      expect(req2Snap.data()?.status).toBe("cancelled")
      expect(req2Snap.data()?.cancelledBy).toBe(hostUid)
      expect(req2Snap.data()?.cancellationReason).toBe(cancelReason)

      // Verify contact document: once cancelled, privacy lockdown ensures
      // unconfirmed / cancelled parties can no longer access personal contact details
      let contactReadBlocked = false
      try {
        await getDoc(doc(db, "rideContacts", req2Id))
      } catch (err: any) {
        contactReadBlocked = err?.code === "permission-denied" || err?.message?.includes("permission")
      }
      expect(contactReadBlocked).toBe(true)

      // Verify riders received notifications of type "ride_cancelled" (each user signs in to read their own notifications)
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const notifQ1 = query(
        collection(db, "notifications"),
        where("userId", "==", maleRiderUid),
        where("rideId", "==", rideId),
        where("type", "==", "ride_cancelled")
      )
      const notifSnap1 = await getDocs(notifQ1)
      expect(notifSnap1.empty).toBe(false)

      await signInWithEmailAndPassword(auth, maleRider2Email, password)
      const notifQ2 = query(
        collection(db, "notifications"),
        where("userId", "==", maleRider2Uid),
        where("rideId", "==", rideId),
        where("type", "==", "ride_cancelled")
      )
      const notifSnap2 = await getDocs(notifQ2)
      expect(notifSnap2.empty).toBe(false)
    })
  })

  // --------------------------------------------------------------------------
  // 4. Accepted Rider Cancellation & Atomic Seat Restoration
  // --------------------------------------------------------------------------
  describe("4. Rider Cancellation & Seat Restoration", () => {
    it("B4-4A: Accepted rider cancels -> seats restored, passenger removed, full reverted to active", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Kovalam Beach",
        date: tomorrow,
        departureTime: "04:00 PM",
        seats: 1,
        totalSeats: 1,
        vehicleType: "bike"
      })
      cleanupRides.push(rideId)

      // Rider 1 requests the only seat
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const req = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 1, from: "CET", to: "Kovalam", date: tomorrow, departureTime: "04:00 PM" },
        maleRiderUid,
        1
      )
      expect(req.success).toBe(true)
      const reqId = req.requestId!
      cleanupRequests.push(reqId)

      // Host accepts Rider 1 -> ride becomes "full" with 0 seats
      await signInWithEmailAndPassword(auth, hostEmail, password)
      const acceptRes = await rideRequestService.acceptRideRequest(reqId, hostUid)
      expect(acceptRes.success).toBe(true)

      const fullRideSnap = await getDoc(doc(db, "rides", rideId))
      expect(fullRideSnap.data()?.status).toBe("full")
      expect(fullRideSnap.data()?.availableSeats).toBe(0)
      expect(fullRideSnap.data()?.acceptedPassengers.length).toBe(1)

      // Rider 1 cancels their accepted request
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const cancelRes = await rideRequestService.cancelRideRequest(reqId, maleRiderUid)
      expect(cancelRes.success).toBe(true)

      // Verify ride document state restored
      const restoredRideSnap = await getDoc(doc(db, "rides", rideId))
      const restoredData = restoredRideSnap.data()!
      expect(restoredData.availableSeats).toBe(1)
      expect(restoredData.status).toBe("active")
      expect(restoredData.acceptedPassengers.length).toBe(0)

      // Verify request and contact state
      const reqSnap = await getDoc(doc(db, "rideRequests", reqId))
      expect(reqSnap.data()?.status).toBe("cancelled")

      // Verify contact document is immediately inaccessible to cancelled passenger (privacy lockdown)
      let contactReadBlocked = false
      try {
        await getDoc(doc(db, "rideContacts", reqId))
      } catch (err: any) {
        contactReadBlocked = err?.code === "permission-denied" || err?.message?.includes("permission")
      }
      expect(contactReadBlocked).toBe(true)
    })

    it("B4-4B: Concurrency: Two accepted riders cancelling simultaneously both restore seats", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(hostUid, {
        from: "CET Trivandrum",
        to: "Airport",
        date: tomorrow,
        departureTime: "05:00 PM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car"
      })
      cleanupRides.push(rideId)

      // Rider 1 requests 1 seat
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const req1 = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Airport", date: tomorrow, departureTime: "05:00 PM" },
        maleRiderUid,
        1
      )
      const req1Id = req1.requestId!
      cleanupRequests.push(req1Id)

      // Rider 2 requests 1 seat
      await signInWithEmailAndPassword(auth, maleRider2Email, password)
      const req2 = await rideRequestService.createRideRequest(
        { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Airport", date: tomorrow, departureTime: "05:00 PM" },
        maleRider2Uid,
        1
      )
      const req2Id = req2.requestId!
      cleanupRequests.push(req2Id)

      // Host accepts both riders -> availableSeats becomes 0, status full
      await signInWithEmailAndPassword(auth, hostEmail, password)
      await rideRequestService.acceptRideRequest(req1Id, hostUid)
      await rideRequestService.acceptRideRequest(req2Id, hostUid)

      const fullSnap = await getDoc(doc(db, "rides", rideId))
      expect(fullSnap.data()?.availableSeats).toBe(0)
      expect(fullSnap.data()?.status).toBe("full")
      expect(fullSnap.data()?.acceptedPassengers.length).toBe(2)

      // Both riders simultaneously cancel their requests
      const [res1, res2] = await Promise.all([
        rideRequestService.cancelRideRequest(req1Id, maleRiderUid),
        rideRequestService.cancelRideRequest(req2Id, maleRider2Uid)
      ])

      expect(res1.success).toBe(true)
      expect(res2.success).toBe(true)

      // Final ride state must have exactly 2 available seats and 0 passengers
      const finalSnap = await getDoc(doc(db, "rides", rideId))
      const finalData = finalSnap.data()!
      expect(finalData.availableSeats).toBe(2)
      expect(finalData.status).toBe("active")
      expect(finalData.acceptedPassengers.length).toBe(0)
    })
  })

  // --------------------------------------------------------------------------
  // 5. Gender Policy Verification (Code & Security Rules)
  // --------------------------------------------------------------------------
  describe("5. Gender Policy Enforcement", () => {
    it("B4-5A: Male user requesting female_only ride is rejected with GENDER_MISMATCH", async () => {
      // Female creates female_only ride
      await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(femaleRiderUid, {
        from: "CET Ladies Hostel",
        to: "Palayam",
        date: tomorrow,
        departureTime: "09:00 AM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car",
        genderPolicy: "female_only"
      })
      cleanupRides.push(rideId)

      // Male attempts to request via service
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      const req = await rideRequestService.createRideRequest(
        {
          id: rideId,
          ownerId: femaleRiderUid,
          status: "active",
          availableSeats: 2,
          from: "CET Ladies Hostel",
          to: "Palayam",
          date: tomorrow,
          departureTime: "09:00 AM",
          genderPolicy: "female_only"
        },
        maleRiderUid,
        1
      )

      expect(req.success).toBe(false)
      expect(req.code === "GENDER_MISMATCH" || req.code === "RIDE_GENDER_POLICY_RESTRICTED").toBe(true)
    })

    it("B4-5B: Male user direct Firestore write to female_only ride is blocked by Security Rules", async () => {
      await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(femaleRiderUid, {
        from: "CET Ladies Hostel",
        to: "Palayam",
        date: tomorrow,
        departureTime: "09:00 AM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car",
        genderPolicy: "female_only"
      })
      cleanupRides.push(rideId)

      // Male signs in and attempts direct addDoc/setDoc bypassing service
      await signInWithEmailAndPassword(auth, maleRiderEmail, password)
      let blocked = false
      try {
        await setDoc(doc(db, "rideRequests", `male-hack-${Date.now()}`), {
          rideId,
          requesterId: maleRiderUid,
          rideOwnerId: femaleRiderUid,
          seatsRequested: 1,
          status: "pending",
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        })
      } catch (e: any) {
        blocked = e?.code === "permission-denied" || e?.message?.includes("permission")
      }
      expect(blocked).toBe(true)
    })

    it("B4-5C: Female user requesting female_only ride SUCCEEDS", async () => {
      // Host creates female_only ride (female host)
      await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
      const tomorrow = new Date(Date.now() + 24 * 3600 * 1000).toISOString().split("T")[0]
      const rideId = await rideService.createRide(femaleRiderUid, {
        from: "CET Ladies Hostel",
        to: "Palayam Library",
        date: tomorrow,
        departureTime: "10:00 AM",
        seats: 2,
        totalSeats: 2,
        vehicleType: "car",
        genderPolicy: "female_only"
      })
      cleanupRides.push(rideId)

      // Another female signs in (or we create a temporary 2nd female rider)
      const femaleRider2Email = `b4.female2.${ts}@cet.ac.in`
      const f2Cred = await createUserWithEmailAndPassword(auth, femaleRider2Email, password)
      const female2Uid = f2Cred.user.uid
      cleanupUsers.push(female2Uid)
      await userService.createUserProfile(female2Uid, {
        name: "Second Female Rider",
        gender: "female",
        college: "CET",
        department: "Arch",
        year: "3rd Year"
      })

      const req = await rideRequestService.createRideRequest(
        {
          id: rideId,
          ownerId: femaleRiderUid,
          status: "active",
          availableSeats: 2,
          from: "CET Ladies Hostel",
          to: "Palayam Library",
          date: tomorrow,
          departureTime: "10:00 AM",
          genderPolicy: "female_only"
        },
        female2Uid,
        1
      )

      expect(req.success).toBe(true)
      if (req.requestId) cleanupRequests.push(req.requestId)
    })
  })
})
