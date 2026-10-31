import { useState } from "react"
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom"
import { useAdmin } from "../contexts/AdminContext"
import { MaterialIcon } from "../components/common/MaterialIcon"

export function AdminLayout() {
  const { isDevBypass, toggleDevBypass, adminEmail } = useAdmin()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const navItems = [
    { label: "Dashboard", path: "/admin", icon: "dashboard", exact: true, group: "ops" },
    { label: "Colleges & Campuses", path: "/admin/colleges", icon: "school", group: "ops" },
    { label: "Students & Users", path: "/admin/users", icon: "people", group: "ops" },
    { label: "Verification Queue", path: "/admin/verifications", icon: "verified", group: "ops" },
    { label: "WayMate Places", path: "/admin/places", icon: "place", group: "ops" },
    { label: "Rides Oversight", path: "/admin/rides", icon: "directions_car", group: "ops" },
    { label: "Cab Pools", path: "/admin/cab-pools", icon: "local_taxi", group: "ops" },
    { label: "Safety & Reports", path: "/admin/reports", icon: "report_problem", group: "compliance" },
    { label: "DPDPA Data Rights", path: "/admin/dpdp", icon: "gavel", group: "compliance" },
    { label: "Settings & Broadcast", path: "/admin/settings", icon: "settings", group: "compliance" },
  ]

  const getPageTitle = () => {
    const item = navItems.find(n => n.exact ? location.pathname === n.path : location.pathname.startsWith(n.path))
    return item ? item.label : "Admin Portal"
  }

  return (
    <div className="min-h-screen bg-[#F8F9FA] text-gray-900 flex font-sans">
      {/* Mobile Backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-xs lg:hidden transition-opacity"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar (Desktop + Mobile Drawer) */}
      <aside
        className={`fixed lg:sticky top-0 bottom-0 left-0 z-50 w-72 bg-black text-white flex flex-col justify-between transition-transform duration-250 ease-out border-r border-white/10 pt-[env(safe-area-inset-top,0px)] pb-[env(safe-area-inset-bottom,0px)] ${
          mobileMenuOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div>
          {/* Logo & Brand Header */}
          <div className="p-5 lg:p-6 border-b border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-[#C5FF00] text-black font-black flex items-center justify-center text-xl shadow-xs">
                W
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-extrabold text-lg text-white tracking-tight">WayMate</h1>
                  <span className="text-[10px] font-black bg-[#C5FF00] text-black px-1.5 py-0.5 rounded tracking-wider">
                    ADMIN
                  </span>
                </div>
                <p className="text-[11px] text-gray-400 font-medium">CET Campus Operations</p>
              </div>
            </div>

            <button
              onClick={() => setMobileMenuOpen(false)}
              className="lg:hidden w-8 h-8 rounded-full bg-white/10 text-gray-300 hover:text-white flex items-center justify-center cursor-pointer"
            >
              <MaterialIcon name="close" className="text-xl" />
            </button>
          </div>

          {/* Navigation Links */}
          <nav className="p-3.5 space-y-1 overflow-y-auto max-h-[calc(100vh-230px)]">
            <p className="px-3 pt-2 pb-1 text-[10px] font-extrabold text-gray-500 uppercase tracking-wider">
              Campus Operations
            </p>
            {navItems.filter(i => i.group === "ops").map(item => {
              const isActive = item.exact
                ? location.pathname === item.path
                : location.pathname.startsWith(item.path)

              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all active:scale-[0.98] ${
                    isActive
                      ? "bg-[#C5FF00] text-black shadow-xs"
                      : "text-gray-300 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  <MaterialIcon
                    name={item.icon}
                    className={`text-xl ${isActive ? "text-black" : "text-gray-400"}`}
                  />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}

            <p className="px-3 pt-4 pb-1 text-[10px] font-extrabold text-gray-500 uppercase tracking-wider">
              Compliance & Safety
            </p>
            {navItems.filter(i => i.group === "compliance").map(item => {
              const isActive = item.exact
                ? location.pathname === item.path
                : location.pathname.startsWith(item.path)

              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all active:scale-[0.98] ${
                    isActive
                      ? "bg-[#C5FF00] text-black shadow-xs"
                      : "text-gray-300 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  <MaterialIcon
                    name={item.icon}
                    className={`text-xl ${isActive ? "text-black" : "text-gray-400"}`}
                  />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </nav>
        </div>

        {/* Bottom Profile & Switcher */}
        <div className="p-4 border-t border-white/10 space-y-3 bg-black/50">
          {/* Status Indicator */}
          <div className="bg-white/5 rounded-xl p-2.5 border border-white/10 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${isDevBypass ? "bg-[#C5FF00]" : "bg-emerald-400 animate-pulse"}`} />
              <span className="text-gray-300 font-mono text-[11px]">
                {isDevBypass ? "Dev Preview Mode" : "Live Firestore"}
              </span>
            </div>
            {import.meta.env.DEV && window.location.hostname === "localhost" && (
              <button
                onClick={toggleDevBypass}
                title="Toggle Dev Simulation Mode"
                className="text-[11px] text-[#C5FF00] hover:underline font-medium cursor-pointer"
              >
                {isDevBypass ? "Live Mode" : "Dev Mode"}
              </button>
            )}
          </div>

          {/* Admin Email details */}
          <div className="px-1 text-xs text-gray-400 truncate">
            <span className="text-gray-500 text-[10px] block uppercase font-bold">Admin Account</span>
            <span className="text-gray-200 font-mono text-[11px]">{adminEmail || "admin@waymate.app"}</span>
          </div>

          {/* Return to Student App Button */}
          <button
            onClick={() => navigate("/home")}
            className="w-full py-2.5 px-3 rounded-xl bg-white/10 hover:bg-white/20 text-white text-xs font-bold flex items-center justify-center gap-2 transition-all active:scale-[0.98] cursor-pointer"
          >
            <MaterialIcon name="arrow_back" className="text-base text-[#C5FF00]" />
            <span>Switch to Student App</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top App Bar */}
        <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-black/8 px-4 lg:px-8 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] pb-3 flex items-center justify-between shadow-xs">
          <div className="flex items-center gap-2.5 sm:gap-3">
            <button
              onClick={() => setMobileMenuOpen(true)}
              className="lg:hidden p-2 rounded-xl text-gray-800 hover:bg-gray-100 active:scale-95 transition-all cursor-pointer"
              aria-label="Open menu"
            >
              <MaterialIcon name="menu" className="text-2xl" />
            </button>

            <div>
              <h2 className="text-base sm:text-lg lg:text-xl font-black text-gray-950 tracking-tight leading-tight">
                {getPageTitle()}
              </h2>
              <p className="text-[11px] text-gray-400 hidden sm:block font-medium">
                WayMate Central Administration • CET Campus Hub
              </p>
            </div>
          </div>

          {/* Header Right Actions */}
          <div className="flex items-center gap-2 sm:gap-3">
            {/* Quick Status Pill */}
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200 text-xs font-semibold text-emerald-800">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Campus Live</span>
            </div>

            {/* Quick Add Place Shortcut */}
            <button
              onClick={() => navigate("/admin/places")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-black hover:bg-neutral-800 text-[#C5FF00] text-xs font-bold transition-all shadow-xs active:scale-95 cursor-pointer"
            >
              <MaterialIcon name="add_location_alt" className="text-base text-[#C5FF00]" />
              <span className="hidden sm:inline">Places</span>
            </button>

            {/* Quick Verification Shortcut */}
            <button
              onClick={() => navigate("/admin/verifications")}
              className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#F4F4F6] hover:bg-gray-200 text-xs font-bold text-gray-800 transition-colors"
            >
              <MaterialIcon name="how_to_reg" className="text-base text-gray-700" />
              <span>Verifications</span>
            </button>

            {/* Switch to Student App (Mobile header shortcut) */}
            <button
              onClick={() => navigate("/home")}
              title="Return to Student View"
              className="p-1.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors cursor-pointer"
            >
              <MaterialIcon name="directions_car" className="text-lg" />
            </button>
          </div>
        </header>

        {/* Content Body with bottom padding for mobile bar */}
        <main className="flex-1 p-3.5 sm:p-5 lg:p-8 max-w-7xl w-full mx-auto pb-24 lg:pb-8">
          <Outlet />
        </main>
      </div>

      {/* Mobile Fixed Bottom Navigation Bar */}
      <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-40 bg-black/95 backdrop-blur-md border-t border-white/10 px-2 py-1.5 flex items-center justify-around shadow-2xl safe-area-bottom">
        <NavLink
          to="/admin"
          end
          className={({ isActive }) =>
            `flex flex-col items-center justify-center py-1 px-3 rounded-xl transition-all active:scale-95 ${
              isActive ? "text-[#C5FF00] font-black" : "text-gray-400 hover:text-white"
            }`
          }
        >
          <MaterialIcon name="dashboard" className="text-xl" />
          <span className="text-[10px] mt-0.5 tracking-tight font-medium">Overview</span>
        </NavLink>

        <NavLink
          to="/admin/verifications"
          className={({ isActive }) =>
            `flex flex-col items-center justify-center py-1 px-3 rounded-xl transition-all active:scale-95 ${
              isActive ? "text-[#C5FF00] font-black" : "text-gray-400 hover:text-white"
            }`
          }
        >
          <MaterialIcon name="verified" className="text-xl" />
          <span className="text-[10px] mt-0.5 tracking-tight font-medium">Verify</span>
        </NavLink>

        <NavLink
          to="/admin/places"
          className={({ isActive }) =>
            `flex flex-col items-center justify-center py-1 px-3 rounded-xl transition-all active:scale-95 ${
              isActive ? "text-[#C5FF00] font-black" : "text-gray-400 hover:text-white"
            }`
          }
        >
          <MaterialIcon name="place" className="text-xl" />
          <span className="text-[10px] mt-0.5 tracking-tight font-medium">Places</span>
        </NavLink>

        <NavLink
          to="/admin/rides"
          className={({ isActive }) =>
            `flex flex-col items-center justify-center py-1 px-3 rounded-xl transition-all active:scale-95 ${
              isActive ? "text-[#C5FF00] font-black" : "text-gray-400 hover:text-white"
            }`
          }
        >
          <MaterialIcon name="directions_car" className="text-xl" />
          <span className="text-[10px] mt-0.5 tracking-tight font-medium">Rides</span>
        </NavLink>

        <button
          onClick={() => setMobileMenuOpen(true)}
          className="flex flex-col items-center justify-center py-1 px-3 rounded-xl text-gray-400 hover:text-white transition-all active:scale-95 cursor-pointer"
        >
          <MaterialIcon name="menu" className="text-xl" />
          <span className="text-[10px] mt-0.5 tracking-tight font-medium">More</span>
        </button>
      </nav>
    </div>
  )
}
