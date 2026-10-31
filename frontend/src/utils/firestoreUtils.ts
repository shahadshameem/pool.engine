/**
 * Firestore Utilities
 *
 * Safe helpers for preparing and sanitizing documents before writing to Firestore.
 */

/**
 * Recursively removes any property with value `undefined` from an object or array.
 * Preserves Firestore FieldValue sentinels (serverTimestamp, deleteField, etc.),
 * Timestamps, Dates, and primitive values.
 */
export function removeUndefined<T>(value: T): T {
  if (value === null || value === undefined || typeof value !== "object") {
    return value
  }

  // Preserve Dates
  if (value instanceof Date) {
    return value
  }

  // Preserve Firestore Timestamps (toMillis / toDate) and FieldValues (_methodName)
  if (
    typeof (value as any).toMillis === "function" ||
    typeof (value as any).toDate === "function" ||
    (value as any)._methodName !== undefined
  ) {
    return value
  }

  // Handle Arrays
  if (Array.isArray(value)) {
    return value.map(item => removeUndefined(item)) as unknown as T
  }

  // Handle Plain Objects
  const cleaned: Record<string, any> = {}
  for (const [k, v] of Object.entries(value)) {
    if (v !== undefined) {
      cleaned[k] = removeUndefined(v)
    }
  }
  return cleaned as T
}
