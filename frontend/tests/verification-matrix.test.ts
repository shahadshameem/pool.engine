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
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut
} from "firebase/auth"
import { auth, db } from "../src/config/firebase"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import { userService } from "../src/services/user/userService"
import { notificationService } from "../src/services/notification/notificationService"
import { findRidesBySmallestDistance } from "../src/services/rideService"
import {
  isRideExpired,
  calculateTimeDifferenceMinutes,
  parseTimeToMinutes,
  MAX_TIME_DIFF_MINUTES
} from "../src/config/matchingConfig"
import {
  getDistanceInMeters,
  formatDistance,
  CAMPUS_PRESETS
} from "../src/utils/locationService"
import { getLocalDateString } from "../src/utils/formatters"

describe("Comprehensive QA Verification & Bug Hunting Suite", () => {
  const ts = Date.now()
  const maleHostEmail = `male.host.${ts}@cet.ac.in`
  const maleRiderEmail = `male.rider.${ts}@cet.ac.in`
  const femaleRiderEmail = `female.rider.${ts}@cet.ac.in`
  const password = "Password123!@"

  let maleHostUid = ""
  let maleRiderUid = ""
  let femaleRiderUid = ""

  const cleanupRides: string[] = []
  const cleanupRequests: string[] = []
  const cleanupUsers: string[] = []

  beforeAll(async () => {
    // 1. Male Host
    const hCred = await createUserWithEmailAndPassword(auth, maleHostEmail, password)
    maleHostUid = hCred.user.uid
    cleanupUsers.push(maleHostUid)
    await userService.createUserProfile(maleHostUid, {
      name: "Male Host",
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "4th Year",
      phone: `9847${Math.floor(100000 + Math.random() * 900000)}`
    })

    // 2. Male Rider
    const mrCred = await createUserWithEmailAndPassword(auth, maleRiderEmail, password)
    maleRiderUid = mrCred.user.uid
    cleanupUsers.push(maleRiderUid)
    await userService.createUserProfile(maleRiderUid, {
      name: "Male Rider",
      gender: "male",
      college: "CET",
      department: "ME",
      year: "2nd Year",
      phone: `9847${Math.floor(100000 + Math.random() * 900000)}`
    })

    // 3. Female Rider
    const frCred = await createUserWithEmailAndPassword(auth, femaleRiderEmail, password)
    femaleRiderUid = frCred.user.uid
    cleanupUsers.push(femaleRiderUid)
    await userService.createUserProfile(femaleRiderUid, {
      name: "Female Rider",
      gender: "female",
      college: "CET",
      department: "CSE",
      year: "3rd Year",
      phone: `9847${Math.floor(100000 + Math.random() * 900000)}`
    })
  }, 30000)

  afterAll(async () => {
    for (const id of cleanupRides) {
      await deleteDoc(doc(db, "rides", id)).catch(() => {})
    }
    for (const id of cleanupRequests) {
      await deleteDoc(doc(db, "rideRequests", id)).catch(() => {})
    }
    for (const id of cleanupUsers) {
      await deleteDoc(doc(db, "users", id)).catch(() => {})
    }
  }, 30000)

  // ==========================================
  // PART 1: ORIGINAL BUG VERIFICATION
  // ==========================================

  describe("PART 1: Original Bug Fixes", () => {
    // B1: Expired/completed rides in search
    describe("B1: Departure & Expiry Logic", () => {
      it("B1-1: Checks if a ride from 5 minutes ago is treated as expired", () => {
        const now = new Date()
        const fiveMinAgo = new Date(now.getTime() - 5 * 60 * 1000)
        const timeStr = `${String(fiveMinAgo.getHours()).padStart(2, "0")}:${String(fiveMinAgo.getMinutes()).padStart(2, "0")}`
        const dateStr = getLocalDateString(fiveMinAgo)

        const expired = isRideExpired(dateStr, timeStr, "active")
        // NOTE FOR SKEPTICAL QA: isRideExpired has a 15-minute grace buffer!
        // So 5 min ago returns FALSE!
        expect(expired).toBe(true)
      })

      it("B1-2: Checks if a ride from 4 hours ago is treated as expired", () => {
        const now = new Date()
        const fourHoursAgo = new Date(now.getTime() - 4 * 60 * 60 * 1000)
        const timeStr = `${String(fourHoursAgo.getHours()).padStart(2, "0")}:${String(fourHoursAgo.getMinutes()).padStart(2, "0")}`
        const dateStr = getLocalDateString(fourHoursAgo)

        const expired = isRideExpired(dateStr, timeStr, "active")
        expect(expired).toBe(true)
      })

      it("B1-3: Checks if yesterday's ride is treated as expired", () => {
        const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000)
        const dateStr = getLocalDateString(yesterday)
        expect(isRideExpired(dateStr, "10:00 AM", "active")).toBe(true)
      })

      it("B1-4: Checks completed or cancelled status is always expired", () => {
        expect(isRideExpired("2099-01-01", "10:00 AM", "completed")).toBe(true)
        expect(isRideExpired("2099-01-01", "10:00 AM", "cancelled")).toBe(true)
      })

      it("B1-5: 12:00 AM and 12:00 PM parsing in parseTimeToMinutes", () => {
        expect(parseTimeToMinutes("12:00 AM")).toBe(0)
        expect(parseTimeToMinutes("12:30 AM")).toBe(30)
        expect(parseTimeToMinutes("12:00 PM")).toBe(720)
        expect(parseTimeToMinutes("12:30 PM")).toBe(750)
      })

      it("B1-6: Midnight crossing time difference (23:55 to 00:05)", () => {
        const diff = calculateTimeDifferenceMinutes("23:55", "00:05")
        // Expected: 10 minutes across midnight boundary
        // Current implementation: |1435 - 5| = 1430 minutes!
        expect(diff).toBeLessThanOrEqual(10)
      })
    })

    // B2: Time Window Rule
    describe("B2: Time Window Rule & Edges", () => {
      it("B2-1: Enforces MAX_TIME_DIFF_MINUTES (±10 min boundary)", () => {
        expect(calculateTimeDifferenceMinutes("10:00", "10:10")).toBe(10)
        expect(calculateTimeDifferenceMinutes("10:00", "10:11")).toBe(11)
        expect(MAX_TIME_DIFF_MINUTES).toBe(10)
      })

      it("B2-2: Distance search filters out rides beyond the time window", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const targetDate = "2026-11-25"

        // Ride at 10:00 AM
        const ride10am = await rideService.createRide(maleHostUid, {
          from: "College of Engineering Trivandrum",
          to: "Trivandrum Central Railway Station",
          fromLocation: { name: "CET", address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
          toLocation: { name: "Central", address: "Thampanoor", latitude: 8.4875, longitude: 76.9525 },
          date: targetDate,
          departureTime: "10:00 AM",
          totalSeats: 3,
          availableSeats: 3
        })
        cleanupRides.push(ride10am)

        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        // Passenger searches for 10:08 AM (8 min diff -> inside 10 min window)
        const insideResults = await findRidesBySmallestDistance({
          source: { lat: 8.5459, lng: 76.9063 },
          destination: { lat: 8.4875, lng: 76.9525 },
          pickupRadiusMeters: 4000,
          dropoffRadiusMeters: 4000,
          date: targetDate,
          time: "10:08 AM"
        })
        expect(insideResults.some(r => r.id === ride10am)).toBe(true)

        // Passenger searches for 10:25 AM (25 min diff -> outside 10 min window)
        const outsideResults = await findRidesBySmallestDistance({
          source: { lat: 8.5459, lng: 76.9063 },
          destination: { lat: 8.4875, lng: 76.9525 },
          pickupRadiusMeters: 4000,
          dropoffRadiusMeters: 4000,
          date: targetDate,
          time: "10:25 AM"
        })
        expect(outsideResults.some(r => r.id === ride10am)).toBe(false)
      }, 25000)
    })

    // B3: Ride Request Acceptance End to End
    describe("B3: Request Acceptance End-to-End", () => {
      it("B3-1: Full flow: request -> accept -> seat decrements -> passenger listed -> notification created", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Technopark Phase 1",
          fromLocation: { name: "CET", address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
          toLocation: { name: "Technopark", address: "Kazhakootam", latitude: 8.5581, longitude: 76.8816 },
          date: "2026-11-26",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        // Male rider requests 1 seat
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const reqResult = await rideRequestService.createRideRequest(
          {
            id: rideId,
            ownerId: maleHostUid,
            status: "OPEN",
            availableSeats: 2,
            from: "CET",
            to: "Technopark",
            date: "2026-11-26",
            departureTime: "09:00 AM"
          },
          maleRiderUid,
          1
        )
        expect(reqResult.success).toBe(true)
        const reqId = reqResult.requestId!
        cleanupRequests.push(reqId)

        // Host accepts
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const acceptRes = await rideRequestService.acceptRideRequest(reqId, maleHostUid)
        expect(acceptRes.success).toBe(true)

        // Verify ride document
        const rideSnap = await getDoc(doc(db, "rides", rideId))
        const rideData = rideSnap.data()!
        expect(rideData.availableSeats).toBe(1)
        expect(rideData.acceptedPassengers).toHaveLength(1)
        expect(rideData.acceptedPassengers[0].uid).toBe(maleRiderUid)

        // Verify notification for rider (sign in as rider to satisfy least-privilege rules)
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const notifQ = query(
          collection(db, "notifications"),
          where("userId", "==", maleRiderUid),
          where("type", "==", "request_accepted")
        )
        const notifSnap = await getDocs(notifQ)
        expect(notifSnap.empty).toBe(false)
      }, 25000)

      it("B3-2: Non-host attempting to accept must be rejected", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Palayam",
          fromLocation: { name: "CET", address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
          toLocation: { name: "Palayam", address: "Palayam", latitude: 8.5028, longitude: 76.9534 },
          date: "2026-11-27",
          departureTime: "08:00 AM",
          totalSeats: 1,
          availableSeats: 1
        })
        cleanupRides.push(rideId)

        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const reqResult = await rideRequestService.createRideRequest(
          {
            id: rideId,
            ownerId: maleHostUid,
            status: "OPEN",
            availableSeats: 1,
            from: "CET",
            to: "Palayam",
            date: "2026-11-27",
            departureTime: "08:00 AM"
          },
          maleRiderUid,
          1
        )
        const reqId = reqResult.requestId!
        cleanupRequests.push(reqId)

        // Female rider (unrelated third party) tries to accept
        await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
        const hijackRes = await rideRequestService.acceptRideRequest(reqId, femaleRiderUid)
        expect(hijackRes.success).toBe(false)
      }, 25000)

      it("B3-3: Accept with 0 available seats remaining must fail", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Palayam",
          fromLocation: { name: "CET", address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
          toLocation: { name: "Palayam", address: "Palayam", latitude: 8.5028, longitude: 76.9534 },
          date: "2026-11-28",
          departureTime: "08:00 AM",
          totalSeats: 1,
          availableSeats: 1
        })
        cleanupRides.push(rideId)

        // Rider 1 requests 1 seat
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const req1 = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "OPEN", availableSeats: 1, from: "CET", to: "Palayam", date: "2026-11-28", departureTime: "08:00 AM" },
          maleRiderUid,
          1
        )
        cleanupRequests.push(req1.requestId!)

        // Rider 2 requests 1 seat
        await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
        const req2 = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "OPEN", availableSeats: 1, from: "CET", to: "Palayam", date: "2026-11-28", departureTime: "08:00 AM" },
          femaleRiderUid,
          1
        )
        cleanupRequests.push(req2.requestId!)

        // Host accepts Rider 1
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const accept1 = await rideRequestService.acceptRideRequest(req1.requestId!, maleHostUid)
        expect(accept1.success).toBe(true)

        // Host attempts to accept Rider 2 (0 seats remaining)
        const accept2 = await rideRequestService.acceptRideRequest(req2.requestId!, maleHostUid)
        expect(accept2.success).toBe(false)
        expect(accept2.message).toContain("not enough seats")
      }, 25000)

      it("B3-4: Cancel after accept restores available seats and removes passenger", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "LuLu Mall",
          fromLocation: { name: "CET", address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
          toLocation: { name: "LuLu Mall", address: "Akkulam", latitude: 8.5350, longitude: 76.9010 },
          date: "2026-11-29",
          departureTime: "02:00 PM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const reqRes = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "OPEN", availableSeats: 2, from: "CET", to: "LuLu Mall", date: "2026-11-29", departureTime: "02:00 PM" },
          maleRiderUid,
          1
        )
        const reqId = reqRes.requestId!
        cleanupRequests.push(reqId)

        // Host accepts
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        await rideRequestService.acceptRideRequest(reqId, maleHostUid)

        // Rider cancels accepted request
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const cancelRes = await rideRequestService.cancelRideRequest(reqId, maleRiderUid)
        expect(cancelRes.success).toBe(true)

        // Seats restored to 2, passenger removed
        const rideSnap = await getDoc(doc(db, "rides", rideId))
        const rideData = rideSnap.data()!
        expect(rideData.availableSeats).toBe(2)
        expect(rideData.acceptedPassengers).toHaveLength(0)
      }, 25000)
    })

    // B4: Exact Place Names & Distance Precision
    describe("B4: Place Name & Distance Accuracy", () => {
      it("B4-1: Preserves host's picked place names ('College of Engineering Trivandrum')", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const cet = CAMPUS_PRESETS.find(p => p.name.includes("College of Engineering"))!
        const central = CAMPUS_PRESETS.find(p => p.name.includes("Central Railway"))!

        const rideId = await rideService.createRide(maleHostUid, {
          from: cet.name,
          to: central.name,
          fromLocation: { name: cet.name, address: cet.subtext || cet.area || cet.name, latitude: cet.lat, longitude: cet.lng },
          toLocation: { name: central.name, address: central.subtext || central.area || central.name, latitude: central.lat, longitude: central.lng },
          date: "2026-12-01",
          departureTime: "09:00 AM",
          totalSeats: 1,
          availableSeats: 1
        })
        cleanupRides.push(rideId)

        const snap = await getDoc(doc(db, "rides", rideId))
        const data = snap.data()!
        expect(data.from).toBe("College of Engineering Trivandrum")
        expect(data.to).toBe("Trivandrum Central Railway Station")
        expect(data.fromLocation.name).toBe("College of Engineering Trivandrum")
      }, 20000)

      it("B4-2: Distance calculations on known coordinate pairs", () => {
        // Same point gives 0m
        expect(getDistanceInMeters(8.5459, 76.9063, 8.5459, 76.9063)).toBe(0)
        expect(formatDistance(0)).toBe("0 m")

        // CET Gate (8.5459, 76.9063) to Sreekaryam Junction (8.5486, 76.9168) is ~1.19 km
        const cetToSreekaryam = getDistanceInMeters(8.5459, 76.9063, 8.5486, 76.9168)
        expect(cetToSreekaryam).toBeGreaterThanOrEqual(1100)
        expect(cetToSreekaryam).toBeLessThanOrEqual(1300)
        expect(formatDistance(cetToSreekaryam)).toBe("1.2 km")

        // Central Railway Station (8.4875, 76.9525) to KSRTC Central Bus Station (8.4883, 76.9515) is ~140-160 m
        const rlyToKsrtc = getDistanceInMeters(8.4875, 76.9525, 8.4883, 76.9515)
        expect(rlyToKsrtc).toBeGreaterThanOrEqual(100)
        expect(rlyToKsrtc).toBeLessThanOrEqual(200)
        expect(formatDistance(rlyToKsrtc)).toMatch(/^\d{3}\s*m$/)
      })
    })

    // B5: Exclude Own Rides
    describe("B5: Own Ride Exclusion", () => {
      it("B5-1: Search excludes the host's own hosted rides", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Central",
          fromLocation: { name: "CET", address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
          toLocation: { name: "Central", address: "Thampanoor", latitude: 8.4875, longitude: 76.9525 },
          date: "2026-12-02",
          departureTime: "04:00 PM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        const results = await findRidesBySmallestDistance({
          source: { lat: 8.5459, lng: 76.9063 },
          destination: { lat: 8.4875, lng: 76.9525 },
          pickupRadiusMeters: 4000,
          dropoffRadiusMeters: 4000,
          date: "2026-12-02",
          userId: maleHostUid
        })
        expect(results.some(r => r.id === rideId)).toBe(false)
      }, 20000)
    })
  })

  // ==========================================
  // PART 2: HUNTING FOR NEW BUGS
  // ==========================================

  describe("PART 2: Bug Hunting", () => {
    // 1. Ride Creation Edge Cases
    describe("1. Ride Creation Edge Cases", () => {
      it("NEW-1A: Can a ride be created for a past date/time?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const pastDate = "2026-01-01"
        // Expected: should throw error
        // Actual: does createRide reject it?
        let threw = false
        try {
          const id = await rideService.createRide(maleHostUid, {
            from: "CET",
            to: "Pattom",
            date: pastDate,
            departureTime: "08:00 AM",
            totalSeats: 1,
            availableSeats: 1
          })
          cleanupRides.push(id)
        } catch {
          threw = true
        }
        expect(threw).toBe(true)
      }, 20000)

      it("NEW-1B: Can a ride be created with 0 or negative seats?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        await expect(rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Pattom",
          date: "2026-12-03",
          departureTime: "08:00 AM",
          totalSeats: 0,
          availableSeats: 0
        })).rejects.toThrow()

        await expect(rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Pattom",
          date: "2026-12-03",
          departureTime: "08:00 AM",
          totalSeats: -2,
          availableSeats: -2
        })).rejects.toThrow()
      }, 20000)

      it("NEW-1C: Can a bike ride have 6 seats (exceed vehicle capacity)?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        let threw = false
        try {
          const id = await rideService.createRide(maleHostUid, {
            from: "CET",
            to: "Pattom",
            vehicleType: "bike",
            date: "2026-12-04",
            departureTime: "08:00 AM",
            totalSeats: 6,
            availableSeats: 6
          })
          cleanupRides.push(id)
        } catch {
          threw = true
        }
        // Expected: bikes shouldn't have 6 seats
        expect(threw).toBe(true)
      }, 20000)

      it("NEW-1D: Can a ride have the same From and To?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        let threw = false
        try {
          const id = await rideService.createRide(maleHostUid, {
            from: "College of Engineering Trivandrum",
            to: "College of Engineering Trivandrum",
            date: "2026-12-05",
            departureTime: "08:00 AM",
            totalSeats: 1,
            availableSeats: 1
          })
          cleanupRides.push(id)
        } catch {
          threw = true
        }
        // Expected: should reject origin == destination
        expect(threw).toBe(true)
      }, 20000)
    })

    // 2. Request Edge Cases
    describe("2. Request Edge Cases", () => {
      it("NEW-2A: Can a host request a seat on their own ride?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Pattom",
          date: "2026-12-06",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        const req = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "OPEN", availableSeats: 2, from: "CET", to: "Pattom", date: "2026-12-06", departureTime: "09:00 AM" },
          maleHostUid,
          1
        )
        expect(req.success).toBe(false)
        expect(req.code).toBe("SELF_REQUEST")
      }, 20000)

      it("NEW-2B: Can duplicate active requests be sent for the same ride?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Pattom",
          date: "2026-12-07",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const req1 = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "OPEN", availableSeats: 2, from: "CET", to: "Pattom", date: "2026-12-07", departureTime: "09:00 AM" },
          maleRiderUid,
          1
        )
        expect(req1.success).toBe(true)
        cleanupRequests.push(req1.requestId!)

        const req2 = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "OPEN", availableSeats: 2, from: "CET", to: "Pattom", date: "2026-12-07", departureTime: "09:00 AM" },
          maleRiderUid,
          1
        )
        expect(req2.success).toBe(false)
        expect(req2.code).toBe("DUPLICATE_REQUEST")
      }, 20000)

      it("NEW-2C: Can a request be sent to a cancelled ride?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Pattom",
          date: "2026-12-08",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        await rideService.cancelRide(rideId, maleHostUid)

        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const req = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: maleHostUid, status: "cancelled", availableSeats: 2, from: "CET", to: "Pattom", date: "2026-12-08", departureTime: "09:00 AM" },
          maleRiderUid,
          1
        )
        expect(req.success).toBe(false)
      }, 20000)
    })

    // 3. Gender Policy Enforcement
    describe("3. Gender Policy Enforcement", () => {
      it("NEW-3A: Male user requesting female_only ride must be blocked by code", async () => {
        await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
        // Female creates female_only ride
        const rideId = await rideService.createRide(femaleRiderUid, {
          from: "CET Ladies Hostel",
          to: "Palayam",
          date: "2026-12-09",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        // Male attempts to request
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const req = await rideRequestService.createRideRequest(
          { id: rideId, ownerId: femaleRiderUid, status: "OPEN", availableSeats: 2, from: "CET Ladies Hostel", to: "Palayam", date: "2026-12-09", departureTime: "09:00 AM", genderPolicy: "female_only" },
          maleRiderUid,
          1
        )
        expect(req.success).toBe(false)
        expect(req.code).toBe("GENDER_MISMATCH")
      }, 20000)

      it("NEW-3B: Male user direct Firestore write to female_only ride request blocked by Security Rules", async () => {
        await signInWithEmailAndPassword(auth, femaleRiderEmail, password)
        const rideId = await rideService.createRide(femaleRiderUid, {
          from: "CET Ladies Hostel",
          to: "Palayam",
          date: "2026-12-10",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        // Male signs in and attempts direct addDoc bypassing service
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        let blocked = false
        try {
          await setDoc(doc(db, "rideRequests", `male-hack-${Date.now()}`), {
            rideId,
            requesterId: maleRiderUid,
            rideOwnerId: femaleRiderUid,
            seatsRequested: 1,
            status: "pending",
            createdAt: new Date(),
            updatedAt: new Date()
          })
        } catch (e: any) {
          blocked = e?.code === "permission-denied" || e?.message?.includes("permission")
        }
        expect(blocked).toBe(true)
      }, 20000)
    })

    // 4. Privacy & Data Exposure
    describe("4. Privacy & Data Exposure", () => {
      it("NEW-4A: Does the public user profile document expose the phone number?", async () => {
        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        // Read male host profile from Firestore directly
        const hostDoc = await getDoc(doc(db, "users", maleHostUid))
        const data = hostDoc.data()

        // SKEPTICAL QA ASSERTION:
        // Constitution Principle III states personal contact details MUST NEVER be exposed publicly.
        // If data.phone exists and is readable by other users, this is a privacy leak!
        expect(data?.phone).toBeUndefined()
      }, 20000)

      it("NEW-4B: Does the public ride document expose driverPhone to searchers?", async () => {
        await signInWithEmailAndPassword(auth, maleHostEmail, password)
        const rideId = await rideService.createRide(maleHostUid, {
          from: "CET",
          to: "Palayam",
          date: "2026-12-11",
          departureTime: "09:00 AM",
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(rideId)

        await signInWithEmailAndPassword(auth, maleRiderEmail, password)
        const rideDoc = await getDoc(doc(db, "rides", rideId))
        const rideData = rideDoc.data()!

        // SKEPTICAL QA: driverPhone should not be visible in public ride document
        expect(rideData.driverPhone).toBeFalsy()
      }, 20000)
    })
  })
})
