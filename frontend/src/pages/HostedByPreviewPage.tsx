import { MobileShell } from "../components/layout/MobileShell"
import { HostInfoCard } from "../components/common/HostInfoCard"

export function HostedByPreviewPage() {
  return (
    <MobileShell hideBottomNav className="bg-[#F8F9FA] min-h-screen p-5 space-y-6">
      <h1 className="text-xl font-bold text-[#111111] pt-2">Hosted By Component Preview</h1>

      {/* Floating Card Spec (16px border radius, white card, no drop shadow) */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold text-[#777777]">Floating Card Variant (16px border-radius)</h2>
        <HostInfoCard
          hostName="Shahad Shameem"
          college="CET"
          department="ECE"
          year="4th Year"
          variant="floating"
        />
      </div>

      {/* Flush Card Spec (0px border radius) */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold text-[#777777]">Flush Variant (0px border-radius)</h2>
        <div className="bg-white border-y border-[#E8E8E8]">
          <HostInfoCard
            hostName="Shahad Shameem"
            college="CET"
            department="ECE"
            year="4th Year"
            variant="flush"
          />
        </div>
      </div>
    </MobileShell>
  )
}
