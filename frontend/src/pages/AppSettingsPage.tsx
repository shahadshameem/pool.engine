import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { MaterialIcon } from "../components/common/MaterialIcon"

export function AppSettingsPage() {
  const navigate = useNavigate()

  return (
    <MobileShell hideBottomNav hasStickyHeader className="flex flex-col min-h-screen bg-background">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 pt-[calc(0.875rem+env(safe-area-inset-top,0px))] pb-3.5 bg-background/95 backdrop-blur border-b border-border/40">
        <button
          onClick={() => navigate(-1)}
          className="h-9 w-9 rounded-full bg-muted flex items-center justify-center text-foreground hover:opacity-80 cursor-pointer"
          aria-label="Back"
        >
          <MaterialIcon name="arrow_back" className="text-[20px]" />
        </button>
        <h1 className="text-[17px] font-extrabold text-foreground">Appearance</h1>
        <div className="w-9" />
      </div>

      <div className="p-4 flex-1 space-y-4">
        <div className="px-1 space-y-0.5">
          <h2 className="text-[16px] font-extrabold text-foreground">Theme Preference</h2>
          <p className="text-[12px] text-muted-foreground">WayMate is permanently optimized for OLED dark mode.</p>
        </div>

        {/* Dark Mode Locked Card */}
        <div className="bg-card border border-border/60 rounded-[22px] p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3.5 min-w-0">
              <div className="h-10 w-10 rounded-full bg-[#C5FF00] text-black flex items-center justify-center shrink-0">
                <MaterialIcon name="dark_mode" className="text-[22px]" />
              </div>
              <div className="min-w-0">
                <p className="text-[15px] font-bold text-foreground truncate">Dark Mode (Always Active)</p>
                <p className="text-[12px] text-muted-foreground">OLED pure black with neon lime accents for battery efficiency</p>
              </div>
            </div>

            <div className="shrink-0 ml-3">
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold bg-[#C5FF00]/15 text-[#C5FF00] border border-[#C5FF00]/30">
                Active
              </span>
            </div>
          </div>
        </div>
      </div>
    </MobileShell>
  )
}
