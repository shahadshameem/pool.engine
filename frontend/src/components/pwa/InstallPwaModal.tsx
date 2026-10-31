import { useState, useEffect } from "react"
import { useLocation } from "react-router-dom"
import { Download, Share, PlusSquare, X, Sparkles } from "lucide-react"
import { useAuth } from "../../hooks/useAuth"
import { WayMateLogoIcon } from "../common/WayMateLogo"

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>
}

const DISMISSAL_KEY = "waymate_install_dismissed"
const SESSION_KEY = "waymate_install_session_shown"
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000 // 7 days cooldown after dismissal

export function InstallPwaModal() {
  const location = useLocation()
  const { isAuthenticated, loading } = useAuth()

  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [showAndroidModal, setShowAndroidModal] = useState(false)
  const [showIosModal, setShowIosModal] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined") return

    // 1. Check standalone mode (already installed)
    const isStandalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (navigator as any).standalone === true
    if (isStandalone) return

    // 2. Check dismissal persistence and session rules
    const lastDismissed = localStorage.getItem(DISMISSAL_KEY)
    if (lastDismissed) {
      const timestamp = parseInt(lastDismissed, 10)
      if (!isNaN(timestamp) && Date.now() - timestamp < COOLDOWN_MS) {
        return
      }
    }

    const sessionShown = sessionStorage.getItem(SESSION_KEY)
    if (sessionShown === "true") return

    // 3. Exclude non-authenticated or initial auth screens
    if (loading || !isAuthenticated) return
    const excludedPaths = ["/", "/login", "/signup", "/onboarding"]
    if (excludedPaths.includes(location.pathname)) return

    // 4. iOS Safari Detection
    const userAgent = window.navigator.userAgent.toLowerCase()
    const isIosDevice = /iphone|ipad|ipod/.test(userAgent)
    const isSafari = userAgent.includes("safari") && !userAgent.includes("crios") && !userAgent.includes("fxios")

    if (isIosDevice && isSafari) {
      setShowIosModal(true)
      sessionStorage.setItem(SESSION_KEY, "true")
      return
    }

    // 5. Android / Desktop Listener for beforeinstallprompt
    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault()
      const promptEvent = e as BeforeInstallPromptEvent
      setDeferredPrompt(promptEvent)
      setShowAndroidModal(true)
      sessionStorage.setItem(SESSION_KEY, "true")
    }

    window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt)

    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstallPrompt)
    }
  }, [isAuthenticated, loading, location.pathname])

  const handleInstallClick = async () => {
    if (!deferredPrompt) return
    try {
      await deferredPrompt.prompt()
      const choiceResult = await deferredPrompt.userChoice
      if (choiceResult.outcome === "accepted") {
        console.log("User accepted PWA installation")
      } else {
        console.log("User dismissed PWA installation")
        localStorage.setItem(DISMISSAL_KEY, Date.now().toString())
      }
    } catch (err) {
      console.error("Error during PWA prompt:", err)
    } finally {
      setDeferredPrompt(null)
      setShowAndroidModal(false)
    }
  }

  const handleDismiss = () => {
    localStorage.setItem(DISMISSAL_KEY, Date.now().toString())
    setShowAndroidModal(false)
    setShowIosModal(false)
  }

  if (!showAndroidModal && !showIosModal) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] bg-black/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-sm rounded-[28px] bg-card border border-border/80 p-6 shadow-2xl space-y-5 animate-in slide-in-from-bottom-5 duration-300">

        {/* Close button */}
        <button
          onClick={handleDismiss}
          className="absolute top-4 right-4 p-1.5 rounded-full text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          aria-label="Close modal"
        >
          <X className="h-5 w-5" />
        </button>

        {/* Header Branding Icon */}
        <div className="flex items-center space-x-3">
          <div className="w-12 h-12 rounded-[18px] bg-black flex items-center justify-center shadow-md shrink-0">
            <WayMateLogoIcon size={32} />
          </div>
          <div>
            <div className="flex items-center space-x-1.5">
              <h2 className="text-[17px] font-bold text-foreground">Install WayMate</h2>
              <Sparkles className="h-4 w-4 text-[#1D1D1F] fill-[#1D1D1F]" />
            </div>
            <p className="text-[12px] text-muted-foreground font-medium">CET College Ride Matching App</p>
          </div>
        </div>

        {/* Android / Desktop Install View */}
        {showAndroidModal && (
          <div className="space-y-4">
            <p className="text-[13px] text-muted-foreground leading-relaxed">
              Install WayMate to your home screen for quick 1-tap access, instant ride alerts, and a full-screen experience.
            </p>

            <div className="pt-2 flex flex-col gap-2.5">
              <button
                onClick={handleInstallClick}
                className="w-full h-12 rounded-[980px] bg-[#1D1D1F] hover:bg-[#1D1D1F]/90 active:scale-[0.98] transition-all font-semibold text-white text-[15px] flex items-center justify-center space-x-2 cursor-pointer"
              >
                <Download className="h-5 w-5 stroke-[2.5]" />
                <span>Install App</span>
              </button>

              <button
                onClick={handleDismiss}
                className="w-full h-10 rounded-[980px] text-muted-foreground hover:text-foreground font-semibold text-[14px] transition-colors cursor-pointer"
              >
                Not now
              </button>
            </div>
          </div>
        )}

        {/* iOS Safari Manual Instructions View */}
        {showIosModal && (
          <div className="space-y-4">
            <p className="text-[13px] text-muted-foreground leading-relaxed">
              Install WayMate on your iPhone or iPad home screen by following these steps:
            </p>

            <div className="bg-secondary/60 rounded-[18px] p-4 space-y-3 border border-border/40 text-[13px]">
              <div className="flex items-start space-x-3">
                <div className="w-6 h-6 rounded-full bg-[#1D1D1F] text-white font-bold flex items-center justify-center text-[12px] shrink-0 mt-0.5">
                  1
                </div>
                <div className="text-foreground leading-snug">
                  Tap the <strong className="font-bold text-foreground">Share</strong> icon <Share className="inline h-4 w-4 text-[#1D1D1F] stroke-[2.5] mx-1" /> in your Safari menu bar below.
                </div>
              </div>

              <div className="flex items-start space-x-3">
                <div className="w-6 h-6 rounded-full bg-[#1D1D1F] text-white font-bold flex items-center justify-center text-[12px] shrink-0 mt-0.5">
                  2
                </div>
                <div className="text-foreground leading-snug">
                  Scroll down and tap <strong className="font-bold text-foreground">"Add to Home Screen"</strong> <PlusSquare className="inline h-4 w-4 text-[#1D1D1F] stroke-[2.5] mx-1" />.
                </div>
              </div>

              <div className="flex items-start space-x-3">
                <div className="w-6 h-6 rounded-full bg-[#1D1D1F] text-white font-bold flex items-center justify-center text-[12px] shrink-0 mt-0.5">
                  3
                </div>
                <div className="text-foreground leading-snug">
                  Tap <strong className="font-bold text-foreground">"Add"</strong> in the top-right corner.
                </div>
              </div>
            </div>

            <div className="pt-1">
              <button
                onClick={handleDismiss}
                className="w-full h-11 rounded-[980px] bg-[#1D1D1F] hover:bg-[#1D1D1F]/90 active:scale-[0.98] transition-all font-semibold text-white text-[14px] cursor-pointer"
              >
                Got it
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
