/**
 * Automatic Ride-Pool Matching Engine Configuration & Utility Constants.
 */

export const MAX_TIME_DIFF_MINUTES = 10;

export const RIDE_MATCH_CONFIG = {
  /** Maximum straight-line distance (in km) between pickup points for a ride-pool match. */
  MAX_ORIGIN_DISTANCE_KM: 3.0,

  /** Maximum straight-line distance (in km) between dropoff points for a ride-pool match. */
  MAX_DESTINATION_DISTANCE_KM: 3.0,

  /** Maximum time difference (in minutes) between ride departure times for a ride search or pool match. */
  MAX_DEPARTURE_TIME_DIFFERENCE_MINUTES: 10,

  /** Maximum time difference (in minutes) allowed for search results filtering. */
  MAX_TIME_DIFF_MINUTES: 10
} as const;

/**
 * Computes the straight-line distance in kilometers between two geographic coordinates
 * using the Haversine formula.
 */
export function calculateHaversineDistance(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R = 6371; // Earth's radius in kilometers
  const dLat = (lat2 - lat1) * (Math.PI / 180);
  const dLon = (lon2 - lon1) * (Math.PI / 180);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * (Math.PI / 180)) *
      Math.cos(lat2 * (Math.PI / 180)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * Parses a time string (e.g., "14:30", "02:30 PM", "9:00", "09:00 AM") into total minutes from midnight (0..1439).
 */
export function parseTimeToMinutes(timeStr?: string): number {
  if (!timeStr) return 0;
  const trimmed = timeStr.trim();

  // Case 1: Time with AM/PM (e.g. "09:00 PM", "9:00:00 AM")
  const amPmMatch = trimmed.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM|am|pm)$/i);
  if (amPmMatch) {
    let hours = parseInt(amPmMatch[1], 10);
    const minutes = parseInt(amPmMatch[2], 10);
    const period = amPmMatch[3].toUpperCase();

    if (period === "PM" && hours < 12) hours += 12;
    if (period === "AM" && hours === 12) hours = 0;
    return hours * 60 + minutes;
  }

  // Case 2: 24-hour time "HH:mm" or "HH:mm:ss"
  const match24 = trimmed.match(/^(\d{1,2}):(\d{2})(?::\d{2})?$/);
  if (match24) {
    const hours = parseInt(match24[1], 10);
    const minutes = parseInt(match24[2], 10);
    return hours * 60 + minutes;
  }

  return 0;
}

/**
 * Computes the absolute difference in minutes between two departure time strings.
 */
export function calculateTimeDifferenceMinutes(time1: string, time2: string): number {
  const minutes1 = parseTimeToMinutes(time1);
  const minutes2 = parseTimeToMinutes(time2);
  const diff = Math.abs(minutes1 - minutes2);
  return Math.min(diff, 1440 - diff);
}

/**
 * Computes a human-readable badge label for departure time proximity between search/target time and ride departure time.
 */
export function getTimeProximityBadgeLabel(searchTime?: string, rideTime?: string): string {
  if (!searchTime || !rideTime) {
    return "Available ride";
  }
  const diff = calculateTimeDifferenceMinutes(searchTime, rideTime);
  if (diff === 0) {
    return "Same departure time";
  }
  return `±${diff} min`;
}

/**
 * Checks if a ride's departure date and time has already passed relative to current time,
 * or if its status is 'completed' or 'cancelled'.
 */
export function isRideExpired(
  dateOrRide?: string | { date?: string; departureTime?: string; time?: string; status?: string },
  timeStrParam?: string,
  statusParam?: string
): boolean {
  let dateStr: string | undefined;
  let timeStr: string | undefined;
  let status: string | undefined;

  if (dateOrRide && typeof dateOrRide === "object") {
    dateStr = dateOrRide.date;
    timeStr = dateOrRide.departureTime || (dateOrRide as any).time;
    status = dateOrRide.status;
  } else {
    dateStr = dateOrRide;
    timeStr = timeStrParam;
    status = statusParam;
  }

  if (status === "completed" || status === "cancelled") return true;
  if (!dateStr) return false;

  try {
    let year: number;
    let month: number;
    let day: number;

    const isoMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const ddmmyyyyMatch = dateStr.match(/^(\d{2})-(\d{2})-(\d{4})/);

    if (isoMatch) {
      year = parseInt(isoMatch[1], 10);
      month = parseInt(isoMatch[2], 10) - 1;
      day = parseInt(isoMatch[3], 10);
    } else if (ddmmyyyyMatch) {
      day = parseInt(ddmmyyyyMatch[1], 10);
      month = parseInt(ddmmyyyyMatch[2], 10) - 1;
      year = parseInt(ddmmyyyyMatch[3], 10);
    } else {
      const parsedDate = new Date(dateStr);
      if (isNaN(parsedDate.getTime())) return false;
      year = parsedDate.getFullYear();
      month = parsedDate.getMonth();
      day = parsedDate.getDate();
    }

    const departureMinutes = parseTimeToMinutes(timeStr);
    const hours = Math.floor(departureMinutes / 60);
    const minutes = departureMinutes % 60;

    const rideDateTime = new Date(year, month, day, hours, minutes, 0, 0);
    const now = new Date();

    // Started (in progress) rides: local campus trips typically complete within 30-45 mins.
    // Automatically transition to completed 45 minutes after departure time.
    if (status === "started") {
      const startedTripDurationMs = 45 * 60 * 1000;
      return now.getTime() >= (rideDateTime.getTime() + startedTripDurationMs);
    }

    // Un-started active/full rides expire immediately upon scheduled departure time
    return now.getTime() >= rideDateTime.getTime();
  } catch (e) {
    return false;
  }
}

/**
 * Checks if a ride is past its participant grace period (e.g. 60 mins past departure time),
 * meaning the trip has concluded even for participants who were actively coordinating.
 */
export function isRidePastGracePeriod(
  dateOrRide?: string | { date?: string; departureTime?: string; time?: string; status?: string },
  timeStrParam?: string,
  statusParam?: string,
  graceMinutes = 60
): boolean {
  let dateStr: string | undefined;
  let timeStr: string | undefined;
  let status: string | undefined;

  if (dateOrRide && typeof dateOrRide === "object") {
    dateStr = dateOrRide.date;
    timeStr = dateOrRide.departureTime || (dateOrRide as any).time;
    status = dateOrRide.status;
  } else {
    dateStr = dateOrRide;
    timeStr = timeStrParam;
    status = statusParam;
  }

  if (status === "completed" || status === "cancelled") return true;
  if (!dateStr) return false;

  try {
    let year: number;
    let month: number;
    let day: number;

    const isoMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const ddmmyyyyMatch = dateStr.match(/^(\d{2})-(\d{2})-(\d{4})/);

    if (isoMatch) {
      year = parseInt(isoMatch[1], 10);
      month = parseInt(isoMatch[2], 10) - 1;
      day = parseInt(isoMatch[3], 10);
    } else if (ddmmyyyyMatch) {
      day = parseInt(ddmmyyyyMatch[1], 10);
      month = parseInt(ddmmyyyyMatch[2], 10) - 1;
      year = parseInt(ddmmyyyyMatch[3], 10);
    } else {
      const parsedDate = new Date(dateStr);
      if (isNaN(parsedDate.getTime())) return false;
      year = parsedDate.getFullYear();
      month = parsedDate.getMonth();
      day = parsedDate.getDate();
    }

    const departureMinutes = parseTimeToMinutes(timeStr);
    const hours = Math.floor(departureMinutes / 60);
    const minutes = departureMinutes % 60;

    const rideDateTime = new Date(year, month, day, hours, minutes, 0, 0);
    const now = new Date();

    const graceMs = (status === "started" ? 45 : graceMinutes) * 60 * 1000;
    return now.getTime() >= (rideDateTime.getTime() + graceMs);
  } catch (e) {
    return false;
  }
}
