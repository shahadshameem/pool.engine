import { describe, it, expect, vi, beforeEach } from "vitest"
import * as poolEngineConfig from "../src/config/poolEngineConfig"
import { poolEngineAdapter } from "../src/services/poolEngine/poolEngineAdapter"
import { rideService } from "../src/services/ride/rideService"
import { addDoc } from "firebase/firestore"

// Mock firestore so this test runs independently of live emulator
vi.mock("../src/config/firebase", () => ({
  db: {},
  auth: { currentUser: null },
  functions: {}
}))

vi.mock("firebase/firestore", () => ({
  collection: vi.fn(),
  query: vi.fn(),
  where: vi.fn(),
  limit: vi.fn(),
  getDocs: vi.fn().mockResolvedValue({ docs: [] }),
  doc: vi.fn(),
  getDoc: vi.fn().mockResolvedValue({
    exists: () => true,
    data: () => ({ gender: "male", name: "Test Driver" })
  }),
  updateDoc: vi.fn(),
  serverTimestamp: vi.fn(),
  addDoc: vi.fn().mockResolvedValue({ id: "firestore_mock_doc_id" }),
  Timestamp: {
    fromDate: vi.fn().mockReturnValue({ seconds: 1770000000, nanoseconds: 0 })
  }
}))

describe("Controlled Workflow Integration — Host Ride Creation and Retrieval", () => {
  const futureDate = "2026-11-15"
  const futureTime = "10:00"

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("when VITE_USE_POOL_ENGINE=false (default): does NOT call Pool Engine and uses Firestore", async () => {
    vi.spyOn(poolEngineConfig, "isPoolEngineEnabled").mockReturnValue(false)
    const registerSpy = vi.spyOn(poolEngineAdapter, "registerHostRide")

    const rideId = await rideService.createRide("driver_usr_1", {
      from: "College of Engineering Trivandrum",
      to: "TVM Central Railway Station",
      date: futureDate,
      departureTime: futureTime,
      totalSeats: 3,
      availableSeats: 3
    })

    expect(registerSpy).not.toHaveBeenCalled()
    expect(addDoc).toHaveBeenCalledTimes(1)
    expect(rideId).toBe("firestore_mock_doc_id")
  })

  it("when VITE_USE_POOL_ENGINE=true: routes creation to Pool Engine, returns pool_engine ride_id, and does not write to Firestore", async () => {
    vi.spyOn(poolEngineConfig, "isPoolEngineEnabled").mockReturnValue(true)
    const registerSpy = vi.spyOn(poolEngineAdapter, "registerHostRide").mockResolvedValue({
      ride_id: "pe_host_ride_777",
      driver_id: "driver_usr_1",
      vehicle_id: "veh_car",
      origin: { latitude: 8.5475, longitude: 76.9048 },
      destination: { latitude: 8.4900, longitude: 76.9530 },
      scheduled_departure_time: 1770000000,
      available_seats: 3,
      max_detour_seconds: 900,
      direct_duration_seconds: 900,
      direct_distance_meters: 10500,
      status: "SCHEDULED",
      stops: []
    })

    const rideId = await rideService.createRide("driver_usr_1", {
      from: "College of Engineering Trivandrum",
      to: "TVM Central Railway Station",
      date: futureDate,
      departureTime: futureTime,
      totalSeats: 3,
      availableSeats: 3
    })

    expect(registerSpy).toHaveBeenCalledTimes(1)
    expect(registerSpy.mock.calls[0][1]).toBe("driver_usr_1")
    expect(addDoc).not.toHaveBeenCalled()
    expect(rideId).toBe("pe_host_ride_777")
  })

  it("when VITE_USE_POOL_ENGINE=true: fails loudly if Pool Engine fails without falling back to Firestore or creating duplicate rides", async () => {
    vi.spyOn(poolEngineConfig, "isPoolEngineEnabled").mockReturnValue(true)
    vi.spyOn(poolEngineAdapter, "registerHostRide").mockRejectedValue(
      new Error("Pool Engine backend error (HTTP 503): Service unavailable")
    )

    await expect(
      rideService.createRide("driver_usr_1", {
        from: "College of Engineering Trivandrum",
        to: "TVM Central Railway Station",
        date: futureDate,
        departureTime: futureTime,
        totalSeats: 3,
        availableSeats: 3
      })
    ).rejects.toThrow("Pool Engine backend error (HTTP 503): Service unavailable")

    // Invariant: addDoc MUST NOT be called as a silent fallback!
    expect(addDoc).not.toHaveBeenCalled()
  })

  it("blocks rapid concurrent ride creations for the exact same route and schedule (double-click protection)", async () => {
    vi.spyOn(poolEngineConfig, "isPoolEngineEnabled").mockReturnValue(true)
    let resolveFirst: any
    const slowFirstPromise = new Promise<any>((resolve) => {
      resolveFirst = resolve
    })

    vi.spyOn(poolEngineAdapter, "registerHostRide").mockImplementationOnce(() => slowFirstPromise)

    const payload = {
      from: "College of Engineering Trivandrum",
      to: "TVM Central Railway Station",
      date: futureDate,
      departureTime: futureTime,
      totalSeats: 3,
      availableSeats: 3
    }

    // First call begins in-flight
    const firstCallPromise = rideService.createRide("driver_usr_dup", payload)

    // Second immediate call with same key
    await expect(
      rideService.createRide("driver_usr_dup", payload)
    ).rejects.toThrow("A ride creation request for this route and schedule is already in progress.")

    // Complete the first call
    resolveFirst({
      ride_id: "pe_host_ride_resolved",
      driver_id: "driver_usr_dup",
      vehicle_id: "veh_car",
      origin: { latitude: 8.5475, longitude: 76.9048 },
      destination: { latitude: 8.4900, longitude: 76.9530 },
      scheduled_departure_time: 1770000000,
      available_seats: 3,
      max_detour_seconds: 900,
      direct_duration_seconds: 900,
      direct_distance_meters: 10500,
      status: "SCHEDULED",
      stops: []
    })

    const firstResult = await firstCallPromise
    expect(firstResult).toBe("pe_host_ride_resolved")
  })

  it("when VITE_USE_POOL_ENGINE=true: getRideById routes to Pool Engine adapter", async () => {
    vi.spyOn(poolEngineConfig, "isPoolEngineEnabled").mockReturnValue(true)
    const getHostSpy = vi.spyOn(poolEngineAdapter, "getHostRideAsWaymateRide").mockResolvedValue({
      id: "pe_ride_888",
      ownerId: "driver_usr_1",
      from: "CET",
      to: "Central",
      date: futureDate,
      departureTime: futureTime,
      availableSeats: 2,
      totalSeats: 2,
      status: "active"
    } as any)

    const ride = await rideService.getRideById("pe_ride_888")

    expect(getHostSpy).toHaveBeenCalledWith("pe_ride_888")
    expect(ride?.id).toBe("pe_ride_888")
  })
})
