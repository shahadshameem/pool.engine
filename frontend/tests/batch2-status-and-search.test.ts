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
  serverTimestamp
} from "firebase/firestore"
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword
} from "firebase/auth"
import { auth, db } from "../src/config/firebase"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import { findRidesBySmallestDistance } from "../src/services/rideService"
import {
  isRideExpired,
  calculateTimeDifferenceMinutes,
  MAX_TIME_DIFF_MINUTES
} from "../src/config/matchingConfig"
import { RIDE_STATUS, normalizeRideStatus } from "../src/types/rideStatus"

describe("BATCH 2: Status, Expiry and Search (NEW-5, B1, B2, B3)", () => {
  const ts = Date.now()
  const password = "Password123!@"
  const hostEmail = `batch2.host.${ts}@cet.ac.in`
  const riderEmail = `batch2.rider.${ts}@cet.ac.in`

  let hostUid = ""
  let riderUid = ""

  const hostPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`
  const riderPhone = `9847${Math.floor(100000 + Math.random() * 900000)}`

  const cleanupRides: string[] = []
  const cleanupRequests: string[] = []
  const cleanupUsers: string[] = []
  const cleanupContacts: string[] = []
  const cleanupNotifs: string[] = []

  beforeAll(async () => {
    // 1. Create Host User
    const hCred = await createUserWithEmailAndPassword(auth, hostEmail, password)
    hostUid = hCred.user.uid
    cleanupUsers.push(hostUid)
    await userService.createUserProfile(hostUid, {
      name: "Batch2 Host",
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
      name: "Batch2 Rider",
      gender: "male",
      college: "CET",
      department: "CSE",
      year: "2nd Year",
      phone: riderPhone
    })
  }, 30000)

  afterAll(async () => {
    for (const id of cleanupContacts) {
      await deleteDoc(doc(db, "rideContacts", id)).catch(() => {})
    }
    for (const id of cleanupNotifs) {
      await deleteDoc(doc(db, "notifications", id)).catch(() => {})
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

  // ----------------------------------------------------------------------
  // 1. Status: Canonical Ride Status Enum
  // ----------------------------------------------------------------------
  it("B2-1: Created ride has canonical status 'active', and normalizeRideStatus normalizes 'OPEN' -> 'active'", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    const rideId = await rideService.createRide(hostUid, {
      from: "College of Engineering Trivandrum",
      to: "Central Railway Station",
      fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
      toLocation: { name: "Central", address: "Central", latitude: 8.4875, longitude: 76.9528 },
      date: "2026-11-25",
      departureTime: "10:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(rideId)

    const snap = await getDoc(doc(db, "rides", rideId))
    expect(snap.exists()).toBe(true)
    const data = snap.data()!

    // Assert canonical status is strictly "active", NOT "OPEN"
    expect(data.status).toBe(RIDE_STATUS.ACTIVE)
    expect(normalizeRideStatus("OPEN")).toBe(RIDE_STATUS.ACTIVE)
    expect(normalizeRideStatus("active")).toBe(RIDE_STATUS.ACTIVE)
    expect(normalizeRideStatus("FULL")).toBe(RIDE_STATUS.FULL)
  })

  // ----------------------------------------------------------------------
  // 2. Search query: Filter by date & status in query; exclude host's own rides
  // ----------------------------------------------------------------------
  it("B2-2: Search query filters out cancelled/completed rides in Firestore and excludes searching user's own rides", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    const targetDate = "2026-11-26"

    // 1. Active ride owned by host
    const hostRideId = await rideService.createRide(hostUid, {
      from: "CET Campus",
      to: "Thampanoor",
      fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
      toLocation: { name: "Thampanoor", address: "Thampanoor", latitude: 8.4875, longitude: 76.9528 },
      date: targetDate,
      departureTime: "10:00 AM",
      totalSeats: 2,
      availableSeats: 2
    })
    cleanupRides.push(hostRideId)

    // 2. Cancelled ride
    const cancelledRideId = await rideService.createRide(hostUid, {
      from: "CET Campus",
      to: "Thampanoor",
      fromLocation: { name: "CET", address: "CET", latitude: 8.5456, longitude: 76.9056 },
      toLocation: { name: "Thampanoor", address: "Thampanoor", latitude: 8.4875, longitude: 76.9528 },
      date: targetDate,
      departureTime: "10:00 AM",
      totalSeats: 2,
      availableSeats: 2
    })
    cleanupRides.push(cancelledRideId)
    await rideService.cancelRide(cancelledRideId, hostUid)

    // Rider searches for rides on targetDate
    await signInWithEmailAndPassword(auth, riderEmail, password)
    const riderSearchResults = await rideService.searchRides({
      from: "CET",
      to: "Thampanoor",
      date: targetDate,
      seats: 1,
      userId: riderUid
    })

    // Active host ride should be present for rider
    const foundHostRide = riderSearchResults.find(r => r.id === hostRideId)
    expect(foundHostRide).toBeDefined()

    // Cancelled ride must NOT be present
    const foundCancelled = riderSearchResults.find(r => r.id === cancelledRideId)
    expect(foundCancelled).toBeUndefined()

    // Host searches for same rides -> their own ride must be excluded
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const hostSearchResults = await rideService.searchRides({
      from: "CET",
      to: "Thampanoor",
      date: targetDate,
      seats: 1,
      userId: hostUid
    })
    const selfRideInResults = hostSearchResults.find(r => r.id === hostRideId)
    expect(selfRideInResults).toBeUndefined()
  })

  // ----------------------------------------------------------------------
  // 3. Expiry: 0 grace window & update status to 'expired' / 'completed' on read
  // ----------------------------------------------------------------------
  it("B2-3: isRideExpired has 0 grace window for past departure, and reading an expired ride updates its status", async () => {
    // 5 minutes ago is expired (0 grace window)
    const now = new Date()
    const fiveMinAgo = new Date(now.getTime() - 5 * 60 * 1000)
    const dateStr = fiveMinAgo.toISOString().split("T")[0]
    const timeStr = fiveMinAgo.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })

    const expired = isRideExpired(dateStr, timeStr, "active")
    expect(expired).toBe(true)

    // Seed a past ride directly in Firestore (since createRide forbids past date/time creation)
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const pastRideRef = doc(collection(db, "rides"))
    const pastRideId = pastRideRef.id
    await setDoc(pastRideRef, {
      ownerId: hostUid,
      driverId: hostUid,
      from: "CET",
      to: "Lulu Mall",
      date: dateStr,
      departureTime: timeStr,
      totalSeats: 3,
      availableSeats: 3,
      genderPolicy: "any",
      status: "active",
      createdAt: serverTimestamp()
    })
    cleanupRides.push(pastRideId)

    // Read the ride via rideService.getRideById: should detect expiry and update status to 'expired'
    const readRide = await rideService.getRideById(pastRideId)
    expect(readRide?.status).toBe(RIDE_STATUS.EXPIRED)

    // Verify Firestore document persisted status 'expired'
    const docSnap = await getDoc(doc(db, "rides", pastRideId))
    expect(docSnap.data()?.status).toBe(RIDE_STATUS.EXPIRED)
  })

  // ----------------------------------------------------------------------
  // 4. Midnight crossing circular time difference
  // ----------------------------------------------------------------------
  it("B2-4: calculateTimeDifferenceMinutes calculates correct circular distance across midnight", () => {
    // 23:55 (11:55 PM) to 00:05 (12:05 AM) is 10 minutes apart
    const diff1 = calculateTimeDifferenceMinutes("11:55 PM", "12:05 AM")
    expect(diff1).toBe(10)

    const diff2 = calculateTimeDifferenceMinutes("23:55", "00:05")
    expect(diff2).toBe(10)

    // 00:10 to 23:50 is 20 minutes apart
    const diff3 = calculateTimeDifferenceMinutes("00:10", "23:50")
    expect(diff3).toBe(20)
  })

  // ----------------------------------------------------------------------
  // 5. Time window in search excludes distant rides (findRidesBySmallestDistance)
  // ----------------------------------------------------------------------
  it("B2-5: Spatial search respects time filter and excludes rides outside time window", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    // 10:00 AM ride on a future date
    const morningRideId = await rideService.createRide(hostUid, {
      from: "College of Engineering Trivandrum",
      to: "Central Railway Station",
      fromLocation: { name: "CET", address: "CET", latitude: 8.5459, longitude: 76.9063 },
      toLocation: { name: "Central", address: "Central", latitude: 8.4875, longitude: 76.9525 },
      date: "2026-11-28",
      departureTime: "10:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(morningRideId)

    await signInWithEmailAndPassword(auth, riderEmail, password)

    // Search for 09:00 PM on same date
    const eveningSearch = await findRidesBySmallestDistance({
      source: { lat: 8.5459, lng: 76.9063 },
      destination: { lat: 8.4875, lng: 76.9525 },
      pickupRadiusMeters: 4000,
      dropoffRadiusMeters: 4000,
      minSeats: 1,
      date: "2026-11-28",
      time: "09:00 PM",
      userId: riderUid
    })

    const foundMorningRideInEvening = eveningSearch.find(r => r.id === morningRideId)
    expect(foundMorningRideInEvening).toBeUndefined()

    // Search for 10:15 AM on same date -> should find the 10:00 AM ride
    const morningSearch = await findRidesBySmallestDistance({
      source: { lat: 8.5459, lng: 76.9063 },
      destination: { lat: 8.4875, lng: 76.9525 },
      pickupRadiusMeters: 4000,
      dropoffRadiusMeters: 4000,
      minSeats: 1,
      date: "2026-11-28",
      time: "10:15 AM",
      maxTimeDiffMinutes: 60,
      userId: riderUid
    })

    const foundMorningRideInMorning = morningSearch.find(r => r.id === morningRideId)
    expect(foundMorningRideInMorning).toBeDefined()
  })

  // ----------------------------------------------------------------------
  // 6. Acceptance flow end-to-end (status, seats, passengers, notification)
  // ----------------------------------------------------------------------
  it("B2-6: Host accept decrements seats, updates passengers, sets status full if 0 left, and sends notification to rider", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    const rideId = await rideService.createRide(hostUid, {
      from: "CET Gate",
      to: "Thampanoor Bus Stand",
      fromLocation: { name: "CET Gate", address: "CET Gate", latitude: 8.5456, longitude: 76.9056 },
      toLocation: { name: "Thampanoor", address: "Thampanoor", latitude: 8.4875, longitude: 76.9528 },
      date: "2026-11-29",
      departureTime: "08:30 AM",
      totalSeats: 1,
      availableSeats: 1
    })
    cleanupRides.push(rideId)

    // Rider requests the 1 seat
    await signInWithEmailAndPassword(auth, riderEmail, password)
    const rideSnap = await getDoc(doc(db, "rides", rideId))
    const fullRide = { id: rideId, ...rideSnap.data() } as any

    const reqRes = await rideRequestService.createRideRequest(fullRide, riderUid, 1)
    expect(reqRes.success).toBe(true)
    const requestId = reqRes.requestId!
    cleanupRequests.push(requestId)
    cleanupContacts.push(requestId)

    // Host accepts
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const acceptRes = await rideRequestService.acceptRideRequest(requestId, hostUid)
    expect(acceptRes.success).toBe(true)

    // Verify ride doc
    const updatedRideSnap = await getDoc(doc(db, "rides", rideId))
    const updatedRideData = updatedRideSnap.data()!
    expect(updatedRideData.availableSeats).toBe(0)
    expect(updatedRideData.status).toBe(RIDE_STATUS.FULL)
    expect(updatedRideData.acceptedPassengers).toHaveLength(1)
    expect(updatedRideData.acceptedPassengers[0].uid).toBe(riderUid)

    // Verify rider received notification
    await signInWithEmailAndPassword(auth, riderEmail, password)
    const notifsQ = query(
      collection(db, "notifications"),
      where("userId", "==", riderUid),
      where("type", "==", "request_accepted")
    )
    const notifsSnap = await getDocs(notifsQ)
    expect(notifsSnap.empty).toBe(false)
    for (const d of notifsSnap.docs) {
      cleanupNotifs.push(d.id)
    }
  })
})
