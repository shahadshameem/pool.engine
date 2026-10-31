import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { WelcomeHero } from "../components/welcome/WelcomeHero"
import { WelcomeActions } from "../components/welcome/WelcomeActions"
import { useAuth } from "../hooks/useAuth"
import { useSEO } from "../hooks/useSEO"

export function WelcomePage() {
  useSEO({
    title: "Verified College Ridesharing & Student Carpool",
    description: "WayMate (wmate.app) connects college students commuting along identical routes. Share rides, split cab and auto fares, and commute safely with peers.",
    canonicalPath: "/",
  })

  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    // If the user is already authenticated, skip the welcome screen
    if (!loading && user) {
      navigate("/home", { replace: true })
    }
  }, [user, loading, navigate])

  if (loading || user) {
    return <MobileShell hideBottomNav>{null}</MobileShell>
  }

  return (
    <MobileShell hideBottomNav className="flex flex-col justify-between pt-[calc(1.5rem+env(safe-area-inset-top,0px))]">
      <WelcomeHero />
      <div className="flex-1" />
      <WelcomeActions />
    </MobileShell>
  )
}
