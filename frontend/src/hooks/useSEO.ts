import { useEffect } from "react"

interface SEOOptions {
  title?: string
  description?: string
  canonicalPath?: string
}

const DEFAULT_TITLE = "WayMate (wmate.app) – Verified College Ridesharing & Student Carpool"
const DEFAULT_DESCRIPTION =
  "WayMate (wmate.app) is the verified student ridesharing and carpool app. Share rides, split cab & auto fares, and commute safely to campus with trusted college peers."

export function useSEO(options: SEOOptions = {}) {
  const { title, description, canonicalPath } = options

  useEffect(() => {
    // 1. Update Document Title
    const formattedTitle = title
      ? `${title} | WayMate (wmate.app)`
      : DEFAULT_TITLE
    document.title = formattedTitle

    // 2. Update Meta Description
    let metaDesc = document.querySelector('meta[name="description"]')
    if (!metaDesc) {
      metaDesc = document.createElement("meta")
      metaDesc.setAttribute("name", "description")
      document.head.appendChild(metaDesc)
    }
    metaDesc.setAttribute("content", description || DEFAULT_DESCRIPTION)

    // 3. Update OG Title & Description
    const ogTitle = document.querySelector('meta[property="og:title"]')
    if (ogTitle) ogTitle.setAttribute("content", formattedTitle)

    const ogDesc = document.querySelector('meta[property="og:description"]')
    if (ogDesc) ogDesc.setAttribute("content", description || DEFAULT_DESCRIPTION)

    // 4. Update Canonical Link if path provided
    if (canonicalPath) {
      let canonicalLink = document.querySelector('link[rel="canonical"]')
      if (!canonicalLink) {
        canonicalLink = document.createElement("link")
        canonicalLink.setAttribute("rel", "canonical")
        document.head.appendChild(canonicalLink)
      }
      canonicalLink.setAttribute("href", `https://wmate.app${canonicalPath}`)
    }

    return () => {
      document.title = DEFAULT_TITLE
      if (metaDesc) metaDesc.setAttribute("content", DEFAULT_DESCRIPTION)
    }
  }, [title, description, canonicalPath])
}
