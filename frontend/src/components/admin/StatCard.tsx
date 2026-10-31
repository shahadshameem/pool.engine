import { MaterialIcon } from "../common/MaterialIcon"

interface StatCardProps {
  title: string
  value: string | number
  subtext?: string
  icon: string
  trend?: {
    value: string
    positive?: boolean
  }
  badge?: string
  badgeColor?: string
  onClick?: () => void
}

export function StatCard({
  title,
  value,
  subtext,
  icon,
  trend,
  badge,
  badgeColor = "bg-gray-100 text-gray-700",
  onClick
}: StatCardProps) {
  return (
    <div
      onClick={onClick}
      className={`bg-white rounded-2xl p-3.5 sm:p-5 border border-black/8 shadow-xs transition-all hover:shadow-md active:scale-[0.99] ${
        onClick ? "cursor-pointer hover:border-black/20" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="space-y-0.5 sm:space-y-1 min-w-0">
          <p className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider truncate">{title}</p>
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <h3 className="text-xl sm:text-2xl font-black text-black tracking-tight">{value}</h3>
            {trend && (
              <span
                className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full flex items-center gap-0.5 ${
                  trend.positive
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
                }`}
              >
                <MaterialIcon
                  name={trend.positive ? "trending_up" : "trending_down"}
                  className="text-xs"
                />
                {trend.value}
              </span>
            )}
          </div>
          {subtext && <p className="text-[11px] text-gray-500 pt-0.5 truncate">{subtext}</p>}
        </div>

        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-[#F4F4F6] text-black flex items-center justify-center">
            <MaterialIcon name={icon} className="text-lg sm:text-xl" />
          </div>
          {badge && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${badgeColor} hidden sm:inline-block`}>
              {badge}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
