import { Phone, MessageCircle } from "lucide-react"
import { normalizePhoneForWhatsApp, formatBranchYear } from "../../utils/formatters"
import { cn } from "../../lib/utils"

export interface HostInfoCardProps {
  hostName?: string
  college?: string
  department?: string
  year?: string
  hostVerified?: boolean
  contactPhone?: string | null
  showContactButtons?: boolean
  className?: string
  variant?: "floating" | "flush"
}

export function HostInfoCard({
  hostName = "Shahad Shameem",
  college = "CET",
  department = "ECE",
  year = "4th Year",
  contactPhone = null,
  showContactButtons = false,
  className = "",
  variant = "floating"
}: HostInfoCardProps) {
  const initial = hostName ? hostName.trim().charAt(0).toUpperCase() : "S"

  // Build secondary text: e.g. "ECE • 4th Year"
  const subtitleText = formatBranchYear(department, year, college || "CET")

  const whatsappUrl = contactPhone ? normalizePhoneForWhatsApp(contactPhone) : null

  return (
    <div
      className={cn(
        "bg-card border border-border/60 p-5 shadow-xs space-y-3",
        variant === "flush" ? "rounded-none border-x-0" : "rounded-[28px]",
        className
      )}
    >
      {/* Header Label */}
      <span className="text-[13px] font-normal text-muted-foreground block leading-none">
        Hosted by
      </span>

      {/* Avatar + Text Row */}
      <div className="flex items-center space-x-3">
        <div className="h-12 w-12 rounded-full bg-muted border border-border/40 flex items-center justify-center text-[17px] font-bold text-foreground shrink-0 uppercase">
          {initial}
        </div>

        {/* Text Block: Name & Department/Year */}
        <div className="flex flex-col justify-center min-w-0 flex-1 space-y-0.5">
          {/* Primary Text: Name */}
          <h3 className="text-[17px] font-bold text-foreground truncate leading-tight">
            {hostName}
          </h3>

          {/* Secondary Text: Department/Year */}
          <p className="text-[13px] font-normal text-muted-foreground truncate leading-tight">
            {subtitleText}
          </p>
        </div>
      </div>

      {/* Optional Contact Buttons */}
      {showContactButtons && (
        <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-border/40">
          {contactPhone ? (
            <>
              <a
                href={`tel:${contactPhone}`}
                className="flex items-center justify-center space-x-2 py-2.5 px-3 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-[13px] font-bold hover:bg-emerald-500/20 transition-colors"
              >
                <Phone className="h-4 w-4" />
                <span>Call</span>
              </a>
              <a
                href={whatsappUrl || "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center space-x-2 py-2.5 px-3 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-[13px] font-bold hover:bg-emerald-500/20 transition-colors"
              >
                <MessageCircle className="h-4 w-4" />
                <span>WhatsApp</span>
              </a>
            </>
          ) : (
            <div className="col-span-2 text-center py-2 px-3 rounded-xl bg-muted border border-border/40 text-[11px] font-medium text-muted-foreground">
              📞 Contact details available after host accepts request
            </div>
          )}
        </div>
      )}
    </div>
  )
}
