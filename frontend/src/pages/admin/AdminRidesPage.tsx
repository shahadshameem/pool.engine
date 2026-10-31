import { useEffect, useState, useMemo } from "react"
import { adminService, canForceCancel, type AdminRide } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { RideDetailModal } from "../../components/admin/RideDetailModal"
import { MaterialIcon } from "../../components/common/MaterialIcon"
import { useToast } from "../../components/feedback/ToastContext"

export function AdminRidesPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const { showToast } = useToast()
  const [rides, setRides] = useState<AdminRide[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRide, setSelectedRide] = useState<AdminRide | null>(null)

  // Filters
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [genderFilter, setGenderFilter] = useState("all")
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    async function loadRides() {
      setLoading(true)
      try {
        const data = await adminService.getRides()
        if (mounted) setRides(data)
      } catch (err) {
        console.error("Failed to load rides:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadRides()
    return () => { mounted = false }
  }, [refreshTrigger])

  const filteredRides = useMemo(() => {
    return rides.filter(ride => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch = !q || (
        ride.from.toLowerCase().includes(q) ||
        ride.to.toLowerCase().includes(q) ||
        ride.hostName.toLowerCase().includes(q)
      )

      const matchesStatus = statusFilter === "all" || ride.status === statusFilter
      const matchesGender = genderFilter === "all" || ride.genderPolicy === genderFilter

      return matchesSearch && matchesStatus && matchesGender
    })
  }, [rides, searchQuery, statusFilter, genderFilter])

  const handleCancelRide = async (rideId: string, reason: string): Promise<boolean> => {
    try {
      const success = await adminService.cancelRideAsAdmin(rideId, reason, adminUid, adminEmail)
      if (success) {
        setRides(prev => prev.map(r => r.id === rideId ? { ...r, status: "cancelled" } : r))
        if (selectedRide?.id === rideId) {
          setSelectedRide(prev => prev ? { ...prev, status: "cancelled" } : null)
        }
        setActionFeedback(`Ride #${rideId} was force-cancelled by admin.`)
        showToast(`Ride #${rideId} was force-cancelled successfully.`, "success")
        setTimeout(() => setActionFeedback(null), 3000)
        triggerRefresh()
        return true
      } else {
        showToast("Failed to force-cancel ride.", "error")
        return false
      }
    } catch (err: any) {
      console.error("Failed to cancel ride:", err)
      showToast(err?.message || "Failed to force-cancel ride.", "error")
      return false
    }
  }

  const handleMarkCompleted = async (rideId: string): Promise<boolean> => {
    try {
      const success = await adminService.markRideCompleted(rideId, adminUid, adminEmail)
      if (success) {
        setRides(prev => prev.map(r => r.id === rideId ? { ...r, status: "completed" } : r))
        if (selectedRide?.id === rideId) {
          setSelectedRide(prev => prev ? { ...prev, status: "completed" } : null)
        }
        setActionFeedback(`Ride #${rideId} marked as completed.`)
        showToast(`Ride #${rideId} marked as completed.`, "success")
        setTimeout(() => setActionFeedback(null), 3000)
        triggerRefresh()
        return true
      } else {
        showToast("Failed to mark ride completed.", "error")
        return false
      }
    } catch (err: any) {
      console.error("Failed to mark ride completed:", err)
      showToast(err?.message || "Failed to mark ride completed.", "error")
      return false
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Rides Oversight & Moderation</h1>
          <p className="text-xs text-gray-500">Monitor active student carpool routes, verify passenger manifests, and moderate safety</p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 font-medium">
            Active: <strong className="text-gray-900">{rides.filter(r => r.status === "active" || r.status === "full").length}</strong>
          </span>
          <span className="text-gray-300">•</span>
          <span className="text-xs text-gray-500 font-medium">
            Total: <strong className="text-gray-900">{rides.length}</strong>
          </span>
        </div>
      </div>

      {/* Action Notification */}
      {actionFeedback && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center gap-2 animate-in fade-in duration-150">
          <MaterialIcon name="check_circle" className="text-base text-emerald-600" />
          <span>{actionFeedback}</span>
        </div>
      )}

      {/* Search and Filters */}
      <div className="bg-white p-4 rounded-2xl border border-black/8 shadow-sm space-y-3">
        <div className="flex flex-col md:flex-row gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <MaterialIcon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search by pickup, destination, or host name..."
              className="w-full pl-10 pr-4 py-2 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black placeholder-gray-400"
            />
          </div>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">Status: All</option>
            <option value="active">Active (Available)</option>
            <option value="full">Full (Booked)</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>

          {/* Gender Policy Filter */}
          <select
            value={genderFilter}
            onChange={e => setGenderFilter(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">Policy: All</option>
            <option value="female">Female Only</option>
          </select>
        </div>

        <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
          <span>Showing <strong className="text-gray-900">{filteredRides.length}</strong> of {rides.length} rides</span>
          {(searchQuery || statusFilter !== "all" || genderFilter !== "all") && (
            <button
              onClick={() => {
                setSearchQuery("")
                setStatusFilter("all")
                setGenderFilter("all")
              }}
              className="text-black font-semibold hover:underline"
            >
              Reset Filters
            </button>
          )}
        </div>
      </div>

      {/* Rides Table */}
      <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-xs text-gray-500">
            <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
            Loading rides...
          </div>
        ) : filteredRides.length === 0 ? (
          <div className="p-12 text-center text-xs text-gray-500 space-y-2">
            <MaterialIcon name="directions_car" className="text-4xl text-gray-300" />
            <p className="font-semibold text-gray-700">No rides matched your filters</p>
            <p>Try broadening your search query or reset status filters</p>
          </div>
        ) : (
          <>
            {/* Mobile Cards View (md:hidden) */}
            <div className="md:hidden divide-y divide-gray-100">
              {filteredRides.map(ride => (
                <div key={ride.id} className="p-4 space-y-3 hover:bg-gray-50/50 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5 font-bold text-gray-950 text-sm">
                        <span>{ride.from}</span>
                        <span className="text-gray-400">→</span>
                        <span>{ride.to}</span>
                      </div>
                      <p className="text-[11px] text-gray-500 font-medium">
                        Host: <span className="text-gray-800 font-semibold">{ride.hostName}</span>
                      </p>
                    </div>

                    <span className={`inline-block px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase shrink-0 ${
                      ride.status === "cancelled" ? "bg-red-100 text-red-800" :
                      ride.status === "active" ? "bg-green-100 text-green-800" :
                      ride.status === "full" ? "bg-amber-100 text-amber-800" :
                      ride.status === "completed" ? "bg-blue-100 text-blue-800" :
                      "bg-gray-100 text-gray-800"
                    }`}>
                      {ride.status}
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center justify-between text-xs text-gray-500 pt-1">
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1 font-mono text-gray-700 bg-gray-100 px-2 py-0.5 rounded-md text-[11px]">
                        <MaterialIcon name="schedule" className="text-xs" />
                        {ride.date} {ride.departureTime}
                      </span>
                      <span className="font-bold text-gray-800">
                        {ride.availableSeats} seats left
                      </span>
                    </div>

                    <button
                      onClick={() => setSelectedRide(ride)}
                      className="px-3.5 py-1.5 rounded-xl bg-black text-white hover:bg-neutral-800 text-xs font-bold transition-all flex items-center gap-1 active:scale-95 cursor-pointer shadow-xs"
                    >
                      <span>Manage</span>
                      <MaterialIcon name="chevron_right" className="text-sm" />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Desktop Table View */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-xs">
              <thead className="bg-[#F8F9FA] text-gray-500 font-semibold border-b border-gray-100 uppercase tracking-wider">
                <tr>
                  <th className="py-3.5 px-4">Route</th>
                  <th className="py-3.5 px-4">Host Driver</th>
                  <th className="py-3.5 px-4">Departure Time</th>
                  <th className="py-3.5 px-4">Seats Left</th>
                  <th className="py-3.5 px-4">Policy</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredRides.map(ride => (
                  <tr key={ride.id} className="hover:bg-gray-50/80 transition-colors">
                    {/* Route */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-1.5 font-bold text-gray-900">
                          <span>{ride.from}</span>
                          <span className="text-gray-400">→</span>
                          <span>{ride.to}</span>
                        </div>
                        <p className="text-[11px] text-gray-500 font-mono">ID: {ride.id}</p>
                      </div>
                    </td>

                    {/* Host */}
                    <td className="py-3.5 px-4 text-gray-700">
                      <p className="font-semibold text-gray-900">{ride.hostName}</p>
                      <p className="text-[11px] text-gray-500">{ride.hostDepartment} • {ride.hostCollege || "CET"}</p>
                    </td>

                    {/* Schedule */}
                    <td className="py-3.5 px-4 text-gray-700">
                      <p className="font-medium text-gray-900">{ride.date}</p>
                      <p className="text-[11px] text-gray-500">{ride.departureTime}</p>
                    </td>

                    {/* Seats */}
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-gray-900">
                          {ride.availableSeats} / {ride.totalSeats}
                        </span>
                        {ride.acceptedPassengers && ride.acceptedPassengers.length > 0 && (
                          <span className="text-[10px] bg-gray-100 px-1.5 py-0.5 rounded text-gray-600 font-medium">
                            {ride.acceptedPassengers.length} booked
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Gender Policy */}
                    <td className="py-3.5 px-4">
                      {ride.genderPolicy ? (
                        <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold capitalize ${
                          ride.genderPolicy === "female" ? "bg-pink-100 text-pink-800" : "bg-blue-100 text-blue-800"
                        }`}>
                          {ride.genderPolicy} only
                        </span>
                      ) : (
                        <span className="text-gray-400 text-[10px]">Open</span>
                      )}
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4">
                      <span className={`inline-block px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase ${
                        ride.status === "cancelled" ? "bg-red-100 text-red-800" :
                        ride.status === "active" ? "bg-green-100 text-green-800" :
                        ride.status === "full" ? "bg-amber-100 text-amber-800" :
                        ride.status === "completed" ? "bg-blue-100 text-blue-800" :
                        "bg-gray-100 text-gray-800"
                      }`}>
                        {ride.status}
                      </span>
                    </td>

                    {/* Actions */}
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => setSelectedRide(ride)}
                          className="px-2.5 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-800 font-medium transition-colors"
                        >
                          Details
                        </button>

                        {canForceCancel(ride.status) && (
                          <button
                            onClick={() => setSelectedRide(ride)}
                            title="Admin Options"
                            className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors cursor-pointer"
                          >
                            <MaterialIcon name="more_vert" className="text-base" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      </div>

      {/* Ride Detail Modal */}
      <RideDetailModal
        ride={selectedRide}
        onClose={() => setSelectedRide(null)}
        onCancelRide={handleCancelRide}
        onMarkCompleted={handleMarkCompleted}
      />
    </div>
  )
}
