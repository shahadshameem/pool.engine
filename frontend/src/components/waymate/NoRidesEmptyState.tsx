import { Plus } from "lucide-react"

interface NoRidesEmptyStateProps {
  onOfferRide: () => void
}

export function NoRidesEmptyState({ onOfferRide }: NoRidesEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-4 px-2 text-center space-y-6">

      {/* Friendly Illustration matching target reference */}
      <div className="w-full max-w-[280px] mx-auto py-2">
        <svg viewBox="0 0 320 160" className="w-full h-auto overflow-visible select-none">
          {/* Soft Sun / Glow */}
          <circle cx="160" cy="72" r="58" className="fill-muted/60" />

          {/* Background Clouds */}
          <path d="M 75 75 Q 85 62 100 65 Q 112 55 125 65 Q 135 70 135 78 Z" className="fill-muted" opacity="0.8" />
          <path d="M 195 72 Q 205 60 218 63 Q 230 52 242 63 Q 252 68 252 76 Z" className="fill-muted" opacity="0.8" />

          {/* Birds */}
          <path d="M 220 54 Q 224 49 228 54 Q 232 49 236 54" fill="none" stroke="currentColor" className="text-muted-foreground" strokeWidth="1.4" strokeLinecap="round" />
          <path d="M 228 63 Q 232 59 235 63 Q 238 59 241 63" fill="none" stroke="currentColor" className="text-muted-foreground" strokeWidth="1.2" strokeLinecap="round" />

          {/* Rolling Hills Background */}
          <path d="M 50 120 C 90 105 130 115 160 120 C 190 125 240 100 280 120 L 280 145 L 50 145 Z" className="fill-muted/40" />
          <path d="M 40 130 C 100 115 170 135 300 125 L 300 145 L 40 145 Z" className="fill-muted/80" />

          {/* Winding Dashed Road */}
          <path d="M 105 145 C 130 135, 145 118, 160 92 C 163 85, 160 78, 160 75" fill="none" className="stroke-border" strokeWidth="32" strokeLinecap="round" />
          <path d="M 112 142 C 132 133, 148 116, 160 92 C 162 87, 160 80, 160 76" fill="none" stroke="#C5FF00" strokeWidth="2.5" strokeDasharray="5 5" strokeLinecap="round" />

          {/* Base Ground Line */}
          <path d="M 60 122 Q 160 116 260 122" fill="none" stroke="currentColor" className="text-border" strokeWidth="1.5" strokeLinecap="round" />

          {/* Left Tree */}
          <line x1="110" y1="102" x2="110" y2="122" stroke="currentColor" className="text-muted-foreground" strokeWidth="2" strokeLinecap="round" />
          <ellipse cx="110" cy="94" rx="11" ry="18" className="fill-muted stroke-border" strokeWidth="1" />

          {/* Right Tree */}
          <line x1="210" y1="102" x2="210" y2="122" stroke="currentColor" className="text-muted-foreground" strokeWidth="2" strokeLinecap="round" />
          <ellipse cx="210" cy="94" rx="11" ry="18" className="fill-muted stroke-border" strokeWidth="1" />

          {/* Radiating Rays / Sparkles around Pin */}
          <line x1="124" y1="46" x2="136" y2="52" stroke="#C5FF00" strokeWidth="3.5" strokeLinecap="round" />
          <line x1="140" y1="28" x2="147" y2="39" stroke="#C5FF00" strokeWidth="3.5" strokeLinecap="round" />
          <line x1="180" y1="28" x2="173" y2="39" stroke="#C5FF00" strokeWidth="3.5" strokeLinecap="round" />
          <line x1="196" y1="46" x2="184" y2="52" stroke="#C5FF00" strokeWidth="3.5" strokeLinecap="round" />

          {/* Map Pin with + */}
          <g transform="translate(160, 68)">
            {/* Pin Drop Shadow */}
            <ellipse cx="0" cy="24" rx="8" ry="3" fill="#000000" opacity="0.15" />

            {/* Pin Body */}
            <path
              d="M 0 22 C -18 -6 -24 -16 -24 -30 A 24 24 0 1 1 24 -30 C 24 -16 18 -6 0 22 Z"
              fill="#C5FF00"
              stroke="#000000"
              strokeWidth="1.5"
            />
            {/* Inner Circle */}
            <circle cx="0" cy="-30" r="12" fill="#000000" />
            {/* Plus Icon inside Pin */}
            <path
              d="M 0 -36 V -24 M -6 -30 H 6"
              stroke="#C5FF00"
              strokeWidth="3.2"
              strokeLinecap="round"
            />
          </g>
        </svg>
      </div>

      {/* Single-line Headline: "No rides found." */}
      <h3 className="text-[20px] sm:text-[22px] font-extrabold tracking-tight text-foreground leading-none">
        No rides <span className="text-[#C5FF00]">found.</span>
      </h3>

      {/* Full-width Lime Action Button */}
      <button
        type="button"
        onClick={onOfferRide}
        className="w-full h-14 bg-[#C5FF00] text-black font-extrabold text-[16px] rounded-full hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer shadow-sm flex items-center justify-center space-x-2"
      >
        <Plus className="h-5 w-5 stroke-[3]" />
        <span>Offer a Ride</span>
      </button>

    </div>
  )
}
