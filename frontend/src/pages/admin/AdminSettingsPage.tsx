import { useEffect, useState } from "react"
import { adminService, type SystemBanner, type AdminActionLog } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { MaterialIcon } from "../../components/common/MaterialIcon"
import { SmsMfaCard } from "../../components/security/SmsMfaCard"

export function AdminSettingsPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const [banner, setBanner] = useState<SystemBanner>({
    enabled: false,
    message: "Campus Weather Advisory: Heavy rains expected in Trivandrum. Please plan rides early!",
    type: "info"
  })
  const [logs, setLogs] = useState<AdminActionLog[]>([])
  const [savingBanner, setSavingBanner] = useState(false)
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    async function loadData() {
      try {
        const [bannerData, logsData] = await Promise.all([
          adminService.getSystemBanner(),
          adminService.getAdminLogs()
        ])
        if (mounted) {
          setBanner(bannerData)
          setLogs(logsData)
        }
      } catch (err) {
        console.error("Failed to load settings data:", err)
      }
    }

    loadData()
    return () => { mounted = false }
  }, [refreshTrigger])

  const handleSaveBanner = async () => {
    setSavingBanner(true)
    try {
      const success = await adminService.updateSystemBanner(banner, adminUid, adminEmail)
      if (success) {
        setActionFeedback("Campus broadcast banner updated successfully!")
        setTimeout(() => setActionFeedback(null), 3000)
        triggerRefresh()
      }
    } catch (e) {
      console.error(e)
    } finally {
      setSavingBanner(false)
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">System Settings & Audit Trail</h1>
        <p className="text-xs text-gray-500">Configure campus broadcast alerts, view administrative audit logs, and platform parameters</p>
      </div>

      {/* Action Notification */}
      {actionFeedback && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center gap-2 animate-in fade-in duration-150">
          <MaterialIcon name="check_circle" className="text-base text-emerald-600" />
          <span>{actionFeedback}</span>
        </div>
      )}

      {/* Administrative Two-Factor Authentication Security */}
      <SmsMfaCard showAsAdminOps className="bg-white border-black/8" />

      {/* Campus Broadcast Banner Manager */}
      <div className="bg-white rounded-2xl p-6 border border-black/8 shadow-sm space-y-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-gray-900">Campus Emergency & Advisory Broadcast</h2>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                banner.enabled ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-600"
              }`}>
                {banner.enabled ? "Active on Student App" : "Disabled"}
              </span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              Display an emergency notice or weather advisory banner at the top of all student rider app screens
            </p>
          </div>

          {/* Toggle Switch */}
          <button
            onClick={() => setBanner(prev => ({ ...prev, enabled: !prev.enabled }))}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              banner.enabled ? "bg-[#25D366]" : "bg-gray-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                banner.enabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold text-gray-700 block mb-1">
              Broadcast Message
            </label>
            <input
              type="text"
              value={banner.message}
              onChange={e => setBanner(prev => ({ ...prev, message: e.target.value }))}
              placeholder="e.g. Heavy rain advisory: Evening carpools recommended from CET Kulathoor."
              className="w-full text-xs p-3 bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black"
            />
          </div>

          <div className="flex items-center gap-4">
            <span className="text-xs font-semibold text-gray-700">Alert Priority:</span>
            <div className="flex items-center gap-2">
              {(["info", "warning", "alert"] as const).map(type => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setBanner(prev => ({ ...prev, type }))}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold uppercase transition-all ${
                    banner.type === type
                      ? type === "alert"
                        ? "bg-red-600 text-white"
                        : type === "warning"
                        ? "bg-amber-500 text-black font-bold"
                        : "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Live Preview Box */}
        <div className="pt-2">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
            Student App Live Preview
          </p>
          <div className={`p-3 rounded-xl flex items-center gap-2.5 text-xs font-medium ${
            banner.type === "alert"
              ? "bg-red-500 text-white"
              : banner.type === "warning"
              ? "bg-[#C5FF00] text-black font-semibold"
              : "bg-gray-900 text-white"
          }`}>
            <MaterialIcon
              name={banner.type === "alert" ? "emergency" : banner.type === "warning" ? "warning" : "info"}
              className="text-base"
            />
            <span className="truncate">{banner.message || "No alert message set"}</span>
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-gray-100">
          <button
            onClick={handleSaveBanner}
            disabled={savingBanner}
            className="px-5 py-2.5 rounded-xl bg-black hover:bg-gray-800 disabled:opacity-50 text-white text-xs font-bold transition-all shadow-sm flex items-center gap-1.5"
          >
            <MaterialIcon name="campaign" className="text-base text-[#C5FF00]" />
            <span>{savingBanner ? "Saving..." : "Save & Publish Broadcast"}</span>
          </button>
        </div>
      </div>

      {/* Platform & Campus Parameters */}
      <div className="bg-white rounded-2xl p-6 border border-black/8 shadow-sm space-y-4">
        <h2 className="text-lg font-bold text-gray-900">Campus Cluster Configuration</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="bg-gray-50 p-4 rounded-xl border border-gray-100 space-y-1">
            <p className="font-semibold text-gray-900">Primary Hub</p>
            <p className="text-gray-600">College of Engineering Trivandrum (CET)</p>
            <p className="text-[11px] text-gray-400">Lat: 8.5463, Lng: 76.9064</p>
          </div>

          <div className="bg-gray-50 p-4 rounded-xl border border-gray-100 space-y-1">
            <p className="font-semibold text-gray-900">Partner Campuses</p>
            <p className="text-gray-600">GEC Barton Hill • Mar Ivanios • SCT</p>
            <p className="text-[11px] text-gray-400">Inter-college route matching enabled</p>
          </div>

          <div className="bg-gray-50 p-4 rounded-xl border border-gray-100 space-y-1">
            <p className="font-semibold text-gray-900">Safety & Strict Gender Policy</p>
            <p className="text-gray-600">Gender strict carpool matching active</p>
            <p className="text-[11px] text-[#25D366] font-semibold">Enforced in Firestore Rules</p>
          </div>
        </div>
      </div>

      {/* Admin Audit Trail Logs */}
      <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden space-y-3">
        <div className="p-6 pb-2">
          <h2 className="text-lg font-bold text-gray-900">Administrative Audit Logs</h2>
          <p className="text-xs text-gray-500">Immutable ledger of administrative verifications, role promotions, and moderation actions</p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#F8F9FA] text-gray-500 font-semibold border-y border-gray-100 uppercase tracking-wider">
              <tr>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Action</th>
                <th className="py-3 px-4">Admin Email</th>
                <th className="py-3 px-4">Target ID</th>
                <th className="py-3 px-4">Action Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-gray-400 text-xs">
                    No administrative audit logs recorded yet.
                  </td>
                </tr>
              ) : (
                logs.map((log, i) => (
                  <tr key={log.id || `log-${log.actionType}-${log.targetId}-${i}`} className="hover:bg-gray-50/80 transition-colors">
                  <td className="py-3 px-4 text-gray-500 font-mono text-[11px] whitespace-nowrap">
                    {new Date(log.timestamp?.toDate?.() || log.timestamp).toLocaleString()}
                  </td>
                  <td className="py-3 px-4">
                    <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-black text-[#C5FF00] tracking-wider">
                      {log.actionType}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-gray-700">
                    {log.adminEmail}
                  </td>
                  <td className="py-3 px-4 font-mono text-gray-500 select-all">
                    {log.targetId}
                  </td>
                  <td className="py-3 px-4 text-gray-800">
                    {log.details}
                  </td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
