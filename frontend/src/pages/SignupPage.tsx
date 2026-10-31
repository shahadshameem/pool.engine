import { useEffect } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { LoginPage } from "./LoginPage"

/**
 * Google Sign-In is the unified authentication flow for both sign-in and sign-up.
 * This component cleanly redirects new users to the unified LoginPage.
 */
export function SignupPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    // Keep URL clean and unified on /login
    navigate("/login" + (searchParams.toString() ? "?" + searchParams.toString() : ""), { replace: true })
  }, [navigate, searchParams])

  return <LoginPage />
}
