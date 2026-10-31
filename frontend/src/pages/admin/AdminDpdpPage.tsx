import { useEffect, useState, useMemo } from "react"
import { adminService, type AdminDataRightsRequest } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { MaterialIcon } from "../../components/common/MaterialIcon"

export function AdminDpdpPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const [requests, setRequests] = useState<AdminDataRightsRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedReq, setSelectedReq] = useState<AdminDataRightsRequest | null>(null)
  const [adminNotes, setAdminNotes] = useState("")
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState("all")

  useEffect(() => {
    let mounted = true
    async function loadRequests() {
      setLoading(true)
      try {
        const data = await adminService.getDataRightsRequests()
        if (mounted) setRequests(data)
      } catch (err) {
        console.error("Failed to load DPDPA requests:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadRequests()
    return () => { mounted = false }
  }, [refreshTrigger])

  const filteredRequests = useMemo(() => {
    return requests.filter(r => {
      if (typeFilter === "all") return true
      return r.type === typeFilter
    })
  }, [requests, typeFilter])

  const handleUpdateStatus = async (
    requestId: string,
    status: "in_review" | "completed" | "rejected"
  ) => {
    const success = await adminService.updateDataRightsStatus(requestId, status, adminNotes, adminUid, adminEmail)
    if (success) {
      setRequests(prev => prev.map(r => r.id === requestId ? { ...r, status, adminNotes } : r))
      setSelectedReq(null)
      setAdminNotes("")
      setActionFeedback(`Request #${requestId} status set to ${status}.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  const currentTimestamp = useMemo(() => Date.now(), [requests])

  const calculateDaysRemaining = (submittedAt: string) => {
    const submitted = new Date(submittedAt).getTime()
    const thirtyDays = 30 * 24 * 60 * 60 * 1000
    const deadline = submitted + thirtyDays
    const remainingDays = Math.ceil((deadline - currentTimestamp) / (24 * 60 * 60 * 1000))
    return remainingDays
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight">DPDPA 2023 Compliance Desk</h1>
            <span className="bg-blue-100 text-blue-900 text-xs font-bold px-2 py-0.5 rounded-full">
              Legal SLA: 30 Days
            </span>
          </div>
          <p className="text-xs text-gray-500">
            Fulfill student statutory rights under the Digital Personal Data Protection Act (Access, Erasure, Correction, Grievance)
          </p>
        </div>

        <div className="p-3 bg-blue-50/70 border border-blue-200 rounded-xl text-xs text-blue-900 flex items-center gap-2">
          <MaterialIcon name="info" className="text-base text-blue-600" />
          <span>Grievance Officer: <strong>icvalley@proton.me</strong></span>
        </div>
      </div>

      {/* Action Notification */}
      {actionFeedback && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center gap-2 animate-in fade-in duration-150">
          <MaterialIcon name="check_circle" className="text-base text-emerald-600" />
          <span>{actionFeedback}</span>
        </div>
      )}

      {/* Legal Info Card */}
      <div className="bg-white rounded-2xl p-5 border border-black/8 shadow-sm grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
        <div className="p-3 bg-gray-50 rounded-xl border border-gray-100 space-y-1">
          <p className="font-bold text-gray-900">§12 Right to Access</p>
          <p className="text-gray-500">Data principal request for copy of personal ride logs & account data.</p>
        </div>
        <div className="p-3 bg-gray-50 rounded-xl border border-gray-100 space-y-1">
          <p className="font-bold text-gray-900">§13(1) Correction</p>
          <p className="text-gray-500">Correction of inaccurate campus academic info or contact details.</p>
        </div>
        <div className="p-3 bg-gray-50 rounded-xl border border-gray-100 space-y-1">
          <p className="font-bold text-gray-900">§13(2) Right to Erasure</p>
          <p className="text-gray-500">Permanent deletion of user document, profile, and push tokens.</p>
        </div>
        <div className="p-3 bg-gray-50 rounded-xl border border-gray-100 space-y-1">
          <p className="font-bold text-gray-900">§13(3) Grievance Redressal</p>
          <p className="text-gray-500">Statutory 30-day resolution timeline before escalation to DPB India.</p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-white p-4 rounded-2xl border border-black/8 shadow-sm flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-700">Filter by Right:</span>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="py-1.5 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">All Rights (§11-14)</option>
            <option value="access">Access (§12)</option>
            <option value="correction">Correction (§13.1)</option>
            <option value="erasure">Erasure (§13.2)</option>
            <option value="grievance">Grievance (§13.3)</option>
            <option value="withdrawal">Withdrawal (§14)</option>
          </select>
        </div>

        <span className="text-xs text-gray-500">
          Total Requests: <strong className="text-gray-900">{filteredRequests.length}</strong>
        </span>
      </div>

      {/* Requests Table */}
      <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-xs text-gray-500">
            <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
            Loading DPDPA compliance ledger...
          </div>
        ) : filteredRequests.length === 0 ? (
          <div className="p-12 text-center text-xs text-gray-500 space-y-2">
            <MaterialIcon name="verified" className="text-4xl text-green-500" />
            <p className="font-semibold text-gray-700">All data rights requests completed</p>
            <p>No open statutory compliance tickets pending</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#F8F9FA] text-gray-500 font-semibold border-b border-gray-100 uppercase tracking-wider">
                <tr>
                  <th className="py-3.5 px-4">Ticket</th>
                  <th className="py-3.5 px-4">Right Type</th>
                  <th className="py-3.5 px-4">Student Principal</th>
                  <th className="py-3.5 px-4">Request Summary</th>
                  <th className="py-3.5 px-4">Statutory SLA</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredRequests.map(req => {
                  const daysLeft = calculateDaysRemaining(req.submittedAt)
                  return (
                    <tr key={req.id} className="hover:bg-gray-50/80 transition-colors">
                      <td className="py-3.5 px-4 font-mono font-medium text-gray-800">
                        {req.id}
                      </td>

                      <td className="py-3.5 px-4">
                        <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-blue-100 text-blue-900">
                          {req.type}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 text-gray-800">
                        <p className="font-medium text-gray-900">{req.name}</p>
                        <p className="text-[11px] text-gray-500 font-mono">{req.email}</p>
                      </td>

                      <td className="py-3.5 px-4 max-w-xs text-gray-600">
                        <p className="line-clamp-2">{req.details}</p>
                      </td>

                      <td className="py-3.5 px-4">
                        <span className={`inline-flex items-center gap-1 font-semibold text-[11px] px-2 py-0.5 rounded-full ${
                          daysLeft <= 5 ? "bg-red-100 text-red-800" :
                          daysLeft <= 15 ? "bg-amber-100 text-amber-800" :
                          "bg-green-100 text-green-800"
                        }`}>
                          <MaterialIcon name="timer" className="text-xs" />
                          {daysLeft > 0 ? `${daysLeft} days left` : "Overdue"}
                        </span>
                      </td>

                      <td className="py-3.5 px-4">
                        <span className={`inline-block px-2.5 py-0.5 rounded-full text-[11px] font-bold capitalize ${
                          req.status === "completed" ? "bg-green-100 text-green-800" :
                          req.status === "in_review" ? "bg-amber-100 text-amber-800" :
                          req.status === "rejected" ? "bg-gray-100 text-gray-700" :
                          "bg-red-100 text-red-800"
                        }`}>
                          {req.status.replace("_", " ")}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={() => {
                            setSelectedReq(req)
                            setAdminNotes(req.adminNotes || "")
                          }}
                          className="px-3 py-1.5 rounded-lg bg-gray-900 hover:bg-black text-white text-xs font-semibold transition-colors"
                        >
                          Process Ticket
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Ticket Modal */}
      {selectedReq && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-black/10 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-6 bg-gradient-to-r from-blue-950 to-black text-white relative">
              <button
                onClick={() => setSelectedReq(null)}
                className="absolute top-5 right-5 text-gray-400 hover:text-white"
              >
                <MaterialIcon name="close" className="text-xl" />
              </button>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-[#C5FF00] text-black uppercase">
                  DPDPA §{selectedReq.type === "access" ? "12" : selectedReq.type === "correction" ? "13(1)" : selectedReq.type === "erasure" ? "13(2)" : "13(3)"}
                </span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-white/20 capitalize">
                  {selectedReq.status.replace("_", " ")}
                </span>
              </div>
              <h2 className="text-xl font-bold">Process Data Rights Request</h2>
              <p className="text-xs text-gray-300 font-mono mt-0.5">Ticket ID: {selectedReq.id}</p>
            </div>

            <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
              <div className="bg-gray-50 p-3.5 rounded-xl border border-gray-100 text-xs space-y-1">
                <p className="font-semibold text-gray-900">Data Principal: {selectedReq.name}</p>
                <p className="text-gray-600 font-mono">{selectedReq.email} (UID: {selectedReq.uid})</p>
                <p className="text-gray-500 pt-1">Submitted on: {new Date(selectedReq.submittedAt).toLocaleString()}</p>
              </div>

              <div className="space-y-1.5">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Request Statement</h4>
                <div className="p-3.5 rounded-xl bg-gray-50 border border-gray-100 text-xs text-gray-800 leading-relaxed">
                  {selectedReq.details}
                </div>
              </div>

              <div className="space-y-1.5">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Admin Fulfillment Notes</h4>
                <textarea
                  value={adminNotes}
                  onChange={e => setAdminNotes(e.target.value)}
                  placeholder="Record compliance action (e.g. data export sent to email, personal records anonymized, request fulfilled)..."
                  rows={3}
                  className="w-full text-xs p-3 bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>

              <div className="space-y-2 pt-2 border-t border-gray-100">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Fulfillment Decision</h4>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    onClick={() => handleUpdateStatus(selectedReq.id, "in_review")}
                    className="py-2 px-2 rounded-xl text-xs font-semibold bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200"
                  >
                    In Review
                  </button>

                  <button
                    onClick={() => handleUpdateStatus(selectedReq.id, "completed")}
                    className="py-2 px-2 rounded-xl text-xs font-semibold bg-green-600 hover:bg-green-700 text-white shadow-sm"
                  >
                    Fulfill (§ Completed)
                  </button>

                  <button
                    onClick={() => handleUpdateStatus(selectedReq.id, "rejected")}
                    className="py-2 px-2 rounded-xl text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-700"
                  >
                    Reject (Non-compliant)
                  </button>
                </div>
              </div>
            </div>

            <div className="p-4 bg-gray-50 border-t border-gray-100 flex justify-end">
              <button
                onClick={() => setSelectedReq(null)}
                className="px-5 py-2 rounded-xl bg-gray-900 hover:bg-black text-white text-xs font-semibold"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
