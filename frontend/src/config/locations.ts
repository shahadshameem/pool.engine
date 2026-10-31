import type { LocationValue } from "../components/location/LocationPicker";
import { CAMPUS_ZONES } from "./campusZones";

export interface FixedLocation extends LocationValue {
  id: string;
  name: string;
  matchedZoneId?: string;
  rawGps?: { lat: number; lng: number; accuracy: number };
  isLowAccuracy?: boolean;
  accuracyMeters?: number;
}

const cetZoneConfig = CAMPUS_ZONES.find(z => z.id === "cet-front-gate" || z.id === "cet");

export const FIXED_LOCATIONS: FixedLocation[] = [
  {
    id: "cet-front-gate",
    name: "College of Engineering Trivandrum",
    address: "College of Engineering Trivandrum (CET) Front Gate, Sreekaryam, Thiruvananthapuram",
    latitude: (cetZoneConfig && !isNaN(cetZoneConfig.lat)) ? cetZoneConfig.lat : 8.546938,
    longitude: (cetZoneConfig && !isNaN(cetZoneConfig.lng)) ? cetZoneConfig.lng : 76.905484,
    matchedZoneId: "cet-front-gate"
  },
  {
    id: "tvm-central",
    name: "TVM Central Railway Station",
    address: "TVM Central Railway Station",
    latitude: 8.4875,
    longitude: 76.9525
  },
  {
    id: "kochuveli",
    name: "Kochuveli Railway Station",
    address: "Kochuveli Railway Station",
    latitude: 8.5288,
    longitude: 76.8970
  },
  {
    id: "icc",
    name: "ICC",
    address: "ICC",
    latitude: 8.5581,
    longitude: 76.8816
  }
];

export function resolveFixedLocation(nameOrAddr?: string | any, locDataInput?: any, isOrigin = true): FixedLocation {
  const actualLocData = (nameOrAddr && typeof nameOrAddr === "object") ? { ...nameOrAddr, ...locDataInput } : locDataInput
  const rawString = typeof nameOrAddr === "string" ? nameOrAddr : (actualLocData?.address || actualLocData?.name || "")
  const raw = (rawString || "").trim()
  const clean = raw.toLowerCase()
  const fallbackName = raw || (isOrigin ? "Origin" : "Destination")

  const explicitLat = typeof actualLocData?.latitude === "number" ? actualLocData.latitude : (typeof actualLocData?.lat === "number" ? actualLocData.lat : undefined)
  const explicitLng = typeof actualLocData?.longitude === "number" ? actualLocData.longitude : (typeof actualLocData?.lng === "number" ? actualLocData.lng : undefined)

  // 1. If explicit GPS/numeric coordinates already exist, preserve them strictly! Never overwrite with a centroid.
  if (typeof explicitLat === "number" && typeof explicitLng === "number" && !isNaN(explicitLat) && !isNaN(explicitLng)) {
    return {
      id: actualLocData.id || ((isOrigin ? "from-" : "to-") + (clean.replace(/[^a-z0-9]/g, "-") || "loc")),
      name: raw || actualLocData.name || fallbackName,
      address: actualLocData.address || raw || fallbackName,
      latitude: explicitLat,
      longitude: explicitLng,
      matchedZoneId: actualLocData.matchedZoneId,
      rawGps: actualLocData.rawGps,
      isLowAccuracy: actualLocData.isLowAccuracy,
      accuracyMeters: actualLocData.accuracyMeters
    }
  }

  // 2. Only if coordinates are missing, resolve named presets from FIXED_LOCATIONS or campus zones
  if (clean) {
    const isCetMatch = (
      clean === "cet" ||
      clean.includes("college of engineering") ||
      clean.includes("cet main gate") ||
      clean.includes("cet front gate") ||
      clean.includes("front gate") ||
      clean.includes("cet campus")
    )
    if (isCetMatch) {
      const cetZone = CAMPUS_ZONES.find(z => z.id === "cet-front-gate" || z.id === "cet")
      const cetLat = (cetZone && !isNaN(cetZone.lat)) ? cetZone.lat : 8.546938
      const cetLng = (cetZone && !isNaN(cetZone.lng)) ? cetZone.lng : 76.905484
      return {
        id: "cet-front-gate",
        name: cetZone?.name || "College of Engineering Trivandrum",
        address: cetZone?.address || "College of Engineering Trivandrum (CET) Front Gate, Sreekaryam, Thiruvananthapuram",
        latitude: cetLat,
        longitude: cetLng,
        matchedZoneId: "cet-front-gate"
      }
    }

    const directMatch = FIXED_LOCATIONS.find((l) => {
      const lName = l.name.toLowerCase()
      const lAddr = l.address.toLowerCase()
      const lId = l.id.toLowerCase()
      return (
        lName === clean ||
        lAddr === clean ||
        lId === clean ||
        (clean.includes("central") && lId === "tvm-central") ||
        (clean.includes("kochuveli") && lId === "kochuveli") ||
        (clean.includes("icc") && lId === "icc") ||
        (clean.length > 2 && (lName.includes(clean) || clean.includes(lName)))
      )
    })
    if (directMatch) return directMatch
  }

  return {
    id: (isOrigin ? "from-" : "to-") + (clean.replace(/[^a-z0-9]/g, "-") || "loc"),
    name: fallbackName,
    address: actualLocData?.address || raw || fallbackName,
    latitude: explicitLat ?? (isOrigin ? 8.5458 : 8.4875),
    longitude: explicitLng ?? (isOrigin ? 76.9032 : 76.9525),
  }
}