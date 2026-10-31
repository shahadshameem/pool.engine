import { describe, it, expect } from "vitest"
import { rideRequestService, type RideRequest } from "../src/services/rideRequest/rideRequestService"

describe("Ride Request Service - Minimal Request Signature & Backwards Compatibility", () => {
  it("allows creating a ride request object without a message property", () => {
    const sampleRequest: RideRequest = {
      rideId: "ride_123",
      requesterId: "user_456",
      rideOwnerId: "host_789",
      seatsRequested: 2,
      status: "pending"
    }

    expect(sampleRequest.seatsRequested).toBe(2)
    expect(sampleRequest.message).toBeUndefined()
  })

  it("allows creating a ride request object with an optional message property", () => {
    const sampleRequest: RideRequest = {
      rideId: "ride_123",
      requesterId: "user_456",
      rideOwnerId: "host_789",
      seatsRequested: 1,
      message: "Optional note",
      status: "pending"
    }

    expect(sampleRequest.seatsRequested).toBe(1)
    expect(sampleRequest.message).toBe("Optional note")
  })

  it("createRideRequest function signature accepts 3 parameters (message omitted)", async () => {
    // Calling with invalid ride id to verify validation execution without throwing TypeScript/arity error
    const result = await rideRequestService.createRideRequest(
      {
        id: "",
        ownerId: "host_1",
        status: "active",
        availableSeats: 3,
        from: "CET",
        to: "Kazhakkoottam",
        date: "2026-10-01",
        departureTime: "17:30"
      },
      "user_1",
      1
    )

    expect(result.success).toBe(false)
    expect(result.code).toBe("INVALID_RIDE")
  })

  it("createRideRequest validates zero seats correctly even without message argument", async () => {
    const result = await rideRequestService.createRideRequest(
      {
        id: "ride_valid_id",
        ownerId: "host_1",
        status: "active",
        availableSeats: 3,
        from: "CET",
        to: "Kazhakkoottam",
        date: "2026-10-01",
        departureTime: "17:30"
      },
      "user_1",
      0
    )

    expect(result.success).toBe(false)
    expect(result.code).toBe("INVALID_RIDE")
    expect(result.message).toBe("You must request at least 1 seat.")
  })
})
