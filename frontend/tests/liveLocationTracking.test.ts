import { describe, it, expect } from "vitest"
import { calculateBearing } from "../src/services/location/liveLocationService"
import { getDistanceInMeters, formatDistance } from "../src/utils/locationService"
import { cleanLocationDisplayName } from "../src/utils/formatters"
import { isRidePastGracePeriod } from "../src/config/matchingConfig"

describe("Live Location Tracking Unit Tests", () => {
  it("calculates accurate navigational bearing between two coordinates", () => {
    // Due North
    const north = calculateBearing(0, 0, 1, 0)
    expect(Math.round(north)).toBe(0)

    // Due East
    const east = calculateBearing(0, 0, 0, 1)
    expect(Math.round(east)).toBe(90)

    // Due South
    const south = calculateBearing(0, 0, -1, 0)
    expect(Math.round(south)).toBe(180)

    // Due West
    const west = calculateBearing(0, 0, 0, -1)
    expect(Math.round(west)).toBe(270)
  })

  it("calculates proximity correctly for 'You have met' threshold (<= 30 meters)", () => {
    const lat1 = 8.545900
    const lng1 = 76.906300

    // Exactly same point -> 0 m (<= 30m, met)
    const dSame = getDistanceInMeters(lat1, lng1, lat1, lng1)
    expect(dSame).toBe(0)
    expect(dSame <= 30).toBe(true)

    // ~15 meters away -> <= 30m, met
    const d15m = getDistanceInMeters(lat1, lng1, lat1 + 0.00013, lng1)
    expect(d15m).toBeLessThanOrEqual(30)
    expect(d15m <= 30).toBe(true)

    // ~200 meters away -> > 30m, not met
    const d200m = getDistanceInMeters(lat1, lng1, lat1 + 0.0018, lng1)
    expect(d200m).toBeGreaterThan(30)
    expect(d200m <= 30).toBe(false)
  })

  it("formats distances properly for UI display", () => {
    expect(formatDistance(15)).toBe("15 m")
    expect(formatDistance(850)).toBe("850 m")
    expect(formatDistance(1250)).toBe("1.3 km")
    expect(formatDistance(2500)).toBe("2.5 km")
  })

  it("calculates campus walking ETA accurately (~80m per min)", () => {
    const calcWalkMin = (meters: number) => Math.max(1, Math.round(meters / 80))
    expect(calcWalkMin(40)).toBe(1)
    expect(calcWalkMin(240)).toBe(3)
    expect(calcWalkMin(400)).toBe(5)
    expect(calcWalkMin(800)).toBe(10)
  })

  it("correctly evaluates pairwise 'All Met' condition for multi-rider groups", () => {
    // 3 students at campus pickup: You, Anu, Rahul
    const pYou = { lat: 8.545900, lng: 76.906300 }
    const pAnuNear = { lat: 8.546020, lng: 76.906400 } // ~17m away
    const pRahulNear = { lat: 8.545980, lng: 76.906200 } // ~14m away
    const pRahulFar = { lat: 8.548500, lng: 76.909000 } // ~400m away

    const checkAllMet = (points: { lat: number; lng: number }[], threshold = 45) => {
      if (points.length < 2) return false
      for (let i = 0; i < points.length; i++) {
        for (let j = i + 1; j < points.length; j++) {
          const d = getDistanceInMeters(points[i].lat, points[i].lng, points[j].lat, points[j].lng)
          if (d > threshold) return false
        }
      }
      return true
    }

    // All within 45m
    expect(checkAllMet([pYou, pAnuNear, pRahulNear])).toBe(true)

    // One student is far away
    expect(checkAllMet([pYou, pAnuNear, pRahulFar])).toBe(false)
  })

  it("selects group location with best GPS accuracy for Phase B cab movement", () => {
    const locs = [
      { userId: "u1", lat: 8.5460, lng: 76.9065, accuracy: 25 },
      { userId: "u2", lat: 8.5461, lng: 76.9066, accuracy: 4 }, // Best lock!
      { userId: "u3", lat: 8.5458, lng: 76.9062, accuracy: 12 }
    ]

    const bestLoc = [...locs].sort((a, b) => a.accuracy - b.accuracy)[0]
    expect(bestLoc.userId).toBe("u2")
    expect(bestLoc.accuracy).toBe(4)
  })

  it("removes 'My Location' tag and preserves only the clean location name", () => {
    // Parenthetical format
    expect(cleanLocationDisplayName("My Location (Ideal Hostel, Kulathoor, Thiruvananthapuram)"))
      .toBe("Ideal Hostel, Kulathoor, Thiruvananthapuram")

    expect(cleanLocationDisplayName("My Location (College of Engineering Trivandrum)"))
      .toBe("College of Engineering Trivandrum")

    // Hyphen / colon format
    expect(cleanLocationDisplayName("My Location - CET Main Gate"))
      .toBe("CET Main Gate")

    // Normal locations without tag remain unchanged
    expect(cleanLocationDisplayName("Technopark Phase III"))
      .toBe("Technopark Phase III")

    expect(cleanLocationDisplayName("Central Railway Station"))
      .toBe("Central Railway Station")

    // Empty or undefined
    expect(cleanLocationDisplayName("")).toBe("")
    expect(cleanLocationDisplayName(undefined)).toBe("")
  })

  it("determines when a ride is past grace period and should end live tracking", () => {
    // Explicitly completed or cancelled rides are always past grace
    expect(isRidePastGracePeriod({ status: "completed" })).toBe(true)
    expect(isRidePastGracePeriod({ status: "cancelled" })).toBe(true)

    // Ride with no date
    expect(isRidePastGracePeriod(undefined)).toBe(false)

    // A ride 3 days ago is definitely past grace
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000)
    const yyyy = threeDaysAgo.getFullYear()
    const mm = String(threeDaysAgo.getMonth() + 1).padStart(2, "0")
    const dd = String(threeDaysAgo.getDate()).padStart(2, "0")
    const pastDateStr = `${yyyy}-${mm}-${dd}`

    expect(isRidePastGracePeriod(pastDateStr, "10:00 AM")).toBe(true)
    expect(isRidePastGracePeriod({ date: pastDateStr, departureTime: "10:00 AM" })).toBe(true)

    // A ride 3 days in the future is NOT past grace
    const threeDaysFuture = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000)
    const fyyyy = threeDaysFuture.getFullYear()
    const fmm = String(threeDaysFuture.getMonth() + 1).padStart(2, "0")
    const fdd = String(threeDaysFuture.getDate()).padStart(2, "0")
    const futureDateStr = `${fyyyy}-${fmm}-${fdd}`

    expect(isRidePastGracePeriod(futureDateStr, "10:00 AM")).toBe(false)
    expect(isRidePastGracePeriod({ date: futureDateStr, departureTime: "10:00 AM" })).toBe(false)
  })
})
