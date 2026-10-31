import { useEffect, useState, useMemo } from "react"
import { adminService, type AdminUser } from "../../services/admin/adminService"
import { verificationHelpService, type VerificationHelpRequest } from "../../services/verification/verificationHelpService"
import { useAdmin } from "../../contexts/AdminContext"
import { UserDetailModal } from "../../components/admin/UserDetailModal"
import { MaterialIcon } from "../../components/common/MaterialIcon"
import { useToast } from "../../components/feedback/ToastContext"

export function AdminVerificationsPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const { showToast } = useToast()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [helpRequests, setHelpRequests] = useState<VerificationHelpRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null)
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [approvingUids, setApprovingUids] = useState<Set<string>>(new Set())
  const [isApprovingAll, setIsApprovingAll] = useState(false)
  const [activeTab, setActiveTab] = useState<"pending" | "escalations">("pending")

  useEffect(() => {
    let mounted = true
    async function loadData() {
      setLoading(true)
      try {
        const [allUsers, helpReqs] = await Promise.all([
          adminService.getUsers(),
          verificationHelpService.getPendingHelpRequests()
        ])
        if (mounted) {
          setUsers(allUsers)
          setHelpRequests(helpReqs)
        }
      } catch (err) {
        console.error("Failed to load verification queue:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadData()
    return () => { mounted = false }
  }, [refreshTrigger])

  const pendingUsers = useMemo(() => {
    return users.filter(u => !u.collegeVerified).filter(u => {
      const q = searchQuery.toLowerCase().trim()
      if (!q) return true
      return u.name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        u.department.toLowerCase().includes(q) ||
        u.college.toLowerCase().includes(q)
    })
  }, [users, searchQuery])

  const handleApprove = async (uid: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation()
    if (approvingUids.has(uid)) return

    setApprovingUids(prev => new Set(prev).add(uid))
    try {
      const success = await adminService.updateUserVerification(uid, true, adminUid, adminEmail)
      if (success) {
        setUsers(prev => prev.map(u => u.uid === uid ? { ...u, collegeVerified: true } : u))
        setActionFeedback("Student college credentials approved successfully.")
        showToast("Student college credentials approved successfully.", "success")
        setTimeout(() => setActionFeedback(null), 3000)
        triggerRefresh()
      } else {
        showToast("Failed to approve student credentials. Please try again.", "error")
      }
    } catch (err) {
      console.error("Failed to approve student:", err)
      showToast("Failed to approve student credentials. Please try again.", "error")
    } finally {
      setApprovingUids(prev => {
        const next = new Set(prev)
        next.delete(uid)
        return next
      })
    }
  }

  const handleApproveAll = async () => {
    if (isApprovingAll || pendingUsers.length === 0) return
    setIsApprovingAll(true)
    try {
      for (const u of pendingUsers) {
        await adminService.updateUserVerification(u.uid, true, adminUid, adminEmail)
      }
      setUsers(prev => prev.map(u => ({ ...u, collegeVerified: true })))
      setActionFeedback(`Approved all ${pendingUsers.length} pending verifications!`)
      showToast(`Approved all ${pendingUsers.length} pending verifications!`, "success")
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    } catch (err) {
      console.error("Failed to approve all students:", err)
      showToast("Failed to approve all students. Please try again.", "error")
    } finally {
      setIsApprovingAll(false)
    }
  }

  const handleApproveHelpRequest = async (req: VerificationHelpRequest) => {
    try {
      await adminService.updateUserVerification(req.userId, true, adminUid, adminEmail)
      await verificationHelpService.resolveHelpRequest(req.id!, "resolved", "Approved via admin escalation queue")
      setHelpRequests(prev => prev.filter(h => h.id !== req.id))
      setUsers(prev => prev.map(u => u.uid === req.userId ? { ...u, collegeVerified: true } : u))
      showToast(`Verified credentials for ${req.userName}!`, "success")
      triggerRefresh()
    } catch (e) {
      showToast("Failed to process help request.", "error")
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Student Verification Queue</h1>
            <span className="bg-amber-100 text-amber-800 text-xs font-bold px-2 py-0.5 rounded-full">
              {pendingUsers.length} Pending
            </span>
            {helpRequests.length > 0 && (
              <span className="bg-red-600 text-white text-xs font-bold px-2 py-0.5 rounded-full animate-pulse">
                {helpRequests.length} Urgent Help Requests
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500">
            Review and authenticate campus student credentials before unlocking ride hosting and booking
          </p>
        </div>

        {/* Tab Selection */}
        <div className="flex items-center gap-2 bg-gray-100 p-1 rounded-xl text-xs font-bold">
          <button
            onClick={() => setActiveTab("pending")}
            className={`px-3 py-1.5 rounded-lg transition-all ${
              activeTab === "pending" ? "bg-white text-black shadow-xs" : "text-gray-600 hover:text-black"
            }`}
          >
            Pending Verifications ({pendingUsers.length})
          </button>
          <button
            onClick={() => setActiveTab("escalations")}
            className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 ${
              activeTab === "escalations" ? "bg-red-600 text-white shadow-xs" : "text-gray-600 hover:text-black"
            }`}
          >
            <span>Urgent Help Requests</span>
            {helpRequests.length > 0 && (
              <span className="bg-white text-red-600 px-1.5 py-0.2 rounded-full text-[10px] font-black">
                {helpRequests.length}
              </span>
            )}
          </button>
        </div>

        {pendingUsers.length > 0 && activeTab === "pending" && (
          <button
            onClick={handleApproveAll}
            disabled={isApprovingAll}
            className="px-4 py-2 rounded-xl bg-[#25D366] hover:bg-[#20ba59] disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-bold flex items-center gap-1.5 shadow-sm transition-all cursor-pointer"
          >
            {isApprovingAll ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Approving All...</span>
              </>
            ) : (
              <>
                <MaterialIcon name="done_all" className="text-base" />
                <span>Approve All ({pendingUsers.length})</span>
              </>
            )}
          </button>
        )}
      </div>

      {/* Action Feedback */}
      {actionFeedback && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center gap-2 animate-in fade-in duration-150">
          <MaterialIcon name="check_circle" className="text-base text-emerald-600" />
          <span>{actionFeedback}</span>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
        <div className="bg-white p-4 sm:p-5 rounded-2xl border border-black/8 shadow-xs">
          <p className="text-[10px] sm:text-xs text-gray-400 font-bold uppercase tracking-wider">Awaiting Verification</p>
          <h3 className="text-xl sm:text-2xl font-black text-amber-700 mt-1">{pendingUsers.length}</h3>
          <p className="text-[11px] text-gray-500 mt-0.5 truncate">Pending student badge</p>
        </div>

        <div className="bg-white p-4 sm:p-5 rounded-2xl border border-black/8 shadow-xs">
          <p className="text-[10px] sm:text-xs text-gray-400 font-bold uppercase tracking-wider">Verified Total</p>
          <h3 className="text-xl sm:text-2xl font-black text-emerald-700 mt-1">
            {users.filter(u => u.collegeVerified).length}
          </h3>
          <p className="text-[11px] text-gray-500 mt-0.5 truncate">Authenticated students</p>
        </div>

        <div className="bg-white p-4 sm:p-5 rounded-2xl border border-black/8 shadow-xs col-span-2 sm:col-span-1">
          <p className="text-[10px] sm:text-xs text-gray-400 font-bold uppercase tracking-wider">Target SLA</p>
          <h3 className="text-xl sm:text-2xl font-black text-gray-900 mt-1">&lt; 4 Hours</h3>
          <p className="text-[11px] text-gray-500 mt-0.5 truncate">Campus safety requirement</p>
        </div>
      </div>

      {/* Search Input */}
      <div className="relative">
        <MaterialIcon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Filter pending students by name, email, department..."
          className="w-full pl-10 pr-4 py-2.5 text-xs bg-white rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black placeholder-gray-400 shadow-xs"
        />
      </div>

      {/* Pending Queue List or Escalations View */}
      {activeTab === "escalations" ? (
        <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden">
          {helpRequests.length === 0 ? (
            <div className="p-12 text-center space-y-2">
              <div className="w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mx-auto">
                <MaterialIcon name="check_circle" className="text-2xl" />
              </div>
              <h3 className="font-bold text-gray-900 text-sm">No Urgent Help Requests</h3>
              <p className="text-xs text-gray-500 max-w-sm mx-auto">
                All verification help escalation requests have been resolved.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {helpRequests.map((req) => (
                <div key={req.id} className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-gray-50/80 transition-colors">
                  <div className="flex items-start gap-3.5">
                    <div className="w-11 h-11 rounded-2xl bg-red-100 text-red-700 font-bold text-sm flex items-center justify-center shrink-0 mt-0.5">
                      <MaterialIcon name="emergency" className="text-xl" />
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <h4 className="font-semibold text-gray-900 text-sm">{req.userName}</h4>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-600 text-white">
                          URGENT HELP
                        </span>
                      </div>
                      <p className="text-xs text-gray-600 font-mono">{req.userEmail}</p>
                      <p className="text-xs text-gray-800 bg-amber-50 p-2 rounded-xl border border-amber-200/60 font-medium">
                        &quot;{req.reason}&quot;
                      </p>
                    </div>
                  </div>

                  <button
                    onClick={() => handleApproveHelpRequest(req)}
                    className="px-4 py-2 rounded-xl bg-[#25D366] hover:bg-[#20ba59] text-white text-xs font-bold flex items-center gap-1 shadow-sm transition-all cursor-pointer shrink-0"
                  >
                    <MaterialIcon name="verified" className="text-base" />
                    <span>Approve Credentials & Resolve</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-xs text-gray-500">
            <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
            Loading verification queue...
          </div>
        ) : pendingUsers.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <div className="w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mx-auto">
              <MaterialIcon name="verified" className="text-2xl" />
            </div>
            <h3 className="font-bold text-gray-900 text-sm">All Students Verified!</h3>
            <p className="text-xs text-gray-500 max-w-sm mx-auto">
              There are no pending verification requests in the queue right now. New student signups will appear here automatically.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {pendingUsers.map(user => (
              <div key={user.uid} className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-gray-50/80 transition-colors">
                <div className="flex items-start sm:items-center gap-3.5">
                  <div className="w-11 h-11 rounded-2xl bg-amber-100 text-amber-900 font-bold text-sm flex items-center justify-center shrink-0">
                    {user.name.charAt(0)}
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h4 className="font-semibold text-gray-900 text-sm">{user.name}</h4>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">
                        PENDING
                      </span>
                    </div>
                    <p className="text-xs text-gray-600 font-mono">{user.email}</p>
                    <p className="text-xs text-gray-500">
                      {user.department} • {user.year} • <span className="font-medium text-gray-700">{user.college}</span>
                    </p>
                  </div>
                </div>

                <div className="w-full sm:w-auto flex items-center justify-between sm:justify-end gap-2 pt-2 sm:pt-0 border-t sm:border-t-0 border-gray-100">
                  <button
                    onClick={() => setSelectedUser(user)}
                    className="flex-1 sm:flex-initial py-2 sm:py-1.5 px-3 rounded-xl border border-gray-200 hover:bg-gray-100 text-xs font-bold text-gray-700 transition-colors text-center cursor-pointer"
                  >
                    Inspect Profile
                  </button>

                  <button
                    onClick={(e) => handleApprove(user.uid, e)}
                    disabled={approvingUids.has(user.uid)}
                    className="px-4 py-1.5 rounded-xl bg-[#25D366] hover:bg-[#20ba59] disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-bold flex items-center gap-1 shadow-sm transition-all cursor-pointer"
                  >
                    {approvingUids.has(user.uid) ? (
                      <>
                        <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        <span>Approving...</span>
                      </>
                    ) : (
                      <>
                        <MaterialIcon name="check" className="text-base" />
                        <span>Approve ID</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>)}

      {/* User Detail Drawer */}
      <UserDetailModal
        user={selectedUser}
        onClose={() => setSelectedUser(null)}
        onToggleVerification={(uid) => {
          handleApprove(uid)
          setSelectedUser(null)
        }}
        onToggleRole={() => {}}
        onToggleStatus={() => {}}
      />
    </div>
  )
}
