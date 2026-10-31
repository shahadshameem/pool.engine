export interface WayMateLogoProps {
  variant?: "horizontal" | "compact" | "vertical" | "symbol" | "app-icon-light" | "app-icon-dark"
  size?: "sm" | "md" | "lg" | "xl" | number
  className?: string
  showTagline?: boolean
  mode?: "auto" | "light" | "dark"
}

export function WayMateSymbol({ className = "", size = 40 }: { className?: string; size?: number }) {
  return (
    <img
      src="/logo.png"
      alt="WayMate"
      style={{ width: size, height: "auto" }}
      className={`object-contain max-h-[120px] ${className}`}
    />
  )
}

export const WayMateLogoIcon = WayMateSymbol

export function WayMateLogo({
  size = "md",
  className = "",
}: WayMateLogoProps) {
  let pixelSize = 40
  if (typeof size === "number") {
    pixelSize = size
  } else {
    switch (size) {
      case "sm": pixelSize = 28; break
      case "md": pixelSize = 36; break
      case "lg": pixelSize = 48; break
      case "xl": pixelSize = 64; break
    }
  }

  return (
    <img
      src="/logo.png"
      alt="WayMate"
      style={{ height: pixelSize }}
      className={`w-auto object-contain ${className}`}
    />
  )
}
