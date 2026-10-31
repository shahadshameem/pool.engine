import { useEffect, useState, useMemo } from "react"
import { adminService, type AdminCabPool } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { MaterialIcon } from "../../components/common/MaterialIcon"
import { ConfirmModal } from "../../components/ui/confirm-modal"
import { useToast } from "../../components/feedback/ToastContext"

export function AdminCabPoolsPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const { showToast } = useToast()
  const [pools, setPools] = useState<AdminCabPool[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)
  const [poolToCancel, setPoolToCancel] = useState<AdminCabPool | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)

  useEffect(() => {
    let mounted = true
    async function loadPools() {
      setLoading(true)
      try {
        const data = await adminService.getCabPools()
        if (mounted) setPools(data)
      } catch (err) {
        console.error("Failed to load cab pools:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadPools()
    return () => { mounted = false }
  }, [refreshTrigger])

  const filteredPools = useMemo(() => {
    return pools.filter(p => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch = !q || (
        (p.pickupLocation || "").toLowerCase().includes(q) ||
        (p.destination || "").toLowerCase().includes(q) ||
        (p.creatorName || "").toLowerCase().includes(q)
      )
      const matchesStatus = statusFilter === "all" || p.status === statusFilter
      return matchesSearch && matchesStatus
    })
  }, [pools, searchQuery, statusFilter])

  const handleConfirmCancel = async () => {
    if (!poolToCancel || isCancelling) return
    setIsCancelling(true)
    try {
      const success = await adminService.cancelCabPool(poolToCancel.id, adminUid, adminEmail)
      if (success) {
        setPools(prev => prev.map(p => p.id === poolToCancel.id ? { ...p, status: "cancelled" } : p))
        setActionFeedback(`Cab Pool #${poolToCancel.id} has been cancelled.`)
        showToast(`Cab Pool #${poolToCancel.id} has been cancelled.`, "success")
        setTimeout(() => setActionFeedback(null), 3000)
        triggerRefresh()
        setPoolToCancel(null)
      } else {
        showToast("Failed to cancel cab pool. Please try again.", "error")
      }
    } catch (err: any) {
      console.error("Failed to cancel cab pool:", err)
      showToast(err?.message || "Failed to cancel cab pool.", "error")
    } finally {
      setIsCancelling(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Cab Pools Management</h1>
          <p className="text-xs text-gray-500">Monitor active student cab-splitting groups to airports, stations, and festivals</p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 font-medium">
            Active Groups: <strong className="text-gray-900">{pools.filter(p => p.status === "forming" || p.status === "ready").length}</strong>
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
      <div className="bg-white p-4 rounded-2xl border border-black/8 shadow-sm flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <MaterialIcon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search by pickup, destination, or student organizer..."
            className="w-full pl-10 pr-4 py-2 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black placeholder-gray-400"
          />
        </div>

        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
        >
          <option value="all">Status: All</option>
          <option value="forming">Forming (Filling up)</option>
          <option value="ready">Ready (Filled)</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {/* Pools Grid */}
      {loading ? (
        <div className="p-12 text-center text-xs text-gray-500">
          <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
          Loading cab pools...
        </div>
      ) : filteredPools.length === 0 ? (
        <div className="p-12 text-center text-xs text-gray-500 bg-white rounded-2xl border border-black/8 space-y-2">
          <MaterialIcon name="local_taxi" className="text-4xl text-gray-300" />
          <p className="font-semibold text-gray-700">No cab pool groups found</p>
          <p>Students can form cab pools anytime from the rider app</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredPools.map(pool => (
            <div key={pool.id} className="bg-white rounded-2xl p-5 border border-black/8 shadow-sm space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                    pool.status === "forming" ? "bg-amber-100 text-amber-800" :
                    pool.status === "ready" ? "bg-green-100 text-green-800" :
                    pool.status === "completed" ? "bg-blue-100 text-blue-800" :
                    "bg-red-100 text-red-800"
                  }`}>
                    {pool.status}
                  </span>
                  <h3 className="font-bold text-gray-900 text-base mt-2 flex items-center gap-1.5">
                    <span>{pool.pickupLocation}</span>
                    <span className="text-gray-400">→</span>
                    <span>{pool.destination}</span>
                  </h3>
                </div>

                <div className="w-9 h-9 rounded-xl bg-[#F4F4F6] text-black flex items-center justify-center">
                  <MaterialIcon name="local_taxi" className="text-xl" />
                </div>
              </div>

              {/* Timing & Organizer */}
              <div className="grid grid-cols-2 gap-2 text-xs bg-gray-50 p-3 rounded-xl border border-gray-100">
                <div>
                  <p className="text-gray-500">Departure</p>
                  <p className="font-semibold text-gray-900">{pool.date} • {pool.departureTime}</p>
                </div>
                <div>
                  <p className="text-gray-500">Organizer</p>
                  <p className="font-semibold text-gray-900">{pool.creatorName}</p>
                </div>
              </div>

              {/* Members List */}
              <div className="space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-semibold text-gray-700">
                    Group Members ({(pool.currentMembers?.length || 0)}/{(pool.maxMembers || 4)})
                  </span>
                  <span className="text-[11px] text-gray-500">
                    {Math.max(0, (pool.maxMembers || 4) - (pool.currentMembers?.length || 0))} spots remaining
                  </span>
                </div>

                <div className="space-y-1.5">
                  {(pool.currentMembers || []).map((m, i) => (
                    <div key={i} className="flex items-center justify-between text-xs bg-gray-50/60 p-2 rounded-lg border border-gray-100">
                      <div className="flex items-center gap-2">
                        <div className="w-5 h-5 rounded-full bg-black text-[#C5FF00] font-bold text-[10px] flex items-center justify-center">
                          {(m.name || "S").charAt(0)}
                        </div>
                        <span className="font-medium text-gray-800">{m.name || "Student"}</span>
                      </div>
                      <span className="font-mono text-gray-500 text-[11px]">{m.phone || "Joined"}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Actions */}
              {pool.status !== "cancelled" && (
                <div className="pt-2 border-t border-gray-100 flex justify-end">
                  <button
                    onClick={() => setPoolToCancel(pool)}
                    className="px-3 py-1.5 rounded-lg border border-red-200 text-red-700 hover:bg-red-50 text-xs font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                  >
                    <MaterialIcon name="cancel" className="text-sm" />
                    Cancel Pool
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Styled Confirm Modal replacing native window.confirm */}
      <ConfirmModal
        isOpen={!!poolToCancel}
        onClose={() => !isCancelling && setPoolToCancel(null)}
        onConfirm={handleConfirmCancel}
        title="Cancel Cab Pool Group"
        description={
          poolToCancel
            ? `Are you sure you want to cancel the cab pool from ${poolToCancel.pickupLocation} to ${poolToCancel.destination}? This action cannot be undone.`
            : ""
        }
        confirmText="Cancel Pool"
        cancelText="Keep Pool"
        isLoading={isCancelling}
      />
    </div>
  )
}
