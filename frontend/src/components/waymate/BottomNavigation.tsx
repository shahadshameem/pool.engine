import { useLocation, useNavigate } from "react-router-dom"
import { cn } from "../../lib/utils"
import { MaterialIcon } from "../common/MaterialIcon"

export interface BottomNavigationProps {
  hide?: boolean
}

export function BottomNavigation({ hide = false }: BottomNavigationProps) {
  const location = useLocation()
  const navigate = useNavigate()

  if (hide) return null

  const navItems = [
    { label: "Home", iconName: "home", path: "/home" },
    { label: "My Trips", iconName: "directions_car", path: "/rides" },
    { label: "Profile", iconName: "person", path: "/profile" },
  ]

  return (
    <div className="fixed bottom-0 left-1/2 -translate-x-1/2 z-50 w-full max-w-md bg-background/95 backdrop-blur border-t border-border/40 px-6 py-2 pb-[calc(8px+env(safe-area-inset-bottom,0px))] pl-[calc(1.5rem+env(safe-area-inset-left,0px))] pr-[calc(1.5rem+env(safe-area-inset-right,0px))]">
      <nav className="flex h-[58px] w-full items-center justify-between">
        {navItems.map((item) => {
          const isActive = item.label === "Home"
            ? (location.pathname === "/" || location.pathname === "/home")
            : item.label === "My Trips"
              ? (location.pathname === "/rides" || (location.pathname.startsWith("/rides/") && !location.pathname.includes("search") && !location.pathname.includes("create")))
              : location.pathname.startsWith(item.path)

          return (
            <button
              key={item.label}
              onClick={() => {
                if (location.pathname !== item.path) {
                  navigate(item.path, { replace: true })
                }
              }}
              aria-label={item.label}
              className="flex flex-1 flex-col items-center justify-center space-y-1 transition-all group focus:outline-none cursor-pointer"
            >
              {/* Icon Container with EDEX Lime Active Pill */}
              <div
                className={cn(
                  "flex h-[36px] w-[54px] items-center justify-center rounded-full transition-all duration-200",
                  isActive
                    ? "bg-[#C5FF00] text-black"
                    : "text-muted-foreground group-hover:text-foreground"
                )}
              >
                <MaterialIcon name={item.iconName} className="text-[24px]" />
              </div>

              {/* Text Label Below Icon */}
              <span
                className={cn(
                  "text-[12px] transition-colors leading-none tracking-tight",
                  isActive ? "font-bold text-foreground" : "font-medium text-muted-foreground"
                )}
              >
                {item.label}
              </span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}