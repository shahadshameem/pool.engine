import { useEffect, useState, useMemo } from "react"
import { adminService, type AdminUser } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { UserDetailModal } from "../../components/admin/UserDetailModal"
import { MaterialIcon } from "../../components/common/MaterialIcon"

export function AdminUsersPage() {
  const { adminUid, adminEmail, refreshTrigger, triggerRefresh } = useAdmin()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null)

  // Filters
  const [searchQuery, setSearchQuery] = useState("")
  const [filterCollege, setFilterCollege] = useState("all")
  const [filterVerification, setFilterVerification] = useState("all")
  const [filterRole, setFilterRole] = useState("all")
  const [actionFeedback, setActionFeedback] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    async function fetchUsers() {
      setLoading(true)
      try {
        const data = await adminService.getUsers()
        if (mounted) setUsers(data)
      } catch (err) {
        console.error("Failed to load users:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    fetchUsers()
    return () => { mounted = false }
  }, [refreshTrigger])

  const filteredUsers = useMemo(() => {
    return users.filter(user => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch = !q || (
        user.name.toLowerCase().includes(q) ||
        user.email.toLowerCase().includes(q) ||
        user.department.toLowerCase().includes(q) ||
        user.college.toLowerCase().includes(q)
      )

      const matchesCollege = filterCollege === "all" || user.college.toLowerCase().includes(filterCollege.toLowerCase())
      const matchesVerification = filterVerification === "all" || (
        filterVerification === "verified" ? user.collegeVerified : !user.collegeVerified
      )
      const matchesRole = filterRole === "all" || (
        filterRole === "admin" ? user.role === "admin" : user.role !== "admin"
      )

      return matchesSearch && matchesCollege && matchesVerification && matchesRole
    })
  }, [users, searchQuery, filterCollege, filterVerification, filterRole])

  const handleToggleVerification = async (uid: string, current: boolean) => {
    const success = await adminService.updateUserVerification(uid, !current, adminUid, adminEmail)
    if (success) {
      setUsers(prev => prev.map(u => u.uid === uid ? { ...u, collegeVerified: !current } : u))
      if (selectedUser?.uid === uid) {
        setSelectedUser(prev => prev ? { ...prev, collegeVerified: !current } : null)
      }
      setActionFeedback(`Student verification ${!current ? "granted" : "revoked"} successfully.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  const handleToggleRole = async (uid: string, currentRole?: string) => {
    const newRole = currentRole === "admin" ? "user" : "admin"
    const success = await adminService.updateUserRole(uid, newRole, adminUid, adminEmail)
    if (success) {
      setUsers(prev => prev.map(u => u.uid === uid ? { ...u, role: newRole, admin: newRole === "admin" } : u))
      if (selectedUser?.uid === uid) {
        setSelectedUser(prev => prev ? { ...prev, role: newRole, admin: newRole === "admin" } : null)
      }
      setActionFeedback(`User role changed to ${newRole}.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  const handleToggleStatus = async (uid: string, currentStatus?: string) => {
    const newStatus = currentStatus === "suspended" ? "active" : "suspended"
    const success = await adminService.updateUserStatus(uid, newStatus, adminUid, adminEmail)
    if (success) {
      setUsers(prev => prev.map(u => u.uid === uid ? { ...u, status: newStatus, accountStatus: newStatus } : u))
      if (selectedUser?.uid === uid) {
        setSelectedUser(prev => prev ? { ...prev, status: newStatus, accountStatus: newStatus } : null)
      }
      setActionFeedback(`Account marked as ${newStatus}.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  const handleUpdateGenderVerification = async (uid: string, status: "unverified" | "pending" | "verified" | "rejected") => {
    const success = await adminService.updateGenderVerificationStatus(uid, status, adminUid, adminEmail)
    if (success) {
      setUsers(prev => prev.map(u => u.uid === uid ? { ...u, genderVerificationStatus: status } : u))
      if (selectedUser?.uid === uid) {
        setSelectedUser(prev => prev ? { ...prev, genderVerificationStatus: status } : null)
      }
      setActionFeedback(`Gender verification status updated to ${status}.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  const handleUpdateAccountStatus = async (uid: string, status: "active" | "restricted" | "suspended") => {
    const success = await adminService.updateUserAccountStatus(uid, status, adminUid, adminEmail)
    if (success) {
      setUsers(prev => prev.map(u => u.uid === uid ? { ...u, accountStatus: status } : u))
      if (selectedUser?.uid === uid) {
        setSelectedUser(prev => prev ? { ...prev, accountStatus: status } : null)
      }
      setActionFeedback(`Account status updated to ${status}.`)
      setTimeout(() => setActionFeedback(null), 3000)
      triggerRefresh()
    }
  }

  const exportCSV = () => {
    const headers = ["UID", "Name", "Email", "College", "Department", "Year", "Verified", "Role", "Status"]
    const rows = filteredUsers.map(u => [
      `"${u.uid}"`,
      `"${u.name}"`,
      `"${u.email}"`,
      `"${u.college}"`,
      `"${u.department}"`,
      `"${u.year}"`,
      u.collegeVerified ? "YES" : "NO",
      u.role || "user",
      u.status || "active"
    ])

    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n")
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement("a")
    link.setAttribute("href", encodedUri)
    link.setAttribute("download", `waymate_students_${new Date().toISOString().split("T")[0]}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="space-y-6">
      {/* Page Title & Export Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Student Directory & Roles</h1>
          <p className="text-xs text-gray-500">Manage student profiles, college verifications, and administrative access</p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={exportCSV}
            className="px-4 py-2 rounded-xl bg-white border border-gray-200 hover:bg-gray-50 text-gray-800 text-xs font-semibold flex items-center gap-1.5 transition-all shadow-xs"
          >
            <MaterialIcon name="download" className="text-base text-gray-600" />
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {/* Action Notification Banner */}
      {actionFeedback && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center gap-2 animate-in fade-in duration-150">
          <MaterialIcon name="check_circle" className="text-base text-emerald-600" />
          <span>{actionFeedback}</span>
        </div>
      )}

      {/* Search and Filters Bar */}
      <div className="bg-white p-4 rounded-2xl border border-black/8 shadow-sm space-y-3">
        <div className="flex flex-col md:flex-row gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <MaterialIcon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-lg" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search by student name, college email, department..."
              className="w-full pl-10 pr-4 py-2 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black placeholder-gray-400"
            />
          </div>

          {/* College Filter */}
          <select
            value={filterCollege}
            onChange={e => setFilterCollege(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">All Campuses</option>
            <option value="College of Engineering Trivandrum">CET Trivandrum</option>
            <option value="Barton Hill">GEC Barton Hill</option>
          </select>

          {/* Verification Filter */}
          <select
            value={filterVerification}
            onChange={e => setFilterVerification(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">Verification: All</option>
            <option value="verified">Verified Only</option>
            <option value="unverified">Pending / Unverified</option>
          </select>

          {/* Role Filter */}
          <select
            value={filterRole}
            onChange={e => setFilterRole(e.target.value)}
            className="py-2 px-3 text-xs bg-gray-50 rounded-xl border border-gray-200 focus:outline-none focus:ring-1 focus:ring-black font-medium text-gray-700"
          >
            <option value="all">Role: All</option>
            <option value="admin">Administrators</option>
            <option value="user">Students</option>
          </select>
        </div>

        <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
          <span>Showing <strong className="text-gray-900">{filteredUsers.length}</strong> of {users.length} students</span>
          {(searchQuery || filterCollege !== "all" || filterVerification !== "all" || filterRole !== "all") && (
            <button
              onClick={() => {
                setSearchQuery("")
                setFilterCollege("all")
                setFilterVerification("all")
                setFilterRole("all")
              }}
              className="text-black font-semibold hover:underline"
            >
              Reset Filters
            </button>
          )}
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white rounded-2xl border border-black/8 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-xs text-gray-500">
            <div className="w-8 h-8 border-3 border-black border-t-[#C5FF00] rounded-full animate-spin mx-auto mb-2" />
            Loading student records...
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="p-12 text-center text-xs text-gray-500 space-y-2">
            <MaterialIcon name="person_search" className="text-4xl text-gray-300" />
            <p className="font-semibold text-gray-700">No students matched the filter criteria</p>
            <p>Try clearing filters or searching with a different keyword</p>
          </div>
        ) : (
          <>
            {/* Mobile Cards View (md:hidden) */}
            <div className="md:hidden divide-y divide-gray-100">
              {filteredUsers.map(user => (
                <div key={user.uid} className="p-4 space-y-3 hover:bg-gray-50/50 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-10 h-10 rounded-full bg-black text-[#C5FF00] font-black text-sm flex items-center justify-center shrink-0">
                        {user.name.charAt(0)}
                      </div>
                      <div className="min-w-0">
                        <h4 className="font-bold text-gray-950 text-sm truncate">{user.name}</h4>
                        <p className="text-[11px] text-gray-500 font-mono truncate">{user.email}</p>
                      </div>
                    </div>

                    {user.role === "admin" ? (
                      <span className="px-2 py-0.5 rounded bg-black text-[#C5FF00] text-[10px] font-black tracking-wider shrink-0">
                        ADMIN
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[10px] font-bold shrink-0">
                        STUDENT
                      </span>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-gray-600 font-medium">
                      {user.department} • {user.year}
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <div className="flex items-center gap-2">
                      {user.collegeVerified ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <MaterialIcon name="verified" className="text-xs" />
                          Verified ID
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-50 text-amber-800 border border-amber-200">
                          <MaterialIcon name="schedule" className="text-xs" />
                          Pending ID
                        </span>
                      )}

                      <span className="text-[11px] text-gray-500 flex items-center gap-1">
                        <span className={`w-2 h-2 rounded-full ${user.status === "suspended" ? "bg-red-500" : "bg-emerald-500"}`} />
                        {user.status === "suspended" ? "Suspended" : "Active"}
                      </span>
                    </div>

                    <button
                      onClick={() => setSelectedUser(user)}
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
                  <th className="py-3.5 px-4">Student</th>
                  <th className="py-3.5 px-4">Academic Dept & College</th>
                  <th className="py-3.5 px-4">Year</th>
                  <th className="py-3.5 px-4">College Verified</th>
                  <th className="py-3.5 px-4">Role</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredUsers.map(user => (
                  <tr key={user.uid} className="hover:bg-gray-50/80 transition-colors">
                    {/* Student Info */}
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-black text-[#C5FF00] font-bold text-xs flex items-center justify-center shrink-0">
                          {user.name.charAt(0)}
                        </div>
                        <div className="min-w-0">
                          <p className="font-semibold text-gray-900 truncate">{user.name}</p>
                          <p className="text-[11px] text-gray-500 font-mono truncate">{user.email}</p>
                        </div>
                      </div>
                    </td>

                    {/* Academic */}
                    <td className="py-3.5 px-4 text-gray-700">
                      <p className="font-medium text-gray-900 line-clamp-1">{user.department}</p>
                      <p className="text-[11px] text-gray-500 line-clamp-1">{user.college}</p>
                    </td>

                    {/* Year */}
                    <td className="py-3.5 px-4 text-gray-700 font-medium">
                      {user.year}
                    </td>

                    {/* College Verified */}
                    <td className="py-3.5 px-4">
                      {user.collegeVerified ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <MaterialIcon name="verified" className="text-xs" />
                          Verified
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                          <MaterialIcon name="schedule" className="text-xs" />
                          Pending ID
                        </span>
                      )}
                    </td>

                    {/* Role */}
                    <td className="py-3.5 px-4">
                      {user.role === "admin" ? (
                        <span className="inline-block px-2 py-0.5 rounded bg-black text-[#C5FF00] text-[10px] font-extrabold tracking-wider">
                          ADMIN
                        </span>
                      ) : (
                        <span className="inline-block px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[10px] font-semibold">
                          STUDENT
                        </span>
                      )}
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4">
                      <span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${
                        user.status === "suspended" ? "bg-red-500" : "bg-green-500"
                      }`} />
                      <span className="text-gray-700 capitalize">{user.status || "Active"}</span>
                    </td>

                    {/* Actions */}
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => setSelectedUser(user)}
                          title="View Profile Details"
                          className="p-1.5 rounded-lg text-gray-700 hover:bg-gray-200 transition-colors"
                        >
                          <MaterialIcon name="visibility" className="text-base" />
                        </button>

                        <button
                          onClick={() => handleToggleVerification(user.uid, user.collegeVerified)}
                          title={user.collegeVerified ? "Revoke Verification" : "Approve College ID"}
                          className={`p-1.5 rounded-lg transition-colors ${
                            user.collegeVerified
                              ? "text-amber-700 hover:bg-amber-100"
                              : "text-emerald-700 hover:bg-emerald-100"
                          }`}
                        >
                          <MaterialIcon name={user.collegeVerified ? "do_not_disturb_on" : "check_circle"} className="text-base" />
                        </button>
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

      {/* User Detail Modal */}
      <UserDetailModal
        user={selectedUser}
        onClose={() => setSelectedUser(null)}
        onToggleVerification={handleToggleVerification}
        onToggleRole={handleToggleRole}
        onToggleStatus={handleToggleStatus}
        onUpdateGenderVerification={handleUpdateGenderVerification}
        onUpdateAccountStatus={handleUpdateAccountStatus}
      />
    </div>
  )
}
