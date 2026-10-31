import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  resolveLocationCoordinate,
  parseDepartureTimestamp,
  mapWaymateRideToPoolEngineInput,
  mapPoolEngineHostRideToWaymateRide,
  PoolEngineAdapter,
  PoolEngineAdapterError
} from "../src/services/poolEngine/poolEngineAdapter"
import {
  PoolEngineClient,
  PoolEngineNotFoundError,
  PoolEngineAuthError,
  type HostRideDTO
} from "../src/services/poolEngine/poolEngineClient"
import type { Ride } from "../src/services/ride/rideService"

describe("Pool Engine Data Adapter Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe("Geographic Coordinate Resolution & Bounds Checking", () => {
    it("resolves explicit valid numeric coordinates", () => {
      const coord = resolveLocationCoordinate("Custom Spot", { latitude: 8.5475, longitude: 76.9048, address: "Spot" })
      expect(coord).toEqual({ latitude: 8.5475, longitude: 76.9048 })
    })

    it("resolves coordinates from predefined FIXED_LOCATIONS by name", () => {
      const coord = resolveLocationCoordinate("College of Engineering Trivandrum")
      expect(coord.latitude).toBeCloseTo(8.5469, 3)
      expect(coord.longitude).toBeCloseTo(76.9054, 3)
    })

    it("resolves coordinates from predefined TVM Central Railway Station", () => {
      const coord = resolveLocationCoordinate("TVM Central Railway Station")
      expect(coord.latitude).toBeCloseTo(8.4875, 3)
      expect(coord.longitude).toBeCloseTo(76.9525, 3)
    })

    it("rejects latitude greater than 90 with OUT_OF_BOUNDS_LATITUDE", () => {
      expect(() => {
        resolveLocationCoordinate("North Pole Outlier", { latitude: 91.5, longitude: 76.9, address: "Out of bounds" })
      }).toThrowError(PoolEngineAdapterError)

      try {
        resolveLocationCoordinate("North Pole Outlier", { latitude: 91.5, longitude: 76.9, address: "Out of bounds" })
      } catch (err: any) {
        expect(err.code).toBe("OUT_OF_BOUNDS_LATITUDE")
        expect(err.field).toBe("latitude")
      }
    })

    it("rejects latitude less than -90 with OUT_OF_BOUNDS_LATITUDE", () => {
      try {
        resolveLocationCoordinate("South Pole Outlier", { latitude: -95.0, longitude: 76.9, address: "Out of bounds" })
      } catch (err: any) {
        expect(err.code).toBe("OUT_OF_BOUNDS_LATITUDE")
      }
    })

    it("rejects longitude greater than 180 or less than -180 with OUT_OF_BOUNDS_LONGITUDE", () => {
      try {
        resolveLocationCoordinate("Dateline Outlier", { latitude: 8.5, longitude: 181.0, address: "Out of bounds" })
      } catch (err: any) {
        expect(err.code).toBe("OUT_OF_BOUNDS_LONGITUDE")
        expect(err.field).toBe("longitude")
      }
    })

    it("rejects ambiguous or unknown location with INVALID_COORDINATES", () => {
      try {
        resolveLocationCoordinate("Unknown Nonexistent Mystery Island 12345", null)
      } catch (err: any) {
        expect(err.code).toBe("INVALID_COORDINATES")
      }
    })
  })

  describe("Departure Timestamp Parsing", () => {
    it("parses ISO date and 24-hour time into correct epoch seconds", () => {
      const epochSec = parseDepartureTimestamp("2026-10-30", "14:30")
      const d = new Date(epochSec * 1000)
      expect(d.getFullYear()).toBe(2026)
      expect(d.getMonth()).toBe(9) // 0-indexed October
      expect(d.getDate()).toBe(30)
      expect(d.getHours()).toBe(14)
      expect(d.getMinutes()).toBe(30)
    })

    it("parses 12-hour AM/PM time into correct epoch seconds", () => {
      const epochSec = parseDepartureTimestamp("2026-10-30", "02:30 PM")
      const d = new Date(epochSec * 1000)
      expect(d.getHours()).toBe(14)
      expect(d.getMinutes()).toBe(30)
    })

    it("throws INVALID_DATE when date is empty or missing", () => {
      expect(() => parseDepartureTimestamp("", "14:30")).toThrowError(PoolEngineAdapterError)
      try {
        parseDepartureTimestamp("", "14:30")
      } catch (err: any) {
        expect(err.code).toBe("INVALID_DATE")
      }
    })

    it("throws INVALID_TIME when time is empty or missing", () => {
      expect(() => parseDepartureTimestamp("2026-10-30", "")).toThrowError(PoolEngineAdapterError)
      try {
        parseDepartureTimestamp("2026-10-30", "")
      } catch (err: any) {
        expect(err.code).toBe("INVALID_TIME")
      }
    })
  })

  describe("Waymate to Pool Engine Schema Mapping & Privacy Preservation", () => {
    it("maps host ride payload and strictly preserves privacy", () => {
      const waymateRide: Partial<Ride> & Record<string, any> = {
        from: "College of Engineering Trivandrum",
        to: "TVM Central Railway Station",
        date: "2026-10-30",
        departureTime: "08:30",
        totalSeats: 3,
        availableSeats: 3,
        vehicleType: "car",
        meetingPoint: "Campus Arch",
        // Personal data that MUST NOT leak to Pool Engine:
        hostName: "John Doe",
        hostPhone: "+919876543210",
        hostCollege: "CET",
        hostDepartment: "CSE",
        hostYear: "2026",
        genderPolicy: "any"
      }

      const input = mapWaymateRideToPoolEngineInput(waymateRide, "firebase_uid_host_123")

      // Validated fields forwarded to Pool Engine:
      expect(input.driver_id).toBe("firebase_uid_host_123")
      expect(input.origin.latitude).toBeCloseTo(8.5469, 3)
      expect(input.origin.longitude).toBeCloseTo(76.9054, 3)
      expect(input.destination.latitude).toBeCloseTo(8.4875, 3)
      expect(input.destination.longitude).toBeCloseTo(76.9525, 3)
      expect(input.available_seats).toBe(3)
      expect(input.max_detour_seconds).toBe(900)
      expect(input.vehicle_id).toBe("veh_car")

      // Privacy verification: Personal fields MUST be stripped
      const rawInput = input as Record<string, any>
      expect(rawInput.hostName).toBeUndefined()
      expect(rawInput.hostPhone).toBeUndefined()
      expect(rawInput.hostCollege).toBeUndefined()
      expect(rawInput.hostDepartment).toBeUndefined()
      expect(rawInput.hostYear).toBeUndefined()
      expect(rawInput.genderPolicy).toBeUndefined()
      expect(rawInput.meetingPoint).toBeUndefined()
    })

    it("rejects missing driver UID", () => {
      const waymateRide: Partial<Ride> = {
        from: "College of Engineering Trivandrum",
        to: "TVM Central Railway Station",
        date: "2026-10-30",
        departureTime: "08:30"
      }

      expect(() => mapWaymateRideToPoolEngineInput(waymateRide, "")).toThrowError(PoolEngineAdapterError)
    })

    it("rejects seat capacity less than 1 or greater than 50", () => {
      const waymateRideZero: Partial<Ride> = {
        from: "College of Engineering Trivandrum",
        to: "TVM Central Railway Station",
        date: "2026-10-30",
        departureTime: "08:30",
        availableSeats: 0
      }
      expect(() => mapWaymateRideToPoolEngineInput(waymateRideZero, "uid_1")).toThrowError(PoolEngineAdapterError)

      const waymateRideTooLarge: Partial<Ride> = {
        ...waymateRideZero,
        availableSeats: 99
      }
      expect(() => mapWaymateRideToPoolEngineInput(waymateRideTooLarge, "uid_1")).toThrowError(PoolEngineAdapterError)
    })
  })

  describe("Pool Engine HostRideDTO to Waymate Ride Mapping", () => {
    it("maps HostRideDTO back into Waymate Ride domain model", () => {
      const dto: HostRideDTO = {
        ride_id: "ride_pe_999",
        driver_id: "drv_firebase_123",
        vehicle_id: "veh_bike",
        origin: { latitude: 8.5475, longitude: 76.9048 },
        destination: { latitude: 8.4900, longitude: 76.9530 },
        scheduled_departure_time: 1770000000,
        available_seats: 1,
        max_detour_seconds: 600,
        direct_duration_seconds: 900,
        direct_distance_meters: 10500,
        status: "SCHEDULED",
        stops: []
      }

      const ride = mapPoolEngineHostRideToWaymateRide(dto, {
        from: "CET Front Gate",
        to: "Central Station"
      })

      expect(ride.id).toBe("ride_pe_999")
      expect(ride.ownerId).toBe("drv_firebase_123")
      expect(ride.from).toBe("CET Front Gate")
      expect(ride.to).toBe("Central Station")
      expect(ride.availableSeats).toBe(1)
      expect(ride.status).toBe("active")
      expect(ride.vehicleType).toBe("bike")
    })
  })

  describe("Adapter Methods & Error Propagation", () => {
    it("calls client.createHostRide with mapped payload", async () => {
      const mockClient = {
        createHostRide: vi.fn().mockResolvedValue({
          ride_id: "pe_ride_123",
          driver_id: "uid_host"
        })
      } as unknown as PoolEngineClient

      const adapter = new PoolEngineAdapter(mockClient)
      const res = await adapter.registerHostRide({
        from: "College of Engineering Trivandrum",
        to: "TVM Central Railway Station",
        date: "2026-10-30",
        departureTime: "09:00",
        availableSeats: 2
      }, "uid_host")

      expect(res.ride_id).toBe("pe_ride_123")
      expect(mockClient.createHostRide).toHaveBeenCalledTimes(1)
    })

    it("returns null when getHostRideAsWaymateRide receives PoolEngineNotFoundError (404)", async () => {
      const mockClient = {
        getHostRide: vi.fn().mockRejectedValue(new PoolEngineNotFoundError("Ride not found"))
      } as unknown as PoolEngineClient

      const adapter = new PoolEngineAdapter(mockClient)
      const res = await adapter.getHostRideAsWaymateRide("ride_nonexistent")
      expect(res).toBeNull()
    })

    it("re-throws authentication errors loudly without swallowing", async () => {
      const mockClient = {
        getHostRide: vi.fn().mockRejectedValue(new PoolEngineAuthError("Token expired"))
      } as unknown as PoolEngineClient

      const adapter = new PoolEngineAdapter(mockClient)
      await expect(adapter.getHostRideAsWaymateRide("ride_unauth")).rejects.toBeInstanceOf(PoolEngineAuthError)
    })
  })
})
