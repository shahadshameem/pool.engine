import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { getLogicalParent } from "../../config/navigationTree"
import { ConfirmModal } from "../ui/confirm-modal"

export interface ModalHandler {
  id: string
  close: () => void
  priority?: number
}

export interface GuardHandler {
  id: string
  isBlocked: () => boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
}

export interface NavigationContextValue {
  goBack: () => void
  registerModal: (id: string, close: () => void, priority?: number) => () => void
  unregisterModal: (id: string) => void
  registerDirtyGuard: (id: string, isDirty: () => boolean, message?: string) => () => void
  unregisterDirtyGuard: (id: string) => void
  registerActiveTripGuard: (id: string, isActive: () => boolean, message?: string) => () => void
  unregisterActiveTripGuard: (id: string) => void
}

const NavigationContext = createContext<NavigationContextValue | null>(null)

export interface NavigationProviderProps {
  children: React.ReactNode
}

export function NavigationProvider({ children }: NavigationProviderProps) {
  const location = useLocation()
  const navigate = useNavigate()

  // Registered open modals & sheets
  const modalsRef = useRef<ModalHandler[]>([])

  // Registered guards (unsaved forms, active trips)
  const dirtyGuardsRef = useRef<Map<string, GuardHandler>>(new Map())
  const activeTripGuardsRef = useRef<Map<string, GuardHandler>>(new Map())

  // Confirmation Dialog States
  const [activePrompt, setActivePrompt] = useState<{
    isOpen: boolean
    title: string
    message: string
    confirmText: string
    cancelText: string
    onConfirm: () => void
  } | null>(null)

  // Register / Unregister Modals
  const registerModal = useCallback((id: string, close: () => void, priority = 0) => {
    modalsRef.current = modalsRef.current.filter(m => m.id !== id)
    modalsRef.current.push({ id, close, priority })
    return () => {
      modalsRef.current = modalsRef.current.filter(m => m.id !== id)
    }
  }, [])

  const unregisterModal = useCallback((id: string) => {
    modalsRef.current = modalsRef.current.filter(m => m.id !== id)
  }, [])

  // Register / Unregister Dirty Form Guards
  const registerDirtyGuard = useCallback(
    (id: string, isDirty: () => boolean, message = "You have unsaved changes. Discard them?") => {
      dirtyGuardsRef.current.set(id, {
        id,
        isBlocked: isDirty,
        title: "Discard changes?",
        message,
        confirmText: "Discard",
        cancelText: "Keep Editing"
      })
      return () => {
        dirtyGuardsRef.current.delete(id)
      }
    },
    []
  )

  const unregisterDirtyGuard = useCallback((id: string) => {
    dirtyGuardsRef.current.delete(id)
  }, [])

  // Register / Unregister Active Trip Guards
  const registerActiveTripGuard = useCallback(
    (id: string, isActive: () => boolean, message = "A ride is currently in progress. Leave this screen? (Live tracking will continue)") => {
      activeTripGuardsRef.current.set(id, {
        id,
        isBlocked: isActive,
        title: "Leave active ride?",
        message,
        confirmText: "Leave Screen",
        cancelText: "Stay"
      })
      return () => {
        activeTripGuardsRef.current.delete(id)
      }
    },
    []
  )

  const unregisterActiveTripGuard = useCallback((id: string) => {
    activeTripGuardsRef.current.delete(id)
  }, [])

  // Execute hierarchical back navigation
  const executeNavigateParent = useCallback(() => {
    const parent = getLogicalParent(location.pathname, location.state)

    // If on /home root, prompt to exit
    if (location.pathname === "/home" || location.pathname === "/") {
      setActivePrompt({
        isOpen: true,
        title: "Exit Waymate?",
        message: "Are you sure you want to exit the application?",
        confirmText: "Exit",
        cancelText: "Cancel",
        onConfirm: () => {
          // If in a PWA / standalone or browser with history, go back out
          if (window.history.length > 1) {
            window.history.back()
          } else {
            window.close()
          }
        }
      })
      return
    }

    // Contextual navigation to parent
    // Use replace: true to prevent stack accumulation on back
    navigate(parent, { replace: true })
  }, [location.pathname, location.state, navigate])

  // Central unified Back Action (used by Header Back Arrow and System Back)
  const goBack = useCallback(() => {
    // 1. Check open modals / sheets first (Priority 1)
    if (modalsRef.current.length > 0) {
      // Sort descending by priority so highest priority closes first
      const sorted = [...modalsRef.current].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
      const topModal = sorted[0]
      topModal.close()
      modalsRef.current = modalsRef.current.filter(m => m.id !== topModal.id)
      return
    }

    // 2. Check active in-progress trip guards (Priority 2)
    for (const guard of activeTripGuardsRef.current.values()) {
      if (guard.isBlocked()) {
        setActivePrompt({
          isOpen: true,
          title: guard.title || "Active Trip in Progress",
          message: guard.message,
          confirmText: guard.confirmText || "Leave",
          cancelText: guard.cancelText || "Stay",
          onConfirm: () => {
            setActivePrompt(null)
            executeNavigateParent()
          }
        })
        return
      }
    }

    // 3. Check dirty form guards (Priority 3)
    for (const guard of dirtyGuardsRef.current.values()) {
      if (guard.isBlocked()) {
        setActivePrompt({
          isOpen: true,
          title: guard.title || "Discard Changes?",
          message: guard.message,
          confirmText: guard.confirmText || "Discard",
          cancelText: guard.cancelText || "Cancel",
          onConfirm: () => {
            setActivePrompt(null)
            executeNavigateParent()
          }
        })
        return
      }
    }

    // 4. Default: Navigate to logical parent
    executeNavigateParent()
  }, [executeNavigateParent])

  // System Popstate (Browser / Hardware Back Button) Interceptor
  useEffect(() => {
    const handlePopState = (_event: PopStateEvent) => {
      // If any modal is open, or a dirty form / trip guard is active, or we are on /home:
      const hasOpenModals = modalsRef.current.length > 0
      const hasActiveTrip = Array.from(activeTripGuardsRef.current.values()).some(g => g.isBlocked())
      const hasDirtyForm = Array.from(dirtyGuardsRef.current.values()).some(g => g.isBlocked())
      const isAtHome = location.pathname === "/home" || location.pathname === "/"

      if (hasOpenModals || hasActiveTrip || hasDirtyForm || isAtHome) {
        // Prevent browser from immediately popping
        window.history.pushState(null, "", window.location.href)
        goBack()
      }
    }

    window.addEventListener("popstate", handlePopState)
    return () => {
      window.removeEventListener("popstate", handlePopState)
    }
  }, [goBack, location.pathname])

  const contextValue: NavigationContextValue = {
    goBack,
    registerModal,
    unregisterModal,
    registerDirtyGuard,
    unregisterDirtyGuard,
    registerActiveTripGuard,
    unregisterActiveTripGuard
  }

  return (
    <NavigationContext.Provider value={contextValue}>
      {children}

      {/* Central Exit / Guard Confirmation Modal */}
      {activePrompt && (
        <ConfirmModal
          isOpen={activePrompt.isOpen}
          title={activePrompt.title}
          description={activePrompt.message}
          confirmText={activePrompt.confirmText}
          cancelText={activePrompt.cancelText}
          variant="destructive"
          onConfirm={activePrompt.onConfirm}
          onClose={() => setActivePrompt(null)}
        />
      )}
    </NavigationContext.Provider>
  )
}

/**
 * Hook to access centralized back navigation and register guards
 */
export function useBackNavigation() {
  const context = useContext(NavigationContext)
  if (!context) {
    throw new Error("useBackNavigation must be used within a NavigationProvider")
  }
  return context
}
