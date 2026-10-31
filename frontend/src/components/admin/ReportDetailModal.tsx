import { useState } from "react"
import type { AdminReport } from "../../services/admin/adminService"
import { MaterialIcon } from "../common/MaterialIcon"

interface ReportDetailModalProps {
  report: AdminReport | null
  onClose: () => void
  onUpdateStatus: (
    reportId: string,
    status: "under_review" | "resolved" | "dismissed",
    adminNotes: string
  ) => void
}

export function ReportDetailModal({
  report,
  onClose,
  onUpdateStatus
}: ReportDetailModalProps) {
  const [adminNotes, setAdminNotes] = useState(report?.adminNotes || "")

  if (!report) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div
        className="w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-black/10 overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 bg-gradient-to-r from-red-950 via-gray-900 to-black text-white relative">
          <button
            onClick={onClose}
            className="absolute top-5 right-5 text-gray-400 hover:text-white transition-colors"
          >
            <MaterialIcon name="close" className="text-xl" />
          </button>

          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-500 text-white uppercase">
              {report.category.replace("_", " ")}
            </span>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full capitalize ${
              report.status === "resolved" ? "bg-green-500 text-white" :
              report.status === "under_review" ? "bg-amber-500 text-black" :
              report.status === "dismissed" ? "bg-gray-500 text-white" :
              "bg-red-400 text-black"
            }`}>
              {report.status.replace("_", " ")}
            </span>
          </div>

          <h2 className="text-xl font-bold">Safety Incident Report</h2>
          <p className="text-xs text-gray-300 font-mono mt-0.5">Ticket ID: {report.id}</p>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Parties Involved */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
              <p className="text-xs text-gray-500 font-medium">Filed By (Reporter)</p>
              <p className="font-semibold text-gray-900">{report.reporterName || "Student"}</p>
              <p className="text-xs text-gray-500 font-mono mt-0.5">{report.reporterEmail}</p>
            </div>

            <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
              <p className="text-xs text-gray-500 font-medium">Reported Entity</p>
              <p className="font-semibold text-gray-900">{report.reportedUserName || "User / Ride"}</p>
              <p className="text-xs text-gray-500 font-mono mt-0.5">
                {report.rideId ? `Ride: ${report.rideId}` : report.reportedUserId ? `UID: ${report.reportedUserId}` : "General"}
              </p>
            </div>
          </div>

          {/* Description */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Incident Description</h3>
            <div className="p-4 rounded-xl bg-gray-50 border border-gray-100 text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
              {report.description}
            </div>
          </div>

          {/* Admin Notes */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Admin Investigation Notes</h3>
            <textarea
              value={adminNotes}
              onChange={e => setAdminNotes(e.target.value)}
              placeholder="Enter disciplinary actions taken, contact outcomes, or investigation summary..."
              rows={3}
              className="w-full text-xs p-3 bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black"
            />
          </div>

          {/* Triage Actions */}
          <div className="space-y-3 pt-2 border-t border-gray-100">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Update Resolution Status</h3>
            <div className="grid grid-cols-3 gap-2">
              <button
                onClick={() => onUpdateStatus(report.id, "under_review", adminNotes)}
                className="py-2 px-2.5 rounded-xl text-xs font-semibold bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 flex items-center justify-center gap-1 transition-all"
              >
                <MaterialIcon name="visibility" className="text-sm" />
                Under Review
              </button>

              <button
                onClick={() => onUpdateStatus(report.id, "resolved", adminNotes)}
                className="py-2 px-2.5 rounded-xl text-xs font-semibold bg-green-600 hover:bg-green-700 text-white flex items-center justify-center gap-1 transition-all shadow-sm"
              >
                <MaterialIcon name="check" className="text-sm" />
                Resolve
              </button>

              <button
                onClick={() => onUpdateStatus(report.id, "dismissed", adminNotes)}
                className="py-2 px-2.5 rounded-xl text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-700 flex items-center justify-center gap-1 transition-all"
              >
                <MaterialIcon name="close" className="text-sm" />
                Dismiss
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 bg-gray-50 border-t border-gray-100 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-gray-900 hover:bg-black text-white text-xs font-semibold transition-all"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
