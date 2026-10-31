export const designTokens = {
  colors: {
    primaryLime: "#C5FF00",  // Electric Lime accent
    dark: "#000000",         // Pure black
    secondaryText: "#AAAAAA",
    border: "rgba(255, 255, 255, 0.12)",
    bgPage: "#000000",
    primary: "#C5FF00",
    surfaceCard: "#141416",
    destructive: "#FF3B30",
    destructiveBg: "#FF3B301A"
  },
  typography: {
    fontFamilyHeading: '"Kumbh Sans", -apple-system, BlinkMacSystemFont, sans-serif',
    fontFamilyBody: '"Kumbh Sans", -apple-system, BlinkMacSystemFont, sans-serif',
    sizes: {
      caption: "12px",
      secondary: "14px",
      body: "16px",
      subheading: "20px",
      headingMd: "24px",
      headingLg: "32px"
    },
    weights: {
      regular: 400,
      semibold: 600
    }
  },
  spacing: [4, 8, 12, 16, 20, 24, 32, 40, 48, 64],
  radii: {
    card: "16px",
    pill: "9999px"
  }
} as const
