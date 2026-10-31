import React from "react"
import { MapPin, ChevronDown, Users } from "lucide-react"
import { NotificationCenter } from "./NotificationCenter"

interface HomeDashboardHeroProps {
  greeting?: string
  userName?: string
  locationName?: string
  onLocationClick?: () => void
}

export const HomeDashboardHero: React.FC<HomeDashboardHeroProps> = ({
  greeting = "Good morning",
  userName = "Shahad",
  locationName = "CET",
  onLocationClick,
}) => {
  const avatarInitial = userName.charAt(0).toUpperCase() || "S"

  return (
    <header className="w-full space-y-4">
      {/* 1. HEADER SECTION */}
      <div className="flex items-center justify-between px-1 py-2 sm:px-2">
        {/* Left side: Avatar + Greeting + Location */}
        <div className="flex items-center space-x-3.5">
          {/* User Avatar with subtle border */}
          <div className="relative flex items-center justify-center shrink-0">
            <div className="h-12 w-12 rounded-full bg-[#E5E5EA] border-2 border-[#1D1D1F]/15 flex items-center justify-center font-bold text-[20px] text-[#1D1D1F]">
              {avatarInitial}
            </div>
          </div>

          {/* Greeting & Location */}
          <div className="flex flex-col justify-center">
            <h1 className="text-[17px] sm:text-[19px] leading-tight text-[#1D1D1F]/60 font-normal">
              {greeting}, <span className="font-semibold text-[#1D1D1F]">{userName}</span>
            </h1>

            {/* Location selector pill */}
            <div className="mt-1 flex items-center">
              <button
                type="button"
                onClick={onLocationClick}
                className="inline-flex items-center space-x-1.5 bg-[#FFFFFF] border border-[#1D1D1F]/15 rounded-[980px] px-2.5 py-0.5 hover:bg-[#F2F2F7] transition-colors cursor-pointer"
              >
                <MapPin className="h-3.5 w-3.5 text-[#1D1D1F] shrink-0" strokeWidth={2.2} />
                <span className="text-[12px] font-semibold text-[#1D1D1F]">{locationName}</span>
                <ChevronDown className="h-3 w-3 text-[#1D1D1F]/60 shrink-0" strokeWidth={2.5} />
              </button>
            </div>
          </div>
        </div>

        {/* Right side: Single Notification Icon */}
        <div className="flex items-center shrink-0">
          <NotificationCenter />
        </div>
      </div>

      {/* 2. HERO PROMOTIONAL CARD */}
      <div className="relative overflow-hidden rounded-[24px] sm:rounded-[28px] bg-[#18181B] text-[#FFFFFF] shadow-md border border-[#27272A]/50">
        {/* Ambient Top-Right Radial Glow (Red & Yellow Warm Gradient) */}
        <div
          className="absolute -top-20 -right-20 h-60 w-60 rounded-full pointer-events-none opacity-40 blur-3xl"
          style={{
            background: "radial-gradient(circle, rgba(229,46,61,0.45) 0%, rgba(250,204,21,0.2) 45%, rgba(24,24,27,0) 80%)"
          }}
        />

        <div className="relative z-10 p-4 sm:p-5 md:p-6 space-y-4">
          <div className="flex flex-row items-center justify-between gap-2 sm:gap-4">
            {/* LEFT CONTENT AREA */}
            <div className="w-[58%] sm:w-[52%] min-w-0 space-y-2.5 sm:space-y-3">
              {/* Top Label Tag ("SHARED RIDES" pill) */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <div className="inline-flex items-center space-x-1.5 bg-white/10 border border-white/20 rounded-[980px] px-2.5 py-1 backdrop-blur-xs">
                  <Users className="h-3 w-3 text-[#E52E3D] shrink-0" strokeWidth={2.5} />
                  <span className="text-[10px] sm:text-[11px] font-bold text-[#E52E3D] uppercase tracking-wider">
                    SHARED RIDES
                  </span>
                </div>

                <span className="text-white/20 font-light text-[10px] select-none hidden xs:inline">|</span>
                <span className="text-[#FACC15] font-semibold text-[9px] sm:text-[11px] uppercase tracking-wider hidden xs:inline">
                  LOWER COST
                </span>
              </div>

              {/* Main Headline */}
              <div>
                <h2 className="text-[20px] xs:text-[23px] sm:text-[28px] md:text-[34px] font-black tracking-tight leading-[1.1] text-white">
                  Travel Together
                  <span className="block text-[#E52E3D] text-[20px] xs:text-[23px] sm:text-[28px] md:text-[34px]">
                    Go Further
                  </span>
                </h2>
              </div>

              {/* Supporting Subtext */}
              <p className="text-[#A1A1AA] text-[11px] sm:text-[13px] font-normal leading-snug max-w-[200px] sm:max-w-[280px]">
                Find or offer rides within campus and nearby areas.
              </p>

              {/* Red & Yellow Accent Line */}
              <div className="flex items-center space-x-1 pt-0.5">
                <div className="w-8 sm:w-10 h-1 bg-[#E52E3D] rounded-[980px]" />
                <div className="w-2 h-1 bg-[#FACC15] rounded-[980px]" />
              </div>
            </div>

            {/* RIGHT SIDE VISUAL: MOBILITY ILLUSTRATION */}
            <div className="w-[42%] sm:w-[48%] h-[130px] xs:h-[150px] sm:h-[180px] md:h-[200px] relative flex items-center justify-center overflow-hidden shrink-0 rounded-xl">
              <svg
                viewBox="0 0 520 320"
                className="w-full h-full object-contain filter drop-shadow-[0_4px_16px_rgba(0,0,0,0.4)]"
                aria-hidden="true"
              >
                <defs>
                  <filter id="route-glow" x="-20%" y="-20%" width="140%" height="140%">
                    <feGaussianBlur stdDeviation="6" result="blur" />
                    <feComposite in="SourceGraphic" in2="blur" operator="over" />
                  </filter>
                  <filter id="light-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="4" />
                  </filter>
                  <radialGradient id="road-ambient" cx="65%" cy="45%" r="50%">
                    <stop offset="0%" stopColor="#E52E3D" stopOpacity="0.25" />
                    <stop offset="100%" stopColor="#E52E3D" stopOpacity="0" />
                  </radialGradient>
                </defs>

                <rect x="0" y="0" width="520" height="320" fill="transparent" />
                <circle cx="350" cy="160" r="140" fill="url(#road-ambient)" />

                {/* MAP GRID LINES */}
                <g stroke="#2D2D32" strokeWidth="1" opacity="0.6">
                  <line x1="40" y1="280" x2="480" y2="80" strokeDasharray="4 6" />
                  <line x1="80" y1="300" x2="440" y2="40" strokeDasharray="4 6" />
                  <line x1="160" y1="310" x2="500" y2="140" strokeDasharray="4 6" />
                  <line x1="60" y1="120" x2="380" y2="280" strokeDasharray="4 6" />
                  <line x1="180" y1="60" x2="460" y2="200" strokeDasharray="4 6" />
                </g>

                {/* ISOMETRIC CAMPUS BUILDINGS */}
                <g transform="translate(380, 50)">
                  <polygon points="30,0 60,15 30,30 0,15" fill="#3F3F46" />
                  <polygon points="0,15 30,30 30,80 0,65" fill="#27272A" />
                  <polygon points="30,30 60,15 60,65 30,80" fill="#1E1E22" />
                  <rect x="36" y="28" width="6" height="8" fill="#E52E3D" opacity="0.9" rx="1" />
                  <rect x="48" y="22" width="6" height="8" fill="#FACC15" opacity="0.9" rx="1" />
                </g>

                <g transform="translate(420, 200)">
                  <polygon points="25,0 50,12 25,24 0,12" fill="#3F3F46" />
                  <polygon points="0,12 25,24 25,65 0,53" fill="#27272A" />
                  <polygon points="25,24 50,12 50,53 25,65" fill="#18181B" />
                  <rect x="8" y="20" width="5" height="7" fill="#FACC15" opacity="0.85" rx="1" />
                  <rect x="16" y="24" width="5" height="7" fill="#E52E3D" opacity="0.85" rx="1" />
                </g>

                {/* CURVED ROAD & ROUTE PATH */}
                <path
                  d="M 60 300 C 180 290, 240 220, 340 180 C 420 148, 460 110, 500 80"
                  fill="none"
                  stroke="#242428"
                  strokeWidth="42"
                  strokeLinecap="round"
                />

                <path
                  d="M 230 240 C 270 215, 330 185, 430 135"
                  fill="none"
                  stroke="#E52E3D"
                  strokeWidth="24"
                  opacity="0.22"
                  filter="url(#route-glow)"
                />
                <path
                  d="M 230 240 C 270 215, 330 185, 430 135"
                  fill="none"
                  stroke="#E52E3D"
                  strokeWidth="10"
                  opacity="0.45"
                />

                {/* Dashed Center Road Markings */}
                <path
                  d="M 60 300 C 180 290, 240 220, 340 180 C 420 148, 460 110, 500 80"
                  fill="none"
                  stroke="#FACC15"
                  strokeWidth="2.5"
                  strokeDasharray="10 8"
                />

                {/* ORIGIN PIN (Red/Orange) */}
                <g transform="translate(230, 240)">
                  <ellipse cx="0" cy="18" rx="18" ry="9" fill="#EF4444" opacity="0.2" />
                  <g transform="translate(-16, -34)">
                    <path
                      d="M 16 0 C 7.16 0 0 7.16 0 16 C 0 28 16 40 16 40 C 16 40 32 28 32 16 C 32 7.16 24.84 0 16 0 Z"
                      fill="#EF4444"
                    />
                    <circle cx="16" cy="15" r="6" fill="#FFFFFF" />
                  </g>
                </g>

                {/* DESTINATION PIN (Apple Red) */}
                <g transform="translate(430, 135)">
                  <ellipse cx="0" cy="22" rx="26" ry="13" fill="#E52E3D" opacity="0.2" />
                  <g transform="translate(-20, -42)">
                    <path
                      d="M 20 0 C 8.95 0 0 8.95 0 20 C 0 35 20 50 20 50 C 20 50 40 35 40 20 C 40 8.95 31.05 0 20 0 Z"
                      fill="#E52E3D"
                      filter="drop-shadow(0 6px 12px rgba(229,46,61,0.5))"
                    />
                    <circle cx="20" cy="19" r="7.5" fill="#18181B" />
                  </g>
                </g>

                {/* RED COMPACT CAR */}
                <g transform="translate(330, 185) rotate(-22)">
                  <ellipse cx="0" cy="6" rx="34" ry="16" fill="#000000" opacity="0.5" />
                  <rect x="-30" y="-14" width="60" height="28" rx="10" fill="#E52E3D" />
                  <rect x="-18" y="-11" width="34" height="22" rx="7" fill="#18181B" />
                  <rect x="-14" y="-8" width="26" height="16" rx="5" fill="#27272A" />
                  <circle cx="28" cy="-8" r="2.5" fill="#FFFFFF" />
                  <circle cx="28" cy="8" r="2.5" fill="#FFFFFF" />
                  <polygon points="29,-10 65,-22 65,-2 29,-6" fill="#FFFFFF" opacity="0.3" filter="url(#light-glow)" />
                  <polygon points="29,6 65,2 65,22 29,10" fill="#FFFFFF" opacity="0.3" filter="url(#light-glow)" />
                </g>
              </svg>
            </div>
          </div>

          {/* PAGINATION DOTS AT BOTTOM (Vibrant Red Active Dot) */}
          <div className="flex items-center space-x-1.5 pt-1">
            <span className="w-5 h-1.5 bg-[#E52E3D] rounded-[980px] transition-all" />
            <span className="w-1.5 h-1.5 bg-white/40 rounded-full transition-all" />
            <span className="w-1.5 h-1.5 bg-white/40 rounded-full transition-all" />
          </div>
        </div>
      </div>
    </header>
  )
}
