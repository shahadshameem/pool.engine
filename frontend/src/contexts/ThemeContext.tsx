import React, { createContext, useContext, useEffect, useState } from "react"

export type ThemeMode = "dark"

interface ThemeContextType {
  theme: "dark"
  setTheme: (theme: ThemeMode) => void
  resolvedTheme: "dark"
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

const THEME_STORAGE_KEY = "waymate_theme_mode"

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme] = useState<"dark">("dark")
  const [resolvedTheme] = useState<"dark">("dark")

  const setTheme = (_newTheme: ThemeMode) => {
    // Locked to dark mode - no-op for any external calls
    localStorage.setItem(THEME_STORAGE_KEY, "dark")
  }

  useEffect(() => {
    const root = document.documentElement

    const applyTheme = () => {
      root.classList.add("dark")
      root.style.backgroundColor = "#000000"
      root.style.colorScheme = "dark"
      localStorage.setItem(THEME_STORAGE_KEY, "dark")

      // Synchronize iOS Safari and PWA status bar theme-color
      try {
        const metaTags = document.querySelectorAll('meta[name="theme-color"]')
        metaTags.forEach(tag => tag.setAttribute("content", "#000000"))
      } catch (e) {}
    }

    applyTheme()
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, setTheme, resolvedTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider")
  }
  return context
}
