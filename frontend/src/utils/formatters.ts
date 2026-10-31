/**
 * Shared date and time formatting utilities for WayMate.
 */

/**
 * Formats any departure time string into a canonical 12-hour format with AM/PM (e.g. "02:24 PM").
 * Handles 24h format ("16:13", "04:13"), 12h format ("4:13 PM", "04:13 PM"), or ISO strings.
 */
export function formatTime12h(timeStr?: string): string {
  if (!timeStr) return ""

  const trimmed = timeStr.trim()

  // Case 1: Already contains AM/PM
  if (/am|pm/i.test(trimmed)) {
    const match = trimmed.match(/^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)$/i)
    if (match) {
      let hours = parseInt(match[1], 10)
      const minutes = match[2]
      const period = match[3].toUpperCase()
      if (hours === 0) hours = 12
      const formattedHours = hours < 10 ? `0${hours}` : `${hours}`
      return `${formattedHours}:${minutes} ${period}`
    }
    return trimmed
  }

  // Case 2: 24-hour format "HH:mm" or "H:mm"
  const match24 = trimmed.match(/^(\d{1,2}):(\d{2})$/)
  if (match24) {
    let hours = parseInt(match24[1], 10)
    const minutes = match24[2]
    const period = hours >= 12 ? "PM" : "AM"
    hours = hours % 12
    if (hours === 0) hours = 12
    const formattedHours = hours < 10 ? `0${hours}` : `${hours}`
    return `${formattedHours}:${minutes} ${period}`
  }

  return trimmed
}

/**
 * Returns local YYYY-MM-DD string without UTC timezone offset shift.
 */
export function getLocalDateString(d: Date = new Date()): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * Formats a date string ("YYYY-MM-DD" or ISO) into "Thu, 25 Sep 2026" format.
 */
export function formatDate(dateStr?: string): string {
  if (!dateStr) return ""

  // If already formatted like "Thu, 25 Sep 2026"
  if (dateStr.includes(",") && /[a-zA-Z]/.test(dateStr)) {
    return dateStr
  }

  try {
    const parts = dateStr.split("T")[0].split("-")
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10)
      const month = parseInt(parts[1], 10) - 1
      const day = parseInt(parts[2], 10)

      const d = new Date(year, month, day)
      if (!isNaN(d.getTime())) {
        const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        const dayOfWeek = days[d.getDay()]
        const monthName = months[d.getMonth()]
        const formattedDay = day < 10 ? `0${day}` : `${day}`

        return `${dayOfWeek}, ${formattedDay} ${monthName} ${year}`
      }
    }
  } catch (e) {}

  return dateStr
}

/**
 * Formats a date string ("YYYY-MM-DD" or ISO) into "DD-MM-YYYY" format (e.g. "26-09-2026").
 */
export function formatDateDDMMYYYY(dateStr?: string): string {
  if (!dateStr) return ""

  try {
    const cleanDate = dateStr.split("T")[0]
    const parts = cleanDate.split("-")
    if (parts.length === 3 && parts[0].length === 4) {
      const year = parts[0]
      const month = parts[1].padStart(2, "0")
      const day = parts[2].padStart(2, "0")
      return `${day}-${month}-${year}`
    }
  } catch (e) {}

  return dateStr
}

/**
 * Formats a date string ("YYYY-MM-DD" or ISO) into a clean, concise display format (e.g. "28 Sep 2026").
 */
export function formatDateShort(dateStr?: string): string {
  if (!dateStr) return ""
  try {
    const cleanDate = dateStr.split("T")[0]
    const parts = cleanDate.split("-")
    if (parts.length === 3 && parts[0].length === 4) {
      const year = parseInt(parts[0], 10)
      const month = parseInt(parts[1], 10) - 1
      const day = parseInt(parts[2], 10)
      const d = new Date(year, month, day)
      if (!isNaN(d.getTime())) {
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        const formattedDay = day < 10 ? `0${day}` : `${day}`
        return `${formattedDay} ${months[month]} ${year}`
      }
    }
  } catch (e) {}
  return dateStr
}

/**
 * Normalizes phone numbers for WhatsApp wa.me links and tel: links (digits only with country code).
 * Strips non-digits, removes leading zero if 11 digits, and prepends country code "91" (India) if a 10-digit number is provided.
 */
export function normalizePhoneForWhatsApp(phone?: string): string {
  if (!phone) return ""
  let digits = phone.replace(/\D/g, "")
  if (digits.length === 13 && digits.startsWith("910")) {
    digits = "91" + digits.slice(3)
  }
  if (digits.length === 11 && digits.startsWith("0")) {
    digits = digits.slice(1)
  }
  if (digits.length === 10) {
    digits = "91" + digits
  }
  return digits
}

export function normalizePhoneNumber(phone?: string): string {
  return normalizePhoneForWhatsApp(phone)
}

/**
 * Generates a normalized WhatsApp chat link with optional pre-filled message.
 */
export function buildWhatsAppLink(phoneNumber: string, message?: string): string {
  const digits = normalizePhoneForWhatsApp(phoneNumber)
  if (!digits) return ""
  let url = `https://wa.me/${digits}`
  if (message) {
    url += `?text=${encodeURIComponent(message)}`
  }
  return url
}

/**
 * Formats date and time into human readable relative format e.g. "Today, 11:00 AM" or "Tomorrow, 09:00 AM".
 * Calculates local date components at render time to prevent UTC shift (ISO string) & stale midnight calculations.
 */
export function formatRideDateTime(dateStr?: string, timeStr?: string): string {
  if (!dateStr) return formatTime12h(timeStr)

  const now = new Date()
  const todayDate = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const tomorrowDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)

  let rideYear: number, rideMonth: number, rideDay: number

  const isoMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/)
  const ddmmyyyyMatch = dateStr.match(/^(\d{2})-(\d{2})-(\d{4})/)

  if (isoMatch) {
    rideYear = parseInt(isoMatch[1], 10)
    rideMonth = parseInt(isoMatch[2], 10) - 1
    rideDay = parseInt(isoMatch[3], 10)
  } else if (ddmmyyyyMatch) {
    rideDay = parseInt(ddmmyyyyMatch[1], 10)
    rideMonth = parseInt(ddmmyyyyMatch[2], 10) - 1
    rideYear = parseInt(ddmmyyyyMatch[3], 10)
  } else {
    const parsed = new Date(dateStr)
    if (isNaN(parsed.getTime())) return dateStr
    rideYear = parsed.getFullYear()
    rideMonth = parsed.getMonth()
    rideDay = parsed.getDate()
  }

  const rideDate = new Date(rideYear, rideMonth, rideDay)

  let dayPart: string
  if (rideDate.getTime() === todayDate.getTime()) {
    dayPart = "Today"
  } else if (rideDate.getTime() === tomorrowDate.getTime()) {
    dayPart = "Tomorrow"
  } else {
    dayPart = formatDate(dateStr)
  }

  const formattedTime = formatTime12h(timeStr)
  return formattedTime ? `${dayPart}, ${formattedTime}` : dayPart
}

/**
 * Normalizes a full college name to its standard short form code (e.g. "College of Engineering Trivandrum (CET)" -> "CET").
 */
export function getCollegeShortName(college?: string): string {
  if (!college) return "CET"
  const c = college.trim()
  if (!c) return "CET"
  if (c.includes("College of Engineering Trivandrum") || c.includes("CET")) return "CET"
  const parenMatch = c.match(/\(([^)]+)\)/)
  if (parenMatch && parenMatch[1] && parenMatch[1].length <= 6) {
    return parenMatch[1].trim().toUpperCase()
  }
  return c
}

/**
 * Normalizes a full department/branch name to its standard short form code (e.g. "ECE", "CSE", "EEE", "ME").
 */
export function getDepartmentShortName(department?: string): string {
  if (!department) return ""
  const d = department.trim()
  if (!d) return ""

  // Extract abbreviation in parentheses if present, e.g. "Electronics & Communication (ECE)" -> "ECE"
  const parenMatch = d.match(/\(([^)]+)\)/)
  if (parenMatch && parenMatch[1]) {
    const candidate = parenMatch[1].trim()
    if (candidate.length <= 6) return candidate.toUpperCase()
  }

  const upper = d.toUpperCase()

  // Common direct mappings
  if (/electronics\s*(&|and|\+)?\s*communication/i.test(d) || /\bece\b/i.test(d)) return "ECE"
  if (/computer\s*science/i.test(d) || /\bcse\b/i.test(d)) return "CSE"
  if (/electrical\s*(&|and|\+)?\s*electronics/i.test(d) || /\beee\b/i.test(d)) return "EEE"
  if (/applied\s*electronics/i.test(d) || /\baei\b/i.test(d)) return "AEI"
  if (/mechanical/i.test(d) || /\bme\b/i.test(d)) return "ME"
  if (/civil/i.test(d) || /\bce\b/i.test(d)) return "CE"
  if (/industrial/i.test(d) || /\bie\b/i.test(d)) return "IE"
  if (/architecture/i.test(d) || /b\.?arch/i.test(d) || /\barch\b/i.test(d)) return "ARCH"
  if (/computer\s*applications/i.test(d) || /\bmca\b/i.test(d)) return "MCA"
  if (/business\s*administration/i.test(d) || /\bmba\b/i.test(d)) return "MBA"
  if (/information\s*technology/i.test(d) || /\bit\b/i.test(d)) return "IT"
  if (/artificial\s*intelligence/i.test(d) || /\baids\b/i.test(d) || /ai\s*(&|and|\+)\s*ds/i.test(d)) return "AI&DS"
  if (/biotechnology/i.test(d) || /\bbt\b/i.test(d)) return "BT"
  if (/chemical/i.test(d) || /\bche\b/i.test(d)) return "CHE"

  // If already a short code (2-5 uppercase letters)
  if (/^[A-Z]{2,5}$/.test(upper)) {
    return upper
  }

  // If department name is short (<= 6 chars), return uppercase
  if (d.length <= 6) {
    return upper
  }

  // Fallback: build initials if multi-word (e.g. "Information Science" -> "IS")
  const words = d.split(/\s+/).filter((w) => !/^(and|&|of|in|the|dept|department)$/i.test(w))
  if (words.length >= 2 && words.length <= 4) {
    return words.map((w) => w.charAt(0).toUpperCase()).join("")
  }

  return d
}

/**
 * Formats a student's branch/department and year into a clean subtitle:
 * e.g. "ECE • 4th Year" or "CSE • 2nd Year".
 * Normalizes full department strings to short form (e.g. "Electronics & Communication Engineering" -> "ECE").
 * Normalizes numeric years (e.g. "1" -> "1st Year", "4" -> "4th Year").
 */
export function formatBranchYear(department?: string, year?: string, fallback: string = "CET"): string {
  const shortDept = getDepartmentShortName(department)
  let normYear = year ? year.trim() : ""

  if (normYear === "1") normYear = "1st Year"
  else if (normYear === "2") normYear = "2nd Year"
  else if (normYear === "3") normYear = "3rd Year"
  else if (normYear === "4") normYear = "4th Year"
  else if (normYear === "5") normYear = "5th Year"

  const parts = [shortDept, normYear].filter(Boolean)
  return parts.length > 0 ? parts.join(" • ") : fallback
}

/**
 * Formats a raw genderPolicy string ("female_only", "female", "any") into a clean display label.
 * Returns "Female Riders Only" for female restriction, or "Any Gender" otherwise.
 */
export function formatGenderPolicyLabel(policy?: string): string {
  if (!policy) return "Any Gender"
  const normalized = policy.toLowerCase().trim()
  if (normalized === "female_only" || normalized === "female") return "Female Riders Only"
  return "Any Gender"
}

/**
 * Cleans location display names by removing wrappers like "My Location (Address)"
 * and extracting just the clean location address or name.
 */
export function cleanLocationDisplayName(name?: string): string {
  if (!name) return ""
  const trimmed = name.trim()
  // Match "My Location (Actual Address)" or "Current Location (Actual Address)"
  const match = trimmed.match(/^(?:My Location|Current Location)\s*\((.+)\)$/i)
  if (match && match[1]) {
    return match[1].trim()
  }
  // Match "My Location - Actual Address" or "My Location: Actual Address"
  if (/^(?:My Location|Current Location)\s*[-:–]\s*/i.test(trimmed)) {
    return trimmed.replace(/^(?:My Location|Current Location)\s*[-:–]\s*/i, "").trim()
  }
  return trimmed
}
