import { describe, it, expect } from "vitest"
import { chunkArray, cabPoolService } from "../src/services/cabPool/cabPoolService"

describe("PHASE 7 — PEER TAXI / CAB SHARING POOLS (Strategy 1)", () => {
  it("P6-1: Correctly chunks array of 12 rejected requests into 3 pools of 4 passengers", () => {
    const rejectedUserIds = Array.from({ length: 12 }, (_, i) => `user-${i + 1}`)
    const chunks = chunkArray(rejectedUserIds, 4)

    expect(chunks.length).toBe(3)
    expect(chunks[0].length).toBe(4)
    expect(chunks[1].length).toBe(4)
    expect(chunks[2].length).toBe(4)

    expect(chunks[0]).toEqual(["user-1", "user-2", "user-3", "user-4"])
    expect(chunks[1]).toEqual(["user-5", "user-6", "user-7", "user-8"])
    expect(chunks[2]).toEqual(["user-9", "user-10", "user-11", "user-12"])
  })

  it("P6-2: Handles non-multiple counts (e.g. 10 rejected users -> 2 pools of 4, 1 pool of 2)", () => {
    const rejectedUserIds = Array.from({ length: 10 }, (_, i) => `user-${i + 1}`)
    const chunks = chunkArray(rejectedUserIds, 4)

    expect(chunks.length).toBe(3)
    expect(chunks[0].length).toBe(4)
    expect(chunks[1].length).toBe(4)
    expect(chunks[2].length).toBe(2)
  })

  it("P6-3: Handles small rejection count (< 4 users -> single forming pool)", () => {
    const rejectedUserIds = ["user-1", "user-2"]
    const chunks = chunkArray(rejectedUserIds, 4)

    expect(chunks.length).toBe(1)
    expect(chunks[0].length).toBe(2)
  })

  it("P6-4: Ensures no pool ever exceeds max capacity of 4 passengers", () => {
    const rejectedUserIds = Array.from({ length: 50 }, (_, i) => `user-${i + 1}`)
    const chunks = chunkArray(rejectedUserIds, 4)

    expect(chunks.length).toBe(13)
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(4)
    }
  })

  it("P6-5: 17 total users with 3 ride seats -> 3 accepted, 14 rejected -> 4 cab pools (3x 4-person, 1x 2-person)", () => {
    const totalUsers = 17
    const rideSeats = 3
    const acceptedUserIds = Array.from({ length: rideSeats }, (_, i) => `accepted-user-${i + 1}`)
    const rejectedUserIds = Array.from({ length: totalUsers - rideSeats }, (_, i) => `rejected-user-${i + 1}`)

    expect(acceptedUserIds.length).toBe(3)
    expect(rejectedUserIds.length).toBe(14)

    const cabPoolChunks = chunkArray(rejectedUserIds, 4)
    expect(cabPoolChunks.length).toBe(4) // 4 + 4 + 4 + 2 = 14
    expect(cabPoolChunks[0].length).toBe(4)
    expect(cabPoolChunks[1].length).toBe(4)
    expect(cabPoolChunks[2].length).toBe(4)
    expect(cabPoolChunks[3].length).toBe(2)
  })
})
