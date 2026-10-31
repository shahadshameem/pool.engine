import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword } from "firebase/auth"
import { doc, setDoc, deleteDoc, getDoc, collection, serverTimestamp } from "firebase/firestore"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import { findRidesBySmallestDistance } from "../src/services/rideService"
import { getLocalDateString } from "../src/utils/formatters"
import { CAMPUS_PRESETS, getDistanceInMeters } from "../src/utils/locationService"

/**
 * FAILING TESTS REPRODUCING BUGS B1, B2, B3, B4, B5
 * These assertions assert the EXPECTED CORRECT BEHAVIOR.
 * They currently FAIL against the buggy codebase, proving the defects.
 */
describe("Phase A: Failing Tests Asserting Expected Correct Behavior", () => {
  const ts = Date.now()
  const password = "TestPassword123!"

  const hostEmail = `fail_host_${ts}@waymate.test`
  const passengerEmail = `fail_pass_${ts}@waymate.test`
  const hostPhone = `+9193${(ts % 100000000).toString().padStart(8, "0")}`
  const passengerPhone = `+9194${(ts % 100000000).toString().padStart(8, "0")}`

  let hostUid = ""
  let passengerUid = ""

  const cleanupRides: string[] = []
  const cleanupRequests: string[] = []
  const cleanupUsers: string[] = []

  beforeAll(async () => {
    const hCred = await createUserWithEmailAndPassword(auth, hostEmail, password)
    hostUid = hCred.user.uid
    await userService.createUserProfile(hostUid, {
      name: "Host User",
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "4th Year",
      phone: hostPhone
    })
    cleanupUsers.push(hostUid)

    const pCred = await createUserWithEmailAndPassword(auth, passengerEmail, password)
    passengerUid = pCred.user.uid
    await userService.createUserProfile(passengerUid, {
      name: "Passenger User",
      gender: "male",
      college: "CET",
      department: "ME",
      year: "2nd Year",
      phone: passengerPhone
    })
    cleanupUsers.push(passengerUid)
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
  })

  it("B1: Search MUST NOT return rides whose departure date/time has already passed", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    // Create a ride departure 2 hours in the past
    const pastDate = new Date(Date.now() - 2 * 60 * 60 * 1000)
    const pastHours = String(pastDate.getHours()).padStart(2, "0")
    const pastMins = String(pastDate.getMinutes()).padStart(2, "0")
    const pastTime = `${pastHours}:${pastMins}`
    const pastDateStr = getLocalDateString(pastDate)

    const pastRideRef = doc(collection(db, "rides"))
    const pastRideId = pastRideRef.id
    await setDoc(pastRideRef, {
      ownerId: hostUid,
      driverId: hostUid,
      from: "College of Engineering Trivandrum",
      to: "Trivandrum Central Railway Station",
      fromLocation: { address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
      toLocation: { address: "Thampanoor", latitude: 8.4875, longitude: 76.9525 },
      date: pastDateStr,
      departureTime: pastTime,
      totalSeats: 3,
      availableSeats: 3,
      genderPolicy: "any",
      status: "active",
      createdAt: serverTimestamp()
    })
    cleanupRides.push(pastRideId)

    await signInWithEmailAndPassword(auth, passengerEmail, password)
    const results = await findRidesBySmallestDistance({
      source: { lat: 8.5459, lng: 76.9063 },
      destination: { lat: 8.4875, lng: 76.9525 },
      pickupRadiusMeters: 4000,
      dropoffRadiusMeters: 4000,
      minSeats: 1
    })

    const foundPastRide = results.find(r => r.id === pastRideId)
    // EXPECTED: Expired ride should NOT be returned
    expect(foundPastRide).toBeUndefined()
  }, 20000)

  it("B2: Search MUST respect the chosen time window and exclude rides hours away", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    // Create a ride at 10:00 AM on a future date
    const distantRideId = await rideService.createRide(hostUid, {
      from: "College of Engineering Trivandrum",
      to: "Trivandrum Central Railway Station",
      fromLocation: { address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
      toLocation: { address: "Thampanoor", latitude: 8.4875, longitude: 76.9525 },
      date: "2026-11-20",
      departureTime: "10:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(distantRideId)

    await signInWithEmailAndPassword(auth, passengerEmail, password)

    // Passenger searches for 09:00 PM (21:00) on 2026-11-20
    const results = await findRidesBySmallestDistance({
      source: { lat: 8.5459, lng: 76.9063 },
      destination: { lat: 8.4875, lng: 76.9525 },
      pickupRadiusMeters: 4000,
      dropoffRadiusMeters: 4000,
      minSeats: 1,
      date: "2026-11-20",
      time: "09:00 PM"
    })

    const distantTimeRide = results.find(r => r.id === distantRideId)
    // EXPECTED: 10:00 AM ride should NOT match a search for 09:00 PM
    expect(distantTimeRide).toBeUndefined()
  }, 20000)

  it("B3: Host accepting a ride request MUST succeed and record the passenger in acceptedPassengers", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    const rideId = await rideService.createRide(hostUid, {
      from: "College of Engineering Trivandrum",
      to: "Trivandrum Central Railway Station",
      fromLocation: { address: "Sreekaryam", latitude: 8.5459, longitude: 76.9063 },
      toLocation: { address: "Thampanoor", latitude: 8.4875, longitude: 76.9525 },
      date: "2026-11-20",
      departureTime: "10:00",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(rideId)

    await signInWithEmailAndPassword(auth, passengerEmail, password)
    const reqRes = await rideRequestService.createRideRequest(
      {
        id: rideId,
        ownerId: hostUid,
        status: "OPEN",
        availableSeats: 3,
        from: "CET",
        to: "Station",
        date: "2026-11-20",
        departureTime: "10:00"
      },
      passengerUid,
      1
    )
    const requestId = reqRes.requestId!
    cleanupRequests.push(requestId)

    // Host accepts request
    await signInWithEmailAndPassword(auth, hostEmail, password)
    const acceptResult = await rideRequestService.acceptRideRequest(requestId, hostUid)

    // EXPECTED: Must succeed
    // CURRENT BUG: Returns { success: false, message: 'Ride is no longer active.' } because status is 'OPEN' not 'active'
    expect(acceptResult.success).toBe(true)
    expect(acceptResult.message).toBe("Request accepted successfully.")

    const updatedRide = await getDoc(doc(db, "rides", rideId))
    expect(updatedRide.data()?.acceptedPassengers).toHaveLength(1)
  }, 20000)

  it("B4: Stored ride MUST preserve the exact place name chosen by the host ('College of Engineering Trivandrum')", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    const cetPreset = CAMPUS_PRESETS.find(p => p.name.includes("College of Engineering"))!
    const tvmCentralPreset = CAMPUS_PRESETS.find(p => p.name.includes("Central Railway"))!

    // In OfferRidePage handleSubmit, from is set to fromLocation.name || fromLocation.address
    const fromName = cetPreset.name || cetPreset.subtext || cetPreset.area!
    const toName = tvmCentralPreset.name || tvmCentralPreset.subtext || tvmCentralPreset.area!

    const rideId = await rideService.createRide(hostUid, {
      from: fromName,
      to: toName,
      fromLocation: {
        name: fromName,
        address: cetPreset.subtext || cetPreset.area || fromName,
        latitude: cetPreset.lat,
        longitude: cetPreset.lng
      },
      toLocation: {
        name: toName,
        address: tvmCentralPreset.subtext || tvmCentralPreset.area || toName,
        latitude: tvmCentralPreset.lat,
        longitude: tvmCentralPreset.lng
      },
      date: "2026-11-20",
      departureTime: "11:00",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(rideId)

    const rideSnap = await getDoc(doc(db, "rides", rideId))
    const ride = rideSnap.data()!

    expect(ride.from).toBe("College of Engineering Trivandrum")
    expect(ride.to).toBe("Trivandrum Central Railway Station")
    expect(ride.source?.name).toBe("College of Engineering Trivandrum")
    expect(ride.destination?.name).toBe("Trivandrum Central Railway Station")
  }, 20000)

  it("B5: Search results MUST exclude the user's own hosted rides", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, password)

    // Create a ride hosted by hostUid
    const ownRideId = await rideService.createRide(hostUid, {
      from: "CET Main Gate",
      to: "Central Railway Station",
      fromLocation: {
        name: "CET Main Gate",
        address: "Sreekaryam",
        latitude: 8.5459,
        longitude: 76.9063
      },
      toLocation: {
        name: "Central Railway Station",
        address: "Thampanoor",
        latitude: 8.4875,
        longitude: 76.9525
      },
      date: "2026-11-22",
      departureTime: "04:00 PM",
      totalSeats: 3,
      availableSeats: 3
    })
    cleanupRides.push(ownRideId)

    const results = await findRidesBySmallestDistance({
      source: { lat: 8.5459, lng: 76.9063 },
      destination: { lat: 8.4875, lng: 76.9525 },
      pickupRadiusMeters: 4000,
      dropoffRadiusMeters: 4000,
      minSeats: 1,
      date: "2026-11-22",
      userId: hostUid
    })

    const ownRide = results.find(r => r.ownerId === hostUid || r.driverId === hostUid || r.id === ownRideId)
    // EXPECTED: Host's own ride should be excluded
    // CURRENT BUG: Host's own ride is returned
    expect(ownRide).toBeUndefined()
  }, 20000)
})
