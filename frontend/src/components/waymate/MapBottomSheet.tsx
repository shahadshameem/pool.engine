
import { Navigation, Bookmark, Map } from "lucide-react"
import { cn } from "../../lib/utils"
import { Button } from "../ui/button"

export interface MapBottomSheetProps {
  placeName: string
  address: string
  distance?: string
  rating?: number
  category?: string
  imageUrl?: string
  onDirections?: () => void
  onSave?: () => void
  onConfirm?: () => void
  className?: string
  isSaved?: boolean
}

export function MapBottomSheet({
  placeName,
  address,
  distance,
  rating,
  category,
  imageUrl,
  onDirections,
  onSave,
  onConfirm,
  className,
  isSaved = false
}: MapBottomSheetProps) {
  return (
    <div className={cn("absolute bottom-0 left-0 w-full bg-card rounded-t-[24px] shadow-[0_-10px_40px_rgba(0,0,0,0.1)] z-40 p-5 pb-safe animate-in slide-in-from-bottom-8", className)}>
      {/* Drag handle */}
      <div className="w-12 h-1.5 bg-muted rounded-full mx-auto mb-5" />

      <div className="flex gap-4 mb-6">
        {imageUrl ? (
          <img src={imageUrl} alt={placeName} className="w-[80px] h-[80px] rounded-[16px] object-cover shrink-0" />
        ) : (
          <div className="w-[80px] h-[80px] rounded-[16px] bg-accent flex items-center justify-center shrink-0 text-muted-foreground">
            <Map className="h-8 w-8 opacity-20" />
          </div>
        )}

        <div className="flex-1 min-w-0">
          <h3 className="font-bold text-[20px] text-foreground leading-tight truncate">{placeName}</h3>

          <div className="flex items-center text-[13px] text-muted-foreground mt-1 mb-1">
            {category && <span>{category}</span>}
            {category && distance && <span className="mx-1.5 font-bold">&middot;</span>}
            {distance && <span>{distance}</span>}
            {rating && (
              <>
                <span className="mx-1.5 font-bold">&middot;</span><span className="text-warning font-medium">&#9733; {rating}</span>
              </>
            )}
          </div>

          <p className="text-[13px] text-muted-foreground line-clamp-2 leading-snug">
            {address}
          </p>
        </div>
      </div>

      <div className="flex gap-3">
        {onSave && (
          <Button
            variant="secondary"
            size="icon"
            onClick={onSave}
            className="shrink-0 rounded-[14px]"
          >
            <Bookmark className={cn("h-5 w-5", isSaved && "fill-primary text-primary")} />
          </Button>
        )}

        {onDirections && (
          <Button
            variant="primary"
            className="flex-1 font-bold"
            onClick={onDirections}
          >
            <Navigation className="mr-2 h-5 w-5" />
            Get Directions
          </Button>
        )}

        {onConfirm && !onDirections && (
          <Button
            variant="primary"
            className="flex-1 font-bold"
            onClick={onConfirm}
          >
            Confirm Location
          </Button>
        )}
      </div>
    </div>
  )
}
