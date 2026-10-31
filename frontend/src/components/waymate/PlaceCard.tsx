
import { Bookmark, Navigation, Star } from "lucide-react"
import { cn } from "../../lib/utils"
import { Button } from "../ui/button"

export interface PlaceCardProps {
  name: string
  category: string
  distance?: string
  rating?: number
  imageUrl?: string
  state?: "default" | "selected" | "saved" | "loading"
  onSave?: () => void
  onClick?: () => void
  onAction?: () => void
  actionLabel?: string
  className?: string
}

export function PlaceCard({
  name,
  category,
  distance,
  rating,
  imageUrl,
  state = "default",
  onSave,
  onClick,
  onAction,
  actionLabel = "Explore",
  className
}: PlaceCardProps) {

  if (state === "loading") {
    return (
      <div className={cn("w-[240px] rounded-[18px] border bg-card p-3 shadow-sm animate-pulse flex-shrink-0", className)}>
        <div className="h-[120px] w-full rounded-[12px] bg-muted mb-3" />
        <div className="h-5 w-3/4 bg-muted rounded mb-2" />
        <div className="h-4 w-1/2 bg-muted rounded mb-4" />
        <div className="h-10 w-full bg-muted rounded-[10px]" />
      </div>
    )
  }

  const isSaved = state === "saved"
  const isSelected = state === "selected"

  return (
    <div
      onClick={onClick}
      className={cn(
        "w-[240px] rounded-[18px] border bg-card p-3 shadow-sm transition-all flex-shrink-0 cursor-pointer overflow-hidden group hover:shadow-md",
        isSelected ? "border-primary ring-1 ring-primary" : "border-border",
        className
      )}
    >
      <div className="relative h-[120px] w-full rounded-[12px] bg-muted mb-3 overflow-hidden">
        {imageUrl ? (
          <img src={imageUrl} alt={name} className="w-full h-full object-cover transition-transform group-hover:scale-105" />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-accent text-muted-foreground">
            <Navigation className="h-8 w-8 opacity-20" />
          </div>
        )}

        {onSave && (
          <button
            onClick={(e) => { e.stopPropagation(); onSave(); }}
            className="absolute top-2 right-2 h-8 w-8 bg-background/80 backdrop-blur-sm rounded-full flex items-center justify-center text-foreground hover:bg-background transition-colors"
          >
            <Bookmark className={cn("h-4 w-4", isSaved && "fill-primary text-primary")} />
          </button>
        )}
      </div>

      <div className="mb-4">
        <h3 className="font-semibold text-[16px] text-foreground truncate">{name}</h3>
        <div className="flex items-center text-[13px] text-muted-foreground mt-0.5">
          <span>{category}</span>
          {distance && (
            <>
              <span className="mx-1.5 font-bold">·</span>
              <span>{distance}</span>
            </>
          )}
        </div>
        {rating !== undefined && (
          <div className="flex items-center mt-1.5 text-[13px] font-medium">
            <Star className="h-3.5 w-3.5 text-warning fill-warning mr-1" />
            <span>{rating}</span>
          </div>
        )}
      </div>

      {onAction && (
        <Button
          variant={isSelected ? "primary" : "secondary"}
          size="sm"
          className="w-full h-[40px] rounded-[10px]"
          onClick={(e) => { e.stopPropagation(); onAction(); }}
        >
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
