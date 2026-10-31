import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { adminService, type AdminStats, type AdminReport, type AdminRide } from "../../services/admin/adminService"
import { useAdmin } from "../../contexts/AdminContext"
import { StatCard } from "../../components/admin/StatCard"
import { MaterialIcon } from "../../components/common/MaterialIcon"

export function AdminDashboardPage() {
  const { refreshTrigger } = useAdmin()
  const navigate = useNavigate()
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [recentRides, setRecentRides] = useState<AdminRide[]>([])
  const [recentReports, setRecentReports] = useState<AdminReport[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    async function loadData() {
      setLoading(true)
      try {
        const [statsData, ridesData, reportsData] = await Promise.all([
          adminService.getAdminStats(),
          adminService.getRides(),
          adminService.getReports()
        ])

        if (mounted) {
          setStats(statsData)
          setRecentRides(ridesData.slice(0, 5))
          setRecentReports(reportsData.slice(0, 4))
        }
      } catch (err) {
        console.error("Dashboard data load error:", err)
      } finally {
        if (mounted) setLoading(false)
      }
    }

    loadData()
    return () => { mounted = false }
  }, [refreshTrigger])

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-black border-t-[#C5FF00] rounded-full animate-spin" />
          <p className="text-xs text-gray-500 font-medium">Loading platform metrics...</p>
        </div>
      </div>
    )
  }

  const maxWeeklyRideCount = Math.max(...(stats?.weeklyRides.map(w => w.count) || [1]))

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Welcome Banner */}
      <div className="bg-black text-white rounded-3xl p-6 lg:p-8 relative overflow-hidden shadow-sm">
        <div className="absolute right-0 top-0 bottom-0 w-1/3 bg-gradient-to-l from-[#C5FF00]/15 to-transparent pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#C5FF00]" />
              <p className="text-xs font-semibold text-[#C5FF00] uppercase tracking-wider">Campus Operations Console</p>
            </div>
            <h1 className="text-2xl lg:text-3xl font-extrabold tracking-tight">
              Welcome back, Admin
            </h1>
            <p className="text-sm text-gray-400 max-w-xl">
              WayMate campus transit network is operating smoothly across College of Engineering Trivandrum (CET) and connected colleges.
            </p>
          </div>

          <div className="flex flex-wrap gap-2.5">
            <button
              onClick={() => navigate("/admin/verifications")}
              className="px-4 py-2.5 rounded-xl bg-[#C5FF00] hover:bg-[#B5EB00] text-black text-xs font-bold transition-all shadow-sm flex items-center gap-1.5"
            >
              <MaterialIcon name="how_to_reg" className="text-base" />
              <span>Verify Students ({stats?.pendingVerifications || 0})</span>
            </button>

            <button
              onClick={() => navigate("/admin/reports")}
              className="px-4 py-2.5 rounded-xl bg-white/10 hover:bg-white/20 text-white text-xs font-semibold transition-all flex items-center gap-1.5"
            >
              <MaterialIcon name="security" className="text-base text-red-400" />
              <span>Reports ({stats?.pendingReports || 0})</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <StatCard
          title="Total Registered Students"
          value={stats?.totalUsers || 0}
          subtext={`${stats?.verifiedUsers || 0} college verified`}
          icon="group"
          trend={{ value: "+18% this month", positive: true }}
          onClick={() => navigate("/admin/users")}
        />

        <StatCard
          title="Student Verification Rate"
          value={`${stats?.verificationRate || 0}%`}
          subtext={`${stats?.pendingVerifications || 0} pending approvals`}
          icon="verified"
          badge={stats?.pendingVerifications ? `${stats.pendingVerifications} Pending` : "100% Up to date"}
          badgeColor={stats?.pendingVerifications ? "bg-amber-100 text-amber-900" : "bg-green-100 text-green-900"}
          onClick={() => navigate("/admin/verifications")}
        />

        <StatCard
          title="Active Rides Today"
          value={stats?.activeRides || 0}
          subtext={`${stats?.completedRides || 0} completed rides total`}
          icon="directions_car"
          trend={{ value: "Peak hour", positive: true }}
          onClick={() => navigate("/admin/rides")}
        />

        <StatCard
          title="Active Cab Pools"
          value={stats?.totalCabPools || 0}
          subtext="Split-fare student groups"
          icon="local_taxi"
          onClick={() => navigate("/admin/cab-pools")}
        />
      </div>

      {/* Secondary Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div
          onClick={() => navigate("/admin/reports")}
          className="bg-white rounded-2xl p-5 border border-black/8 shadow-sm flex items-center justify-between cursor-pointer hover:border-black/20 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-red-50 text-red-600 flex items-center justify-center">
              <MaterialIcon name="warning" className="text-2xl" />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Safety & Moderation</p>
              <h4 className="text-xl font-bold text-gray-900">{stats?.pendingReports || 0} Open Incident Reports</h4>
              <p className="text-xs text-gray-500">Requires review by moderation staff</p>
            </div>
          </div>
          <MaterialIcon name="chevron_right" className="text-gray-400" />
        </div>

        <div
          onClick={() => navigate("/admin/dpdp")}
          className="bg-white rounded-2xl p-5 border border-black/8 shadow-sm flex items-center justify-between cursor-pointer hover:border-black/20 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
              <MaterialIcon name="gavel" className="text-2xl" />
            </div>
            <div>
              <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">DPDPA 2023 Compliance</p>
              <h4 className="text-xl font-bold text-gray-900">{stats?.pendingDataRequests || 0} Pending Data Requests</h4>
              <p className="text-xs text-gray-500">Access, Erasure & Grievance SLA</p>
            </div>
          </div>
          <MaterialIcon name="chevron_right" className="text-gray-400" />
        </div>
      </div>

      {/* Charts & Breakdown Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Weekly Ride Trends Bar Chart */}
        <div className="lg:col-span-2 bg-white rounded-2xl p-6 border border-black/8 shadow-sm space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold text-gray-900">Weekly Ride Volume</h3>
              <p className="text-xs text-gray-500">Campus trip creations over the past 7 days</p>
            </div>
            <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-[#C5FF00]/30 text-black">
              Daily Distribution
            </span>
          </div>

          {/* Clean CSS Bar Chart */}
          <div className="h-48 flex items-end justify-between gap-3 pt-4 border-b border-gray-100">
            {stats?.weeklyRides.map((w, idx) => {
              const heightPct = Math.max(15, Math.round((w.count / maxWeeklyRideCount) * 100))
              return (
                <div key={idx} className="flex-1 flex flex-col items-center gap-2 h-full justify-end group">
                  <div className="text-[10px] font-bold text-gray-700 opacity-0 group-hover:opacity-100 transition-opacity">
                    {w.count}
                  </div>
                  <div
                    style={{ height: `${heightPct}%` }}
                    className="w-full max-w-[42px] rounded-t-lg bg-black group-hover:bg-[#C5FF00] transition-colors"
                  />
                  <span className="text-xs font-medium text-gray-500 pb-1">{w.day}</span>
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-between text-xs text-gray-500">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-black" />
              Weekday Commute Hours (CET Kulathoor)
            </span>
            <span className="font-semibold text-gray-900">Total: 175 Trips</span>
          </div>
        </div>

        {/* Campus Distribution Card */}
        <div className="bg-white rounded-2xl p-6 border border-black/8 shadow-sm space-y-6">
          <div>
            <h3 className="font-bold text-gray-900">Campus Distribution</h3>
            <p className="text-xs text-gray-500">Active student registration share</p>
          </div>

          <div className="space-y-4">
            {stats?.collegeBreakdown.map((item, i) => (
              <div key={i} className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="font-medium text-gray-800">{item.name}</span>
                  <span className="font-bold text-gray-900">{item.count}</span>
                </div>
                <div className="w-full h-2 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full bg-black rounded-full"
                    style={{ width: `${Math.min(100, Math.round((item.count / (stats.totalUsers || 1)) * 100))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="pt-4 border-t border-gray-100 text-xs text-gray-500 space-y-1">
            <p className="font-medium text-gray-700">Hub: College of Engineering Trivandrum</p>
            <p>Routes connect CET Main Gate, Kulathoor, Kazhakoottam, Thampanoor & Technopark.</p>
          </div>
        </div>
      </div>

      {/* Recent Activity Sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Rides */}
        <div className="bg-white rounded-2xl p-6 border border-black/8 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold text-gray-900">Recent Rides Posted</h3>
              <p className="text-xs text-gray-500">Latest active trips offered by students</p>
            </div>
            <button
              onClick={() => navigate("/admin/rides")}
              className="text-xs font-semibold text-black hover:underline"
            >
              View All →
            </button>
          </div>

          <div className="space-y-3">
            {recentRides.map(ride => (
              <div
                key={ride.id}
                onClick={() => navigate("/admin/rides")}
                className="p-3.5 rounded-xl bg-gray-50 hover:bg-gray-100 transition-colors flex items-center justify-between cursor-pointer border border-gray-100"
              >
                <div className="space-y-1 min-w-0 pr-2">
                  <p className="text-sm font-semibold text-gray-900 truncate">
                    {ride.from} → {ride.to}
                  </p>
                  <p className="text-xs text-gray-500">
                    Host: <span className="font-medium text-gray-700">{ride.hostName}</span> • {ride.departureTime}
                  </p>
                </div>

                <div className="text-right shrink-0">
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${
                    ride.status === "cancelled" ? "bg-red-100 text-red-800" :
                    ride.status === "active" ? "bg-green-100 text-green-800" :
                    ride.status === "full" ? "bg-amber-100 text-amber-800" :
                    ride.status === "completed" ? "bg-blue-100 text-blue-800" :
                    "bg-gray-100 text-gray-800"
                  }`}>
                    {ride.status.toUpperCase()}
                  </span>
                  <p className="text-[11px] text-gray-400 mt-1">{ride.availableSeats} seats left</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Safety Reports */}
        <div className="bg-white rounded-2xl p-6 border border-black/8 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold text-gray-900">Recent Safety Incidents</h3>
              <p className="text-xs text-gray-500">Reports filed by riders or hosts</p>
            </div>
            <button
              onClick={() => navigate("/admin/reports")}
              className="text-xs font-semibold text-black hover:underline"
            >
              Manage Reports →
            </button>
          </div>

          <div className="space-y-3">
            {recentReports.length > 0 ? (
              recentReports.map(rep => (
                <div
                  key={rep.id}
                  onClick={() => navigate("/admin/reports")}
                  className="p-3.5 rounded-xl bg-gray-50 hover:bg-gray-100 transition-colors flex items-center justify-between cursor-pointer border border-gray-100"
                >
                  <div className="space-y-1 min-w-0 pr-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-red-100 text-red-800">
                        {rep.category.replace("_", " ")}
                      </span>
                      <span className="text-xs text-gray-500 font-mono truncate">{rep.id}</span>
                    </div>
                    <p className="text-xs text-gray-700 line-clamp-1">{rep.description}</p>
                  </div>

                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full capitalize shrink-0 ${
                    rep.status === "resolved" ? "bg-green-100 text-green-800" :
                    rep.status === "under_review" ? "bg-amber-100 text-amber-800" :
                    "bg-red-100 text-red-800"
                  }`}>
                    {rep.status.replace("_", " ")}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-center py-8 text-xs text-gray-500">
                <MaterialIcon name="verified_user" className="text-3xl text-green-500 mb-1" />
                <p>No open safety reports. All clear!</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
