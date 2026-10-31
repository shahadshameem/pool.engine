import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  createRideWithH3,
  matchRidesWithH3,
  findRidesBySmallestDistance,
  findMatchingRides
} from "../src/services/rideService"
import * as firestore from "firebase/firestore"
import { getH3Cell } from "../src/utils/locationService"

vi.mock("firebase/firestore", async () => {
  const actual = await vi.importActual<any>("firebase/firestore")
  return {
    ...actual,
    collection: vi.fn(),
    addDoc: vi.fn(),
    getDoc: vi.fn(),
    getDocs: vi.fn(),
    doc: vi.fn(),
    updateDoc: vi.fn(),
    query: vi.fn(),
    where: vi.fn(),
    limit: vi.fn(),
    serverTimestamp: vi.fn(() => ({ _methodName: "serverTimestamp" }))
  }
})

describe("Firebase Firestore Schema & Uber H3 Ride Matching Service", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("creates a ride document with Uber H3 Resolution 8 spatial indices and OPEN status", async () => {
    const mockDocRef = { id: "ride_tvm_123" }
    vi.mocked(firestore.addDoc).mockResolvedValueOnce(mockDocRef as any)

    const rideInput = {
      driverId: "user_cet_456",
      driverName: "Arjun Nair",
      driverPhone: "9876543210",
      vehicleType: "bike" as const,
      availableSeats: 1,
      farePerSeat: 30,
      departureTime: new Date("2026-10-21T09:00:00Z"),
      source: {
        name: "CET Main Gate, Sreekaryam",
        lat: 8.5459,
        lng: 76.9063,
        pickupRadiusMeters: 800
      },
      destination: {
        name: "Technopark Phase 1 Main Gate",
        lat: 8.5581,
        lng: 76.8816,
        dropoffRadiusMeters: 1000
      },
      routeSummary: {
        distanceKm: 4.8,
        durationMins: 12
      }
    }

    const result = await createRideWithH3(rideInput)
    expect(result.id).toBe("ride_tvm_123")
    // Standardized canonical ride status is "active" (Batch 2)
    expect(["active", "OPEN"]).toContain(result.status)

    // Verify H3 indices were generated automatically
    const expectedSourceH3 = getH3Cell(8.5459, 76.9063, 8)
    const expectedDestH3 = getH3Cell(8.5581, 76.8816, 8)
    expect(result.source.h3IndexRes8).toBe(expectedSourceH3)
    expect(result.destination.h3IndexRes8).toBe(expectedDestH3)

    // Verify Firestore addDoc was invoked
    expect(firestore.addDoc).toHaveBeenCalledTimes(1)
  })

  it("throws validation error if source or destination coordinates are missing", async () => {
    await expect(
      createRideWithH3({
        driverId: "u1",
        source: { name: "No coords", lat: 0, lng: 0 } as any,
        destination: { lat: 8.5, lng: 76.9 } as any
      })
    ).rejects.toThrow("Source location coordinates")
  })

  it("matches candidate rides within circular radii and Uber H3 disks, sorting by minimum detour", async () => {
    const cetH3 = getH3Cell(8.5459, 76.9063, 8)
    const tp1H3 = getH3Cell(8.5581, 76.8816, 8)

    const mockCandidates = [
      {
        id: "ride_match_1",
        status: "OPEN",
        availableSeats: 2,
        driverId: "d1",
        source: {
          name: "CET Men's Hostel (MH)",
          lat: 8.5482,
          lng: 76.9041, // ~350m from CET Main Gate
          h3IndexRes8: cetH3
        },
        destination: {
          name: "Technopark Phase 1",
          lat: 8.5581,
          lng: 76.8816, // exact match
          h3IndexRes8: tp1H3
        }
      },
      {
        id: "ride_far_away",
        status: "OPEN",
        availableSeats: 1,
        driverId: "d2",
        source: {
          name: "Thampanoor",
          lat: 8.4875,
          lng: 76.9525, // ~8 km away
          h3IndexRes8: getH3Cell(8.4875, 76.9525, 8)
        },
        destination: {
          name: "East Fort",
          lat: 8.4828,
          lng: 76.9453,
          h3IndexRes8: getH3Cell(8.4828, 76.9453, 8)
        }
      }
    ]

    vi.mocked(firestore.getDocs).mockResolvedValue({
      docs: mockCandidates.map(c => ({
        id: c.id,
        data: () => c
      }))
    } as any)

    const matches = await matchRidesWithH3({
      source: {
        lat: 8.5459,
        lng: 76.9063,
        pickupRadiusMeters: 1000
      },
      destination: {
        lat: 8.5581,
        lng: 76.8816,
        dropoffRadiusMeters: 1000
      },
      minSeats: 1
    })

    // Only ride_match_1 matches both circles and H3 disk
    expect(matches.length).toBe(1)
    expect(matches[0].id).toBe("ride_match_1")
    expect(matches[0].isH3Match).toBe(true)
    expect(matches[0].sourceDistanceMeters).toBeLessThan(500)
    expect(matches[0].destDistanceMeters).toBeLessThan(50)
  })

  it("finds and sorts rides strictly in ascending order of smallest total walking distance", async () => {
    // Passenger: CET Main Gate (8.5459, 76.9063) to Technopark Phase 1 (8.5581, 76.8816)
    const mockRides = [
      {
        id: "driver_b_closer",
        status: "OPEN",
        availableSeats: 3,
        driverName: "Rahul",
        source: {
          name: "CET Men's Hostel (MH)",
          lat: 8.5482,
          lng: 76.9041 // ~350m from CET Main Gate
        },
        destination: {
          name: "Technopark Phase 1 Gate",
          lat: 8.5581,
          lng: 76.8816 // 0m from destination
        }
      },
      {
        id: "driver_a_further",
        status: "OPEN",
        availableSeats: 2,
        driverName: "Sneha",
        source: {
          name: "Sreekaryam Junction",
          lat: 8.5476,
          lng: 76.9161 // ~1.08 km from CET Main Gate
        },
        destination: {
          name: "Kazhakootam Junction",
          lat: 8.5684,
          lng: 76.8731 // ~1.5 km from Technopark
        }
      },
      {
        id: "driver_c_outside_radius",
        status: "OPEN",
        availableSeats: 1,
        driverName: "Kiran",
        source: {
          name: "Thampanoor",
          lat: 8.4875,
          lng: 76.9525 // ~8 km away
        },
        destination: {
          name: "East Fort",
          lat: 8.4828,
          lng: 76.9453
        }
      }
    ]

    vi.mocked(firestore.getDocs).mockResolvedValue({
      docs: mockRides.map(r => ({
        id: r.id,
        data: () => r
      })),
      forEach: (cb: any) => mockRides.forEach(r => cb({ id: r.id, data: () => r }))
    } as any)

    const results = await findRidesBySmallestDistance({
      source: { lat: 8.5459, lng: 76.9063 },
      destination: { lat: 8.5581, lng: 76.8816 },
      pickupRadiusMeters: 2500,
      dropoffRadiusMeters: 2500
    })

    // Driver C is outside 2.5 km radius, so only Driver B and Driver A match
    expect(results.length).toBe(2)

    // Driver B has total distance ~350m, Driver A has total distance ~2.6km
    // Must be ordered strictly ascending by totalDistanceMeters
    expect(results[0].id).toBe("driver_b_closer")
    expect(results[0].isClosestMatch).toBe(true)
    expect(results[0].totalDistanceMeters).toBeLessThan(results[1].totalDistanceMeters!)

    // Proximity badges must be populated
    expect(results[0].proximityBadge).toContain("Pickup:")
    expect(results[0].proximityBadge).toContain("Drop-off:")
    expect(results[0].proximityBadge).toContain("Total walk:")

    // Also supports findMatchingRides with riderSource and riderDestination parameters
    const aliasResults = await findMatchingRides({
      riderSource: { lat: 8.5459, lng: 76.9063 },
      riderDestination: { lat: 8.5581, lng: 76.8816 },
      maxDistanceMeters: 2500
    })
    expect(aliasResults.length).toBe(2)
    expect(aliasResults[0].id).toBe("driver_b_closer")
  })

  it("exports findMatchingRides and createRideOffer aliases matching the core services", async () => {
    const { findMatchingRides, createRideOffer } = await import("../src/services/rideService")
    expect(findMatchingRides).toBe(findRidesBySmallestDistance)
    expect(createRideOffer).toBe(createRideWithH3)
  })
})
