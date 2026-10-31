import { Component } from "react"
import type { ErrorInfo, ReactNode } from "react"
import { AlertCircle, RefreshCw } from "lucide-react"
import { Button } from "../ui/button"

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught Error Boundary Catch:", error, errorInfo)
    const isChunkError =
      error?.message?.includes("dynamically imported module") ||
      error?.message?.includes("Importing a module script failed") ||
      error?.name === "ChunkLoadError"

    if (isChunkError) {
      const alreadyReloaded = sessionStorage.getItem("chunk_reload_auto")
      if (!alreadyReloaded) {
        sessionStorage.setItem("chunk_reload_auto", "true")
        window.location.reload()
      }
    }
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="mx-auto flex min-h-screen w-full max-w-md flex-col bg-background text-foreground p-6 text-center justify-center items-center space-y-4">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
            <AlertCircle className="h-8 w-8 text-destructive" />
          </div>
          <h1 className="text-xl font-bold text-foreground">Something went wrong</h1>
          <p className="text-sm text-muted-foreground max-w-xs">
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <Button
            className="mt-4 bg-[#E52E3D] text-white hover:bg-[#D02533] font-bold rounded-full h-12 px-6 cursor-pointer"
            onClick={() => {
              sessionStorage.removeItem("chunk_reload_auto")
              sessionStorage.removeItem("chunk_reload_retry")
              this.setState({ hasError: false, error: null })
              window.location.reload()
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Reload Application
          </Button>
        </div>
      )
    }

    return this.props.children
  }
}
