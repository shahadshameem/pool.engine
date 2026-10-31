import { useState, useEffect } from "react"
import { adminService, type AdminPlace } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { MaterialIcon } from "../../components/common/MaterialIcon"

export function AdminPlacesPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const [places, setPlaces] = useState<AdminPlace[]>([])
  const [loading, setLoading] = useState(true)
  const [locationName, setLocationName] = useState("")
  const [searchQuery, setSearchQuery] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [toastMessage, setToastMessage] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    async function loadPlaces() {
      setLoading(true)
      try {
        const data = await adminService.getPlaces()
        if (mounted) setPlaces(data)
      } catch (err) {
        console.error("Error loading places:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }
    loadPlaces()
    return () => { mounted = false }
  }, [refreshTrigger])

  const showToast = (msg: string) => {
    setToastMessage(msg)
    setTimeout(() => setToastMessage(null), 3000)
  }

  const handleAddPlace = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = locationName.trim()
    if (!name) return

    setSubmitting(true)
    try {
      await adminService.addPlace(name, adminUid, adminEmail)
      setLocationName("")
      showToast(`Added location: "${name}"`)
      triggerRefresh()
    } catch (err) {
      console.error("Error adding place:", err)
      showToast("Failed to add location")
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeletePlace = async (place: AdminPlace) => {
    if (!window.confirm(`Delete "${place.name}" from WayMate places?`)) return

    setDeletingId(place.id)
    try {
      await adminService.deletePlace(place.id, place.name, adminUid, adminEmail)
      showToast(`Deleted "${place.name}"`)
      triggerRefresh()
    } catch (err) {
      console.error("Error deleting place:", err)
      showToast("Failed to delete location")
    } finally {
      setDeletingId(null)
    }
  }

  const filteredPlaces = places.filter(p =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase().trim())
  )

  return (
    <div className="space-y-6 max-w-4xl mx-auto animate-in fade-in duration-200">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-16 right-4 z-50 bg-black text-white text-xs px-4 py-3 rounded-2xl shadow-xl border border-white/10 flex items-center gap-2 animate-in fade-in slide-in-from-top-4">
          <MaterialIcon name="check_circle" className="text-base text-[#C5FF00]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header */}
      <div className="bg-white p-5 sm:p-6 rounded-2xl sm:rounded-3xl border border-black/8 shadow-xs">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-[#C5FF00]" />
          <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">Campus Transit Network</span>
        </div>
        <h1 className="text-xl sm:text-2xl font-black text-gray-950 tracking-tight mt-1">WayMate Places</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Add pickup locations, campus gates, or transit spots. Students can select these locations when searching or offering rides.
        </p>
      </div>

      {/* Add Location Form (Single Input Box) */}
      <form
        onSubmit={handleAddPlace}
        className="bg-white p-4 sm:p-5 rounded-2xl sm:rounded-3xl border border-black/8 shadow-sm flex flex-col sm:flex-row gap-3"
      >
        <div className="relative flex-1">
          <MaterialIcon name="place" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
          <input
            type="text"
            required
            value={locationName}
            onChange={e => setLocationName(e.target.value)}
            placeholder="Enter location name (e.g. CET Back Gate, Barton Hill, Technopark...)"
            disabled={submitting}
            className="w-full pl-10 pr-4 py-3 text-xs sm:text-sm bg-gray-50 rounded-xl sm:rounded-2xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black placeholder-gray-400 font-medium"
          />
        </div>

        <button
          type="submit"
          disabled={!locationName.trim() || submitting}
          className="px-6 py-3 rounded-xl sm:rounded-2xl bg-black hover:bg-neutral-800 disabled:opacity-40 text-[#C5FF00] font-bold text-xs sm:text-sm flex items-center justify-center gap-2 shadow-sm transition-all active:scale-[0.98] cursor-pointer shrink-0"
        >
          <MaterialIcon name="add" className="text-lg" />
          <span>{submitting ? "Adding..." : "Add Location"}</span>
        </button>
      </form>

      {/* Locations List Section */}
      <div className="bg-white rounded-2xl sm:rounded-3xl border border-black/8 shadow-sm overflow-hidden">
        {/* Search & Header Bar */}
        <div className="p-4 sm:p-5 border-b border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-gray-900">Registered Locations</h2>
            <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 text-xs font-bold">
              {places.length}
            </span>
          </div>

          {places.length > 3 && (
            <div className="relative w-full sm:w-64">
              <MaterialIcon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-base" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search locations..."
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black"
              />
            </div>
          )}
        </div>

        {/* Content */}
        {loading ? (
          <div className="p-12 text-center text-xs text-gray-500">
            <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
            Loading locations...
          </div>
        ) : filteredPlaces.length === 0 ? (
          <div className="p-12 text-center text-xs text-gray-500 space-y-2">
            <MaterialIcon name="location_off" className="text-4xl text-gray-300" />
            <p className="font-bold text-gray-700 text-sm">
              {searchQuery ? "No locations matched your search" : "No locations added yet"}
            </p>
            <p className="text-gray-400">
              {searchQuery ? "Try searching with a different term" : "Add a location above to get started"}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {filteredPlaces.map(place => (
              <div
                key={place.id}
                className="p-4 sm:p-4.5 flex items-center justify-between gap-3 hover:bg-gray-50/60 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-gray-100 text-gray-700 flex items-center justify-center shrink-0">
                    <MaterialIcon name="place" className="text-lg text-gray-900" />
                  </div>
                  <span className="font-bold text-gray-900 text-xs sm:text-sm truncate">
                    {place.name}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={() => handleDeletePlace(place)}
                  disabled={deletingId === place.id}
                  title="Delete Location"
                  className="p-2 sm:px-3 sm:py-1.5 rounded-xl text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-40 transition-colors flex items-center gap-1 cursor-pointer shrink-0"
                >
                  <MaterialIcon name="delete" className="text-lg" />
                  <span className="hidden sm:inline text-xs font-semibold">Delete</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
