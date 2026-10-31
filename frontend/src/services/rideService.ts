/**
 * TypeScript definitions & re-exports for rideService
 */

import { Timestamp } from "firebase/firestore"
import {
  createRideWithH3 as createRideWithH3Js,
  matchRidesWithH3 as matchRidesWithH3Js,
  findRidesBySmallestDistance as findRidesBySmallestDistanceJs,
  getRideById as getRideByIdJs,
  updateRideStatus as updateRideStatusJs
} from "./rideService.js"

export interface H3Location {
  name: string
  lat: number
  lng: number
  h3IndexRes8?: string
  pickupRadiusMeters?: number
  dropoffRadiusMeters?: number
}

export interface H3RideDocument {
  id?: string
  driverId: string
  driverName: string
  driverPhone?: string
  vehicleType: "bike" | "car" | "auto" | string
  availableSeats: number
  farePerSeat: number
  status: "OPEN" | "FULL" | "COMPLETED" | "CANCELLED" | "active"
  departureTime: Timestamp | Date | string
  source: H3Location
  destination: H3Location
  routeSummary?: {
    distanceKm: number
    durationMins: number
  }
  pickupRadiusMeters?: number
  dropoffRadiusMeters?: number
  pickupDistanceMeters?: number
  dropoffDistanceMeters?: number
  totalDistanceMeters?: number
  pickupDistanceFormatted?: string
  dropoffDistanceFormatted?: string
  totalDistanceFormatted?: string
  proximityBadge?: string
  isClosestMatch?: boolean
  sourceDistanceMeters?: number
  destDistanceMeters?: number
  totalDetourMeters?: number
  isH3Match?: boolean
  createdAt?: any
}

export interface SmallestDistanceQuery {
  riderSource?: {
    lat: number
    lng: number
  }
  source?: {
    lat: number
    lng: number
  }
  riderDestination?: {
    lat: number
    lng: number
  }
  destination?: {
    lat: number
    lng: number
  }
  maxDistanceMeters?: number
  pickupRadiusMeters?: number
  dropoffRadiusMeters?: number
  minSeats?: number
  vehicleType?: string
  userId?: string
  date?: string
  time?: string
  maxTimeDiffMinutes?: number
}

export const createRideWithH3 = createRideWithH3Js as (rideData: Partial<H3RideDocument>) => Promise<H3RideDocument>
export const createRideOffer = createRideWithH3
export const matchRidesWithH3 = matchRidesWithH3Js as (query: any) => Promise<H3RideDocument[]>
export const findRidesBySmallestDistance = findRidesBySmallestDistanceJs as (query: SmallestDistanceQuery) => Promise<H3RideDocument[]>
export const findMatchingRides = findRidesBySmallestDistance
export const getRideById = getRideByIdJs as (rideId: string) => Promise<H3RideDocument | null>
export const updateRideStatus = updateRideStatusJs as (rideId: string, status: "OPEN" | "FULL" | "COMPLETED" | "CANCELLED") => Promise<void>

export default {
  createRideWithH3,
  createRideOffer,
  matchRidesWithH3,
  findRidesBySmallestDistance,
  findMatchingRides,
  getRideById,
  updateRideStatus
}
