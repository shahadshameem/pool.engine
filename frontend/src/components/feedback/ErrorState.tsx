import { AlertCircle } from "lucide-react"
import { Button } from "../ui/button"

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
  isInline?: boolean
}

export function ErrorState({
  title = "Something went wrong",
  message = "We couldn't load the information. Please try again.",
  onRetry,
  isInline = false
}: ErrorStateProps) {
  if (isInline) {
    return (
      <div className="flex w-full items-center gap-3 rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-destructive">
        <AlertCircle className="h-5 w-5 shrink-0" />
        <div className="flex-1 text-sm">{message}</div>
        {onRetry && (
          <Button variant="ghost" size="sm" onClick={onRetry} className="h-8 hover:bg-destructive/20">
            Retry
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-[40vh] w-full flex-col items-center justify-center p-6 text-center">
      <div className="mb-4 rounded-full bg-destructive/10 p-3 text-destructive">
        <AlertCircle className="h-8 w-8" />
      </div>
      <h3 className="mb-2 text-xl font-bold">{title}</h3>
      <p className="mb-6 max-w-xs text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <Button onClick={onRetry} variant="outline" className="min-w-[120px]">
          Try Again
        </Button>
      )}
    </div>
  )
}
