import { describe, it, expect } from "vitest"
import { getRequestDetailsFromMap } from "../src/hooks/useRideRequestStatus"
import type { RideRequest } from "../src/services/rideRequest/rideRequestService"

describe("Compatible Ride Request Synchronization & Deduplication", () => {
  const mockRequestsMap: Record<string, RideRequest> = {
    // Direct rideId mapping for a pending request
    ride_host_b: {
      id: "req_123",
      rideId: "ride_host_b",
      requesterId: "user_a",
      rideOwnerId: "host_b",
      seatsRequested: 1,
      status: "pending"
    },
    // Composite key mapping
    ride_host_b_host_b: {
      id: "req_123",
      rideId: "ride_host_b",
      requesterId: "user_a",
      rideOwnerId: "host_b",
      seatsRequested: 1,
      status: "pending"
    },
    // Accepted request for another ride
    ride_host_c: {
      id: "req_456",
      rideId: "ride_host_c",
      requesterId: "user_a",
      rideOwnerId: "host_c",
      seatsRequested: 2,
      status: "accepted"
    },
    ride_host_c_host_c: {
      id: "req_456",
      rideId: "ride_host_c",
      requesterId: "user_a",
      rideOwnerId: "host_c",
      seatsRequested: 2,
      status: "accepted"
    }
  }

  it("finds pending request by exact rideId", () => {
    const result = getRequestDetailsFromMap(mockRequestsMap, "ride_host_b")
    expect(result.status).toBe("pending")
    expect(result.request?.id).toBe("req_123")
  })

  it("finds accepted request by exact rideId", () => {
    const result = getRequestDetailsFromMap(mockRequestsMap, "ride_host_c")
    expect(result.status).toBe("accepted")
    expect(result.request?.id).toBe("req_456")
  })

  it("finds request when passing an array of candidate ride IDs (matchedRideId and rideId)", () => {
    // When notification has rideId (own ride) and matchedRideId (candidate ride)
    const result = getRequestDetailsFromMap(
      mockRequestsMap,
      ["ride_host_b", "ride_user_a"],
      "host_b"
    )
    expect(result.status).toBe("pending")
    expect(result.request?.id).toBe("req_123")
  })

  it("returns status 'none' when no request exists for given candidate ride IDs", () => {
    const result = getRequestDetailsFromMap(
      mockRequestsMap,
      ["ride_unrequested_1", "ride_unrequested_2"],
      "host_d"
    )
    expect(result.status).toBe("none")
    expect(result.request).toBeNull()
  })

  it("filters out candidate rides that have active (pending/accepted) requests", () => {
    const candidateRides = [
      { id: "ride_host_b", ownerId: "host_b", from: "CET", to: "Kollam" },
      { id: "ride_host_c", ownerId: "host_c", from: "CET", to: "Kollam" },
      { id: "ride_host_d", ownerId: "host_d", from: "CET", to: "Kollam" }
    ]

    const alreadyRequestedRideIds = new Set(["ride_host_b", "ride_host_c"])

    const filtered = candidateRides.filter(r => !alreadyRequestedRideIds.has(r.id))

    expect(filtered).toHaveLength(1)
    expect(filtered[0].id).toBe("ride_host_d")
  })

  it("correctly filters notification popup queue to exclude already-requested match notifications", () => {
    const popupQueue = [
      {
        id: "notif_1",
        type: "ride_match_found",
        matchedRideId: "ride_host_b",
        rideId: "ride_user_a",
        actorId: "host_b"
      },
      {
        id: "notif_2",
        type: "ride_match_found",
        matchedRideId: "ride_host_d",
        rideId: "ride_user_a",
        actorId: "host_d"
      }
    ]

    const filteredQueue = popupQueue.filter(popup => {
      if (popup.type !== "ride_match_found") return true
      const candidateIds = [popup.matchedRideId, popup.rideId].filter(Boolean) as string[]
      const reqDetails = getRequestDetailsFromMap(mockRequestsMap, candidateIds, popup.actorId)
      return reqDetails.status !== "pending" && reqDetails.status !== "accepted"
    })

    expect(filteredQueue).toHaveLength(1)
    expect(filteredQueue[0].id).toBe("notif_2")
    expect(filteredQueue[0].matchedRideId).toBe("ride_host_d")
  })
})
