import type { AdminUser } from "../../services/admin/adminService"
import { MaterialIcon } from "../common/MaterialIcon"

interface UserDetailModalProps {
  user: AdminUser | null
  onClose: () => void
  onToggleVerification: (uid: string, current: boolean) => void
  onToggleRole: (uid: string, currentRole?: string) => void
  onToggleStatus: (uid: string, currentStatus?: string) => void
  onUpdateGenderVerification?: (uid: string, status: "unverified" | "pending" | "verified" | "rejected") => void
  onUpdateAccountStatus?: (uid: string, status: "active" | "restricted" | "suspended") => void
}

export function UserDetailModal({
  user,
  onClose,
  onToggleVerification,
  onToggleRole,
  onToggleStatus,
  onUpdateGenderVerification,
  onUpdateAccountStatus
}: UserDetailModalProps) {
  if (!user) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div
        className="w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-black/10 overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 bg-gradient-to-r from-gray-900 to-black text-white relative">
          <button
            onClick={onClose}
            className="absolute top-5 right-5 text-gray-400 hover:text-white transition-colors"
          >
            <MaterialIcon name="close" className="text-xl" />
          </button>

          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-[#C5FF00] text-black font-bold text-xl flex items-center justify-center shadow-md">
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold">{user.name}</h2>
                {user.collegeVerified && (
                  <span className="bg-[#25D366]/20 text-[#25D366] text-xs font-semibold px-2 py-0.5 rounded-full flex items-center gap-1 border border-[#25D366]/30">
                    <MaterialIcon name="verified" className="text-xs" />
                    Verified
                  </span>
                )}
                {user.role === "admin" && (
                  <span className="bg-[#C5FF00] text-black text-xs font-bold px-2 py-0.5 rounded-full">
                    ADMIN
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-300 font-mono mt-0.5">{user.email}</p>
            </div>
          </div>
        </div>

        {/* Body Details */}
        <div className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Academic Info */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Academic & Gender Info</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">College</p>
                <p className="font-medium text-gray-900 line-clamp-1">{user.college}</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Department</p>
                <p className="font-medium text-gray-900 line-clamp-1">{user.department}</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Year / Batch</p>
                <p className="font-medium text-gray-900">{user.year}</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Gender & Verification</p>
                <p className="font-medium text-gray-900 capitalize">
                  {user.gender || "Not specified"} ({user.genderVerificationStatus || "unverified"})
                </p>
              </div>
            </div>
          </div>

          {/* Contact & Platform Activity */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Platform Activity</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Phone</p>
                <p className="font-medium text-gray-900">{user.phone || "No phone linked"}</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Account Access</p>
                <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded-full mt-0.5 ${
                  user.accountStatus === "suspended" || user.status === "suspended" ? "bg-red-100 text-red-800" :
                  user.accountStatus === "restricted" ? "bg-amber-100 text-amber-900" :
                  "bg-green-100 text-green-800"
                }`}>
                  {user.accountStatus || user.status || "active"}
                </span>
              </div>
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Rides Hosted</p>
                <p className="font-medium text-gray-900">{user.ridesHostedCount || 0} rides</p>
              </div>
              <div className="bg-gray-50 p-3 rounded-xl border border-gray-100">
                <p className="text-xs text-gray-500">Rides Joined</p>
                <p className="font-medium text-gray-900">{user.ridesJoinedCount || 0} trips</p>
              </div>
            </div>
          </div>

          {/* User UID */}
          <div className="bg-gray-50 p-3 rounded-xl border border-gray-100 text-xs">
            <span className="text-gray-500">UID: </span>
            <span className="font-mono text-gray-700 select-all">{user.uid}</span>
          </div>

          {/* Administration Actions */}
          <div className="space-y-3 pt-2 border-t border-gray-100">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Administrative Controls</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <button
                onClick={() => onToggleVerification(user.uid, user.collegeVerified)}
                className={`py-2.5 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all ${
                  user.collegeVerified
                    ? "bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-200"
                    : "bg-[#25D366] hover:bg-[#20ba59] text-white shadow-sm"
                }`}
              >
                <MaterialIcon name={user.collegeVerified ? "cancel" : "verified"} className="text-base" />
                {user.collegeVerified ? "Revoke Verification" : "Approve College ID"}
              </button>

              <button
                onClick={() => onToggleRole(user.uid, user.role)}
                className="py-2.5 px-3 rounded-xl text-xs font-semibold border border-gray-200 hover:bg-gray-50 text-gray-800 flex items-center justify-center gap-1.5 transition-all"
              >
                <MaterialIcon name="admin_panel_settings" className="text-base" />
                {user.role === "admin" ? "Demote to Student" : "Promote to Admin"}
              </button>

              {onUpdateGenderVerification && (
                <button
                  onClick={() => onUpdateGenderVerification(user.uid, user.genderVerificationStatus === "verified" ? "rejected" : "verified")}
                  className="py-2.5 px-3 rounded-xl text-xs font-semibold bg-blue-50 hover:bg-blue-100 text-blue-900 border border-blue-200 flex items-center justify-center gap-1.5 transition-all"
                >
                  <MaterialIcon name="verified_user" className="text-base" />
                  {user.genderVerificationStatus === "verified" ? "Reject Gender Verification" : "Verify Gender"}
                </button>
              )}

              {onUpdateAccountStatus && (
                <button
                  onClick={() => onUpdateAccountStatus(user.uid, user.accountStatus === "restricted" ? "active" : "restricted")}
                  className="py-2.5 px-3 rounded-xl text-xs font-semibold bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-200 flex items-center justify-center gap-1.5 transition-all"
                >
                  <MaterialIcon name="do_not_disturb_on" className="text-base" />
                  {user.accountStatus === "restricted" ? "Restore Ride Access" : "Restrict Ride Access"}
                </button>
              )}

              <button
                onClick={() => onToggleStatus(user.uid, user.status)}
                className={`py-2.5 px-3 rounded-xl text-xs font-semibold col-span-1 sm:col-span-2 flex items-center justify-center gap-1.5 transition-all ${
                  user.status === "suspended" || user.accountStatus === "suspended"
                    ? "bg-green-50 hover:bg-green-100 text-green-800 border border-green-200"
                    : "bg-red-50 hover:bg-red-100 text-red-800 border border-red-200"
                }`}
              >
                <MaterialIcon name={user.status === "suspended" || user.accountStatus === "suspended" ? "lock_open" : "block"} className="text-base" />
                {user.status === "suspended" || user.accountStatus === "suspended" ? "Lift Account Suspension" : "Suspend Account (Violation)"}
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
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
