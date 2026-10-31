import { describe, it, expect, beforeAll, afterAll } from "vitest"
import {
  collection,
  doc,
  getDoc,
  setDoc,
  deleteDoc,
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

describe("BATCH 3: Validation on Ride Creation (NEW-1, NEW-2, NEW-3)", () => {
  const ts = Date.now()
  const password = "Password123!@"
  const hostEmail = `batch3.host.${ts}@cet.ac.in`
  let hostUid = ""
  const hostPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`

  const cleanupRides: string[] = []
  const cleanupUsers: string[] = []

  beforeAll(async () => {
    const cred = await createUserWithEmailAndPassword(auth, hostEmail, password)
    hostUid = cred.user.uid
    cleanupUsers.push(hostUid)
    await userService.createUserProfile(hostUid, {
      name: "Batch3 Host",
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "4th Year",
      phone: hostPhone
    })
  }, 30000)

  afterAll(async () => {
    for (const id of cleanupRides) {
      await deleteDoc(doc(db, "rides", id)).catch(() => {})
    }
    for (const id of cleanupUsers) {
      await deleteDoc(doc(db, "users", id, "private", "contact")).catch(() => {})
      await deleteDoc(doc(db, "users", id)).catch(() => {})
    }
  })

  // --------------------------------------------------------------------------
  // 1. Past Time Validation (NEW-1)
  // --------------------------------------------------------------------------
  describe("1. Past Date/Time Validation", () => {
    it("B3-V1A: Rejects ride creation for 5 minutes in the past", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000)
      const dateStr = fiveMinAgo.toISOString().split("T")[0]
      const timeStr = fiveMinAgo.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })

      let threw = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "CET",
          to: "Thampanoor",
          fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          toLocation: { name: "Thampanoor", address: "Thampanoor", latitude: 8.4875, longitude: 76.9528 },
          date: dateStr,
          departureTime: timeStr,
          totalSeats: 2,
          availableSeats: 2
        })
        cleanupRides.push(id)
      } catch (err: any) {
        threw = true
        expect(err.message).toMatch(/past/i)
      }
      expect(threw).toBe(true)
    })

    it("B3-V1B: Direct Firestore write with past departureTimestamp blocked by Security Rules", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000)
      const pastTimestamp = Timestamp.fromDate(tenMinAgo)

      let rulesBlocked = false
      try {
        await setDoc(doc(collection(db, "rides")), {
          ownerId: hostUid,
          driverId: hostUid,
          from: "CET",
          to: "Central",
          date: "2026-10-20",
          departureTime: "08:00 AM",
          departureTimestamp: pastTimestamp,
          genderPolicy: "any",
          availableSeats: 1,
          totalSeats: 1,
          status: "active",
          createdAt: serverTimestamp()
        })
      } catch {
        rulesBlocked = true
      }
      expect(rulesBlocked).toBe(true)
    })

    it("B3-V1C: Allows ride creation for future departure time (now + 5 mins)", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const future = new Date(Date.now() + 5 * 60 * 1000)
      const dateStr = `${future.getFullYear()}-${String(future.getMonth() + 1).padStart(2, "0")}-${String(future.getDate()).padStart(2, "0")}`
      const timeStr = future.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })

      const rideId = await rideService.createRide(hostUid, {
        from: "CET Main Gate",
        to: "Thampanoor Station",
        fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
        toLocation: { name: "Thampanoor", address: "Thampanoor", latitude: 8.4875, longitude: 76.9528 },
        date: dateStr,
        departureTime: timeStr,
        totalSeats: 1,
        availableSeats: 1
      })
      expect(rideId).toBeDefined()
      cleanupRides.push(rideId)
    })
  })

  // --------------------------------------------------------------------------
  // 2. Capacity Ceiling by Vehicle Type (NEW-2)
  // --------------------------------------------------------------------------
  describe("2. Vehicle Capacity Ceiling", () => {
    it("B3-V2A: Bike with 2 or 6 seats is rejected by service and rules (bike max is 1)", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      let serviceRejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "CET",
          to: "Technopark",
          fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          toLocation: { name: "Technopark", address: "Technopark", latitude: 8.5583, longitude: 76.8817 },
          date: "2026-11-20",
          departureTime: "10:00 AM",
          vehicleType: "bike",
          totalSeats: 6,
          availableSeats: 6
        })
        cleanupRides.push(id)
      } catch (err: any) {
        serviceRejected = true
        expect(err.message).toMatch(/bike.*seat/i)
      }
      expect(serviceRejected).toBe(true)

      // Direct Firestore write attempt: bike with 6 seats must be rejected by rules
      let rulesBlocked = false
      try {
        await setDoc(doc(collection(db, "rides")), {
          ownerId: hostUid,
          driverId: hostUid,
          from: "CET",
          to: "Technopark",
          date: "2026-11-20",
          departureTime: "10:00 AM",
          departureTimestamp: Timestamp.fromDate(new Date("2026-11-20T10:00:00Z")),
          genderPolicy: "any",
          vehicleType: "bike",
          availableSeats: 6,
          totalSeats: 6,
          status: "active",
          createdAt: serverTimestamp()
        })
      } catch {
        rulesBlocked = true
      }
      expect(rulesBlocked).toBe(true)
    })

    it("B3-V2B: Auto with 4 seats is rejected, but 3 seats succeeds", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      let auto4Rejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "CET",
          to: "Technopark",
          fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          toLocation: { name: "Technopark", address: "Technopark", latitude: 8.5583, longitude: 76.8817 },
          date: "2026-11-21",
          departureTime: "10:00 AM",
          vehicleType: "auto",
          totalSeats: 4,
          availableSeats: 4
        })
        cleanupRides.push(id)
      } catch (err: any) {
        auto4Rejected = true
      }
      expect(auto4Rejected).toBe(true)

      // Auto with 3 seats should succeed
      const auto3Id = await rideService.createRide(hostUid, {
        from: "CET",
        to: "Technopark",
        fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
        toLocation: { name: "Technopark", address: "Technopark", latitude: 8.5583, longitude: 76.8817 },
        date: "2026-11-21",
        departureTime: "10:00 AM",
        vehicleType: "auto",
        totalSeats: 3,
        availableSeats: 3
      })
      expect(auto3Id).toBeDefined()
      cleanupRides.push(auto3Id)
    })

    it("B3-V2C: Car with 7 seats is rejected, but 4 seats succeeds", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      let car7Rejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "CET",
          to: "Kovalam",
          fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          toLocation: { name: "Kovalam", address: "Kovalam", latitude: 8.4020, longitude: 76.9787 },
          date: "2026-11-22",
          departureTime: "11:00 AM",
          vehicleType: "car",
          totalSeats: 7,
          availableSeats: 7
        })
        cleanupRides.push(id)
      } catch {
        car7Rejected = true
      }
      expect(car7Rejected).toBe(true)

      const car4Id = await rideService.createRide(hostUid, {
        from: "CET",
        to: "Kovalam",
        fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
        toLocation: { name: "Kovalam", address: "Kovalam", latitude: 8.4020, longitude: 76.9787 },
        date: "2026-11-22",
        departureTime: "11:00 AM",
        vehicleType: "car",
        totalSeats: 4,
        availableSeats: 4
      })
      expect(car4Id).toBeDefined()
      cleanupRides.push(car4Id)
    })
  })

  // --------------------------------------------------------------------------
  // 3. Origin != Destination (NEW-3)
  // --------------------------------------------------------------------------
  describe("3. Origin and Destination Differentiation", () => {
    it("B3-V3A: Rejects ride creation when From and To place names are identical", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      let sameNameRejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "College of Engineering Trivandrum",
          to: "College of Engineering Trivandrum",
          fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          toLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          date: "2026-11-23",
          departureTime: "02:00 PM",
          totalSeats: 1,
          availableSeats: 1
        })
        cleanupRides.push(id)
      } catch (err: any) {
        sameNameRejected = true
        expect(err.message).toMatch(/same/i)
      }
      expect(sameNameRejected).toBe(true)
    })

    it("B3-V3B: Rejects ride creation when coordinates are closer than 100 meters", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      let tooCloseRejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "CET Gate 1",
          to: "CET Gate 2",
          // ~20 meters apart
          fromLocation: { name: "CET Gate 1", address: "CET Gate 1", latitude: 8.54560, longitude: 76.90560 },
          toLocation: { name: "CET Gate 2", address: "CET Gate 2", latitude: 8.54565, longitude: 76.90565 },
          date: "2026-11-23",
          departureTime: "03:00 PM",
          totalSeats: 1,
          availableSeats: 1
        })
        cleanupRides.push(id)
      } catch (err: any) {
        tooCloseRejected = true
        expect(err.message).toMatch(/close|100m/i)
      }
      expect(tooCloseRejected).toBe(true)
    })
  })

  // --------------------------------------------------------------------------
  // 4. Input Sanitization & Empty/Long String Guards
  // --------------------------------------------------------------------------
  describe("4. Input Sanitization & Length Guards", () => {
    it("B3-V4: Rejects empty location strings and overly long notes", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      // Empty 'from' string
      let emptyFromRejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "   ",
          to: "Technopark",
          date: "2026-11-24",
          departureTime: "04:00 PM",
          totalSeats: 1,
          availableSeats: 1
        })
        cleanupRides.push(id)
      } catch {
        emptyFromRejected = true
      }
      expect(emptyFromRejected).toBe(true)

      // Overly long notes (> 500 characters)
      let longNotesRejected = false
      try {
        const id = await rideService.createRide(hostUid, {
          from: "CET",
          to: "Technopark",
          fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
          toLocation: { name: "Technopark", address: "Technopark", latitude: 8.5583, longitude: 76.8817 },
          date: "2026-11-24",
          departureTime: "04:00 PM",
          totalSeats: 1,
          availableSeats: 1,
          notes: "A".repeat(600)
        })
        cleanupRides.push(id)
      } catch {
        longNotesRejected = true
      }
      expect(longNotesRejected).toBe(true)
    })

    it("B3-V6: Creates ride successfully when fromLocation and toLocation have undefined fields (matchedZoneId, rawGps, accuracyMeters)", async () => {
      await signInWithEmailAndPassword(auth, hostEmail, password)

      const id = await rideService.createRide(hostUid, {
        from: "CET Front Gate",
        to: "Trivandrum Central Railway Station",
        fromLocation: {
          name: "CET Front Gate",
          address: "College of Engineering Trivandrum (CET) Front Gate",
          latitude: 8.546938,
          longitude: 76.905484,
          matchedZoneId: undefined, // undefined nested property
          rawGps: undefined,
          isLowAccuracy: undefined,
          accuracyMeters: undefined
        } as any,
        toLocation: {
          name: "Trivandrum Central Railway Station",
          address: "Thampanoor, Thiruvananthapuram",
          latitude: 8.4869,
          longitude: 76.9532,
          matchedZoneId: undefined,
          rawGps: undefined,
          isLowAccuracy: undefined,
          accuracyMeters: undefined
        } as any,
        date: "2026-11-28",
        departureTime: "11:55 PM",
        totalSeats: 1,
        availableSeats: 1,
        notes: undefined,
        meetingPoint: undefined
      })

      expect(id).toBeDefined()
      expect(typeof id).toBe("string")
      cleanupRides.push(id)

      const ride = await rideService.getRideById(id)
      expect(ride).not.toBeNull()
      expect(ride?.from).toBe("CET Front Gate")
      expect(ride?.to).toBe("Trivandrum Central Railway Station")
      expect(ride?.fromLocation).toBeDefined()
      expect("matchedZoneId" in (ride?.fromLocation || {})).toBe(false)
    })
  })
})
