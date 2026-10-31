import { useEffect, useState, useMemo } from "react"
import { adminService, type AdminReport } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { ReportDetailModal } from "../../components/admin/ReportDetailModal"
import { MaterialIcon } from "../../components/common/MaterialIcon"

export function AdminReportsPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const [reports, setReports] = useState<AdminReport[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedReport, setSelectedReport] = useState<AdminReport | null>(null)

  // Filters
  const [searchQuery, setSearchQuery] = useState("")
  const [categoryFilter, setCategoryFilter] = useState("all")
  const [statusFilter, setStatusFilter] = useState("all")
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    async function loadReports() {
      setLoading(true)
      try {
        const data = await adminService.getReports()
        if (mounted) setReports(data)
      } catch (err) {
        console.error("Failed to load reports:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadReports()
    return () => { mounted = false }
  }, [refreshTrigger])

  const filteredReports = useMemo(() => {
    return reports.filter(r => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch = !q || (
        r.id.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        (r.reporterName || "").toLowerCase().includes(q) ||
        (r.reporterEmail || "").toLowerCase().includes(q) ||
        (r.reportedUserName || "").toLowerCase().includes(q)
      )

      const matchesCategory = categoryFilter === "all" || r.category === categoryFilter
      const matchesStatus = statusFilter === "all" || r.status === statusFilter

      return matchesSearch && matchesCategory && matchesStatus
    })
  }, [reports, searchQuery, categoryFilter, statusFilter])

  const handleUpdateStatus = async (
    reportId: string,
    status: "under_review" | "resolved" | "dismissed",
    adminNotes: string
  ) => {
    const success = await adminService.updateReportStatus(reportId, status, adminNotes, adminUid, adminEmail)
    if (success) {
      setReports(prev => prev.map(r => r.id === reportId ? { ...r, status, adminNotes } : r))
      if (selectedReport?.id === reportId) {
        setSelectedReport(prev => prev ? { ...prev, status, adminNotes } : null)
      }
      setActionFeedback(`Report #${reportId} updated to ${status}.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Safety & Incident Moderation</h1>
          <p className="text-xs text-gray-500">Triage user complaints, no-shows, harassment reports, and campus transit safety</p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-red-100 text-red-800">
            {reports.filter(r => r.status === "pending" || r.status === "under_review").length} Open Cases
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

      {/* KPI Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-black/8 shadow-sm">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Pending Triage</p>
          <h3 className="text-2xl font-bold text-red-600 mt-1">
            {reports.filter(r => r.status === "pending").length}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">Unreviewed complaints</p>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-black/8 shadow-sm">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Under Active Review</p>
          <h3 className="text-2xl font-bold text-amber-600 mt-1">
            {reports.filter(r => r.status === "under_review").length}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">Investigation in progress</p>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-black/8 shadow-sm">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Resolved / Closed</p>
          <h3 className="text-2xl font-bold text-green-600 mt-1">
            {reports.filter(r => r.status === "resolved" || r.status === "dismissed").length}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">Disciplinary action or dismissed</p>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="bg-white p-4 rounded-2xl border border-black/8 shadow-sm space-y-3">
        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <MaterialIcon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search reports by ticket ID, student, or incident summary..."
              className="w-full pl-10 pr-4 py-2 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black placeholder-gray-400"
            />
          </div>

          <select
            value={categoryFilter}
            onChange={e => setCategoryFilter(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">Category: All</option>
            <option value="wrong_profile_information">Wrong Profile Information</option>
            <option value="phone_misuse">Phone Number Misuse</option>
            <option value="harassment">Harassment</option>
            <option value="inappropriate_behavior">Inappropriate Behaviour</option>
            <option value="impersonation">Impersonation</option>
            <option value="safety_concern">Safety Concern</option>
            <option value="reckless_driving">Reckless Driving</option>
            <option value="no_show">No-Show Passenger/Driver</option>
            <option value="fare_dispute">Fare Dispute</option>
            <option value="fake_profile">Fake / Suspicious Profile</option>
            <option value="other">Other</option>
          </select>

          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">Status: All</option>
            <option value="pending">Pending</option>
            <option value="under_review">Under Review</option>
            <option value="resolved">Resolved</option>
            <option value="dismissed">Dismissed</option>
          </select>
        </div>

        <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
          <span>Showing <strong className="text-gray-900">{filteredReports.length}</strong> of {reports.length} reports</span>
          {(searchQuery || categoryFilter !== "all" || statusFilter !== "all") && (
            <button
              onClick={() => {
                setSearchQuery("")
                setCategoryFilter("all")
                setStatusFilter("all")
              }}
              className="text-black font-semibold hover:underline"
            >
              Reset Filters
            </button>
          )}
        </div>
      </div>

      {/* Reports Table */}
      <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-xs text-gray-500">
            <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
            Loading safety reports...
          </div>
        ) : filteredReports.length === 0 ? (
          <div className="p-12 text-center text-xs text-gray-500 space-y-2">
            <MaterialIcon name="verified_user" className="text-4xl text-green-500" />
            <p className="font-semibold text-gray-700">No safety reports found</p>
            <p>Campus rides are safe and compliant</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#F8F9FA] text-gray-500 font-semibold border-b border-gray-100 uppercase tracking-wider">
                <tr>
                  <th className="py-3.5 px-4">Ticket</th>
                  <th className="py-3.5 px-4">Category</th>
                  <th className="py-3.5 px-4">Reporter</th>
                  <th className="py-3.5 px-4">Reported Entity</th>
                  <th className="py-3.5 px-4">Description</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredReports.map(rep => (
                  <tr key={rep.id} className="hover:bg-gray-50/80 transition-colors">
                    {/* Ticket */}
                    <td className="py-3.5 px-4 font-mono font-medium text-gray-800">
                      {rep.id}
                    </td>

                    {/* Category */}
                    <td className="py-3.5 px-4">
                      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-red-100 text-red-800">
                        {rep.category.replace("_", " ")}
                      </span>
                    </td>

                    {/* Reporter */}
                    <td className="py-3.5 px-4 text-gray-800">
                      <p className="font-medium text-gray-900">{rep.reporterName || "Student"}</p>
                      <p className="text-[11px] text-gray-500 font-mono">{rep.reporterEmail}</p>
                    </td>

                    {/* Reported User */}
                    <td className="py-3.5 px-4 text-gray-800">
                      <p className="font-medium text-gray-900">{rep.reportedUserName || "User"}</p>
                      <p className="text-[11px] text-gray-500 font-mono">
                        {rep.rideId ? `Ride #${rep.rideId}` : rep.reportedUserId || "General"}
                      </p>
                    </td>

                    {/* Description preview */}
                    <td className="py-3.5 px-4 max-w-xs text-gray-600">
                      <p className="line-clamp-2">{rep.description}</p>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4">
                      <span className={`inline-block px-2.5 py-0.5 rounded-full text-[11px] font-bold capitalize ${
                        rep.status === "resolved" ? "bg-green-100 text-green-800" :
                        rep.status === "under_review" ? "bg-amber-100 text-amber-800" :
                        rep.status === "dismissed" ? "bg-gray-100 text-gray-700" :
                        "bg-red-100 text-red-800"
                      }`}>
                        {rep.status.replace("_", " ")}
                      </span>
                    </td>

                    {/* Actions */}
                    <td className="py-3.5 px-4 text-right">
                      <button
                        onClick={() => setSelectedReport(rep)}
                        className="px-3 py-1.5 rounded-lg bg-gray-900 hover:bg-black text-white text-xs font-semibold transition-colors"
                      >
                        Triage Case
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Report Detail Modal */}
      <ReportDetailModal
        report={selectedReport}
        onClose={() => setSelectedReport(null)}
        onUpdateStatus={handleUpdateStatus}
      />
    </div>
  )
}
