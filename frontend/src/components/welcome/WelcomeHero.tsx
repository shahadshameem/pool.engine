import { MaterialIcon } from "../common/MaterialIcon"

export function WelcomeHero() {
  return (
    <div className="flex flex-col items-center pt-8 pb-4 text-center">
      {/* Brand Title */}
      <div className="mb-8 space-y-1">
        <h1 className="text-edex-display text-foreground font-black tracking-tight">
          Way<span className="text-[#C5FF00]">Mate</span>
        </h1>
        <span className="text-[10px] font-extrabold tracking-[0.25em] text-muted-foreground uppercase block pt-1">
          RIDE TOGETHER
        </span>
      </div>

      {/* Hero Headline */}
      <div className="space-y-3 px-4 max-w-[320px]">
        <h2 className="text-edex-section text-foreground font-bold leading-tight">
          Same route.<br />Brighter journeys.
        </h2>
        <p className="text-edex-meta text-muted-foreground">
          Find or offer a ride with students near you.
        </p>
      </div>

      {/* Minimal Route Illustration */}
      <div className="my-10 flex w-full max-w-[280px] items-center justify-between px-6 py-6 rounded-2xl bg-card border border-border/60 shadow-xs">
        <div className="flex flex-col items-center space-y-1">
          <MaterialIcon name="location_on" className="text-foreground text-[28px]" />
          <span className="text-[12px] font-semibold text-foreground">Origin</span>
        </div>

        <div className="flex-1 flex items-center justify-center px-4">
          <div className="w-full h-[2px] bg-dashed border-t-2 border-dashed border-border/60 relative">
            <MaterialIcon name="directions_car" className="text-foreground text-[20px] absolute -top-[9px] left-1/2 -translate-x-1/2 bg-card px-1" />
          </div>
        </div>

        <div className="flex flex-col items-center space-y-1">
          <MaterialIcon name="location_on" className="text-foreground text-[28px]" />
          <span className="text-[12px] font-semibold text-foreground">Destination</span>
        </div>
      </div>
    </div>
  )
}
