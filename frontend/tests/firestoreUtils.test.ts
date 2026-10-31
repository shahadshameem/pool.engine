import { describe, it, expect } from "vitest"
import { removeUndefined } from "../src/utils/firestoreUtils"
import { Timestamp } from "firebase/firestore"

describe("Firestore Utilities - removeUndefined", () => {
  it("strips top-level undefined properties without mutating other values", () => {
    const input = {
      a: "hello",
      b: undefined,
      c: 123,
      d: false,
      e: null
    }

    const output = removeUndefined(input)
    expect(output).toEqual({
      a: "hello",
      c: 123,
      d: false,
      e: null
    })
    expect("b" in output).toBe(false)
  })

  it("recursively strips nested undefined properties (e.g. fromLocation.matchedZoneId)", () => {
    const input = {
      from: "College of Engineering Trivandrum",
      to: "Trivandrum Central Railway Station",
      fromLocation: {
        name: "CET",
        address: "CET Front Gate",
        latitude: 8.546938,
        longitude: 76.905484,
        matchedZoneId: undefined, // undefined in nested object
        rawGps: undefined,
        isLowAccuracy: undefined,
        accuracyMeters: undefined
      },
      toLocation: {
        name: "Central Station",
        latitude: 8.4869,
        longitude: 76.9532,
        matchedZoneId: undefined
      }
    }

    const output = removeUndefined(input)

    expect(output.fromLocation).toEqual({
      name: "CET",
      address: "CET Front Gate",
      latitude: 8.546938,
      longitude: 76.905484
    })
    expect("matchedZoneId" in output.fromLocation).toBe(false)
    expect("rawGps" in output.fromLocation).toBe(false)
    expect("isLowAccuracy" in output.fromLocation).toBe(false)
    expect("accuracyMeters" in output.fromLocation).toBe(false)

    expect(output.toLocation).toEqual({
      name: "Central Station",
      latitude: 8.4869,
      longitude: 76.9532
    })
    expect("matchedZoneId" in output.toLocation).toBe(false)
  })

  it("cleans undefined values inside arrays of objects", () => {
    const input = {
      stops: [
        { name: "Stop 1", time: "10:00", notes: undefined },
        { name: "Stop 2", time: undefined, notes: "Wait at junction" }
      ]
    }

    const output = removeUndefined(input)
    expect(output.stops[0]).toEqual({ name: "Stop 1", time: "10:00" })
    expect(output.stops[1]).toEqual({ name: "Stop 2", notes: "Wait at junction" })
  })

  it("preserves Date objects intact", () => {
    const now = new Date()
    const input = {
      createdAt: now,
      tag: undefined
    }

    const output = removeUndefined(input)
    expect(output.createdAt).toBe(now)
    expect(output.createdAt instanceof Date).toBe(true)
  })

  it("preserves Firestore Timestamp and FieldValue sentinels", () => {
    const timestamp = Timestamp.now()
    const sentinel = { _methodName: "serverTimestamp" }

    const input = {
      departureTimestamp: timestamp,
      serverTime: sentinel,
      optionalNotes: undefined,
      nested: {
        updatedAt: sentinel,
        badField: undefined
      }
    }

    const output = removeUndefined(input)
    expect(output.departureTimestamp).toBe(timestamp)
    expect(output.serverTime).toBe(sentinel)
    expect(output.nested.updatedAt).toBe(sentinel)
    expect("badField" in output.nested).toBe(false)
  })
})
