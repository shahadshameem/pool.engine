/**
 * Consent Context
 * Provides app-wide access to the user's consent state and a function to update it.
 * Non-essential trackers (Analytics, FCM) are gated behind this context.
 */
import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react"
import {
  type ConsentMap,
  type ConsentPurpose,
  getConsentState,
  recordConsent,
  hasConsentBeenRecorded,
} from "../services/consent/consentService"
import { useAuth } from "../hooks/useAuth"

interface ConsentContextValue {
  /** The current consent map. Null = not yet loaded. */
  consentMap: ConsentMap | null
  /** True if the user has not yet been asked for consent */
  needsBanner: boolean
  /** True while consent state is being fetched */
  loading: boolean
  /** Update a single purpose consent */
  updateConsent: (purpose: ConsentPurpose, granted: boolean) => Promise<void>
  /** Mark banner as dismissed (for anonymous / pre-auth visitors) */
  dismissBanner: () => void
  /** True if non-essential analytics/tracking is permitted */
  analyticsAllowed: boolean
  /** True if push notifications are allowed */
  notificationsAllowed: boolean
}

const ConsentContext = createContext<ConsentContextValue>({
  consentMap: null,
  needsBanner: false,
  loading: true,
  updateConsent: async () => {},
  dismissBanner: () => {},
  analyticsAllowed: false,
  notificationsAllowed: false,
})

const BANNER_DISMISSED_KEY = "waymate_consent_banner_dismissed_v1"

export function ConsentProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [consentMap, setConsentMap] = useState<ConsentMap | null>(null)
  const [loading, setLoading] = useState(true)
  const [needsBanner, setNeedsBanner] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function loadConsent() {
      setLoading(true)
      const isLocallyDismissed = sessionStorage.getItem(BANNER_DISMISSED_KEY) || localStorage.getItem(BANNER_DISMISSED_KEY)

      try {
        if (!user) {
          // Not logged in — check dismissal
          if (!isLocallyDismissed) setNeedsBanner(true)
          setConsentMap(null)
          return
        }

        try {
          const recorded = await hasConsentBeenRecorded(user.uid)
          if (cancelled) return

          if (!recorded) {
            if (!isLocallyDismissed) {
              setNeedsBanner(true)
            }
            setConsentMap(null)
          } else {
            const map = await getConsentState(user.uid)
            if (!cancelled) setConsentMap(map)
            setNeedsBanner(false)
          }
        } catch (err) {
          console.warn("Failed to check consent state from Firestore:", err)
          setNeedsBanner(!isLocallyDismissed)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadConsent()
    return () => { cancelled = true }
  }, [user])

  const updateConsent = useCallback(
    async (purpose: ConsentPurpose, granted: boolean) => {
      if (!user) return
      await recordConsent(user.uid, purpose, granted, "settings")
      setConsentMap((prev) => ({
        ...(prev ?? ({} as ConsentMap)),
        [purpose]: granted,
      }))
    },
    [user]
  )

  const dismissBanner = useCallback(() => {
    sessionStorage.setItem(BANNER_DISMISSED_KEY, "1")
    localStorage.setItem(BANNER_DISMISSED_KEY, "1")
    setNeedsBanner(false)
  }, [])

  const analyticsAllowed = consentMap?.analytics === true
  const notificationsAllowed = consentMap?.notifications === true

  return (
    <ConsentContext.Provider
      value={{
        consentMap,
        needsBanner,
        loading,
        updateConsent,
        dismissBanner,
        analyticsAllowed,
        notificationsAllowed,
      }}
    >
      {children}
    </ConsentContext.Provider>
  )
}

export function useConsent() {
  return useContext(ConsentContext)
}
