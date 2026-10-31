import { useEffect, lazy, Suspense } from "react"
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { ErrorBoundary } from "./components/feedback/ErrorBoundary"
import { ToastProvider } from "./components/feedback/ToastContext"
import { NotificationProvider } from "./contexts/NotificationContext"
import { AuthProvider } from "./contexts/AuthContext"
import { AdminProvider } from "./contexts/AdminContext"
import { ThemeProvider } from "./contexts/ThemeContext"
import { ConsentProvider } from "./contexts/ConsentContext"
import { ConsentBanner } from "./components/consent/ConsentBanner"
import { NavigationProvider } from "./components/navigation/NavigationProvider"
import { InstallPwaModal } from "./components/pwa/InstallPwaModal"
import { registerServiceWorker } from "./services/pwa/registerServiceWorker"
import { FullPageLoader } from "./components/feedback/LoadingState"

import { MobileShell } from "./components/layout/MobileShell"
import { AdminRoute } from "./components/admin/AdminRoute"
import { AdminLayout } from "./layouts/AdminLayout"

// Helper to automatically retry lazy loading if a dynamic chunk fails due to a new deployment release
function lazyWithRetry<T extends React.ComponentType<any>>(
  componentImport: () => Promise<{ default: T }>
) {
  return lazy(async () => {
    const pageAlreadyRefreshed = sessionStorage.getItem("chunk_reload_retry")
    try {
      const component = await componentImport()
      sessionStorage.removeItem("chunk_reload_retry")
      return component
    } catch (error: any) {
      const isChunkError =
        error?.message?.includes("dynamically imported module") ||
        error?.message?.includes("Importing a module script failed") ||
        error?.name === "ChunkLoadError"

      if (isChunkError && !pageAlreadyRefreshed) {
        sessionStorage.setItem("chunk_reload_retry", "true")
        window.location.reload()
        return new Promise(() => {})
      }
      throw error
    }
  })
}

// Lazy-loaded pages with dynamic chunk auto-retry recovery
const WelcomePage = lazyWithRetry(() => import("./pages/WelcomePage").then(m => ({ default: m.WelcomePage })))
const SignupPage = lazyWithRetry(() => import("./pages/SignupPage").then(m => ({ default: m.SignupPage })))
const LoginPage = lazyWithRetry(() => import("./pages/LoginPage").then(m => ({ default: m.LoginPage })))
const ForgotPasswordPage = lazyWithRetry(() => import("./pages/ForgotPasswordPage").then(m => ({ default: m.ForgotPasswordPage })))
const OnboardingPage = lazyWithRetry(() => import("./pages/OnboardingPage").then(m => ({ default: m.OnboardingPage })))
const HomePage = lazyWithRetry(() => import("./pages/HomePage").then(m => ({ default: m.HomePage })))
const FindRidePage = lazyWithRetry(() => import("./pages/FindRidePage").then(m => ({ default: m.FindRidePage })))
const RideDetailsPage = lazyWithRetry(() => import("./pages/RideDetailsPage").then(m => ({ default: m.RideDetailsPage })))
const OfferRidePage = lazyWithRetry(() => import("./pages/OfferRidePage").then(m => ({ default: m.OfferRidePage })))
const MyRidesPage = lazyWithRetry(() => import("./pages/MyRidesPage").then(m => ({ default: m.MyRidesPage })))
const ActivityPage = lazyWithRetry(() => import("./pages/ActivityPage").then(m => ({ default: m.ActivityPage })))
const ProfilePage = lazyWithRetry(() => import("./pages/ProfilePage").then(m => ({ default: m.ProfilePage })))
const AccountInfoPage = lazyWithRetry(() => import("./pages/AccountInfoPage").then(m => ({ default: m.AccountInfoPage })))
const NotificationSettingsPage = lazyWithRetry(() => import("./pages/NotificationSettingsPage").then(m => ({ default: m.NotificationSettingsPage })))
const PrivacyPage = lazyWithRetry(() => import("./pages/PrivacyPage").then(m => ({ default: m.PrivacyPage })))
const AppSettingsPage = lazyWithRetry(() => import("./pages/AppSettingsPage").then(m => ({ default: m.AppSettingsPage })))
const HostedByPreviewPage = lazyWithRetry(() => import("./pages/HostedByPreviewPage").then(m => ({ default: m.HostedByPreviewPage })))
const DemoScreen = lazyWithRetry(() => import("./DemoScreen").then(m => ({ default: m.DemoScreen })))

// Admin Portal Pages
const AdminDashboardPage = lazyWithRetry(() => import("./pages/admin/AdminDashboardPage").then(m => ({ default: m.AdminDashboardPage })))
const AdminCollegesPage = lazyWithRetry(() => import("./pages/admin/AdminCollegesPage").then(m => ({ default: m.AdminCollegesPage })))
const AdminUsersPage = lazyWithRetry(() => import("./pages/admin/AdminUsersPage").then(m => ({ default: m.AdminUsersPage })))
const AdminVerificationsPage = lazyWithRetry(() => import("./pages/admin/AdminVerificationsPage").then(m => ({ default: m.AdminVerificationsPage })))
const AdminRidesPage = lazyWithRetry(() => import("./pages/admin/AdminRidesPage").then(m => ({ default: m.AdminRidesPage })))
const AdminCabPoolsPage = lazyWithRetry(() => import("./pages/admin/AdminCabPoolsPage").then(m => ({ default: m.AdminCabPoolsPage })))
const AdminReportsPage = lazyWithRetry(() => import("./pages/admin/AdminReportsPage").then(m => ({ default: m.AdminReportsPage })))
const AdminDpdpPage = lazyWithRetry(() => import("./pages/admin/AdminDpdpPage").then(m => ({ default: m.AdminDpdpPage })))
const AdminPlacesPage = lazyWithRetry(() => import("./pages/admin/AdminPlacesPage").then(m => ({ default: m.AdminPlacesPage })))
const AdminSettingsPage = lazyWithRetry(() => import("./pages/admin/AdminSettingsPage").then(m => ({ default: m.AdminSettingsPage })))

// DPDP compliance pages
const TermsPage = lazyWithRetry(() => import("./pages/TermsPage").then(m => ({ default: m.TermsPage })))
const DataRightsPage = lazyWithRetry(() => import("./pages/DataRightsPage").then(m => ({ default: m.DataRightsPage })))

// Temporary placeholders for future steps
const Placeholder = ({ title }: { title: string }) => (
  <MobileShell>
    <div className="flex h-[80vh] flex-col items-center justify-center p-6 text-center space-y-4">
      <h1 className="text-2xl font-bold text-muted-foreground">{title}</h1>
      <button
        onClick={() => window.history.back()}
        className="text-primary hover:underline font-medium"
      >
        Go Back
      </button>
    </div>
  </MobileShell>
)

function App() {
  useEffect(() => {
    registerServiceWorker()
  }, [])

  return (
    <ErrorBoundary>
      <ThemeProvider>
        <AuthProvider>
          <AdminProvider>
            <BrowserRouter>
              <ToastProvider>
                <NotificationProvider>
                  <NavigationProvider>
                    <ConsentProvider>
                      <ConsentBanner />
                      <InstallPwaModal />
                      <Suspense fallback={<FullPageLoader />}>
                        <Routes>
                        <Route path="/" element={<WelcomePage />} />
                        <Route path="/signup" element={<SignupPage />} />
                        <Route path="/login" element={<LoginPage />} />
                        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                        <Route path="/onboarding" element={<OnboardingPage />} />
                        <Route path="/home" element={<HomePage />} />

                        {/* Rides Search Route */}
                        <Route path="/rides/search" element={<FindRidePage />} />
                        <Route path="/find-ride" element={<Navigate to="/rides/search" replace />} />

                        {/* Ride Details Route */}
                        <Route path="/rides/:rideId" element={<RideDetailsPage />} />
                        <Route path="/ride/:rideId" element={<Navigate to="/rides/:rideId" replace />} />

                        {/* Future Routes connected via Home Dashboard */}
                        <Route path="/rides/create" element={<OfferRidePage />} />
                        <Route path="/offer-ride" element={<Navigate to="/rides/create" replace />} />
                        <Route path="/rides" element={<MyRidesPage />} />
                        <Route path="/rides/:rideId/manage" element={<Navigate to="/rides/:rideId" replace />} />
                        <Route path="/activity" element={<ActivityPage />} />
                        <Route path="/profile" element={<ProfilePage />} />
                        <Route path="/profile/account" element={<AccountInfoPage />} />
                        <Route path="/profile/edit" element={<Navigate to="/profile/account" replace />} />
                        <Route path="/profile/notifications" element={<NotificationSettingsPage />} />
                        <Route path="/profile/privacy" element={<PrivacyPage />} />
                        <Route path="/profile/settings" element={<AppSettingsPage />} />
                        <Route path="/verification-status" element={<Navigate to="/home" replace />} />
                        {import.meta.env.DEV && (
                          <>
                            <Route path="/preview-hosted-by" element={<HostedByPreviewPage />} />
                            <Route path="/demo" element={<DemoScreen />} />
                          </>
                        )}

                        {/* Administrative Operations Portal */}
                        <Route
                          path="/admin"
                          element={
                            <AdminRoute>
                              <AdminLayout />
                            </AdminRoute>
                          }
                        >
                          <Route index element={<AdminDashboardPage />} />
                          <Route path="colleges" element={<AdminCollegesPage />} />
                          <Route path="users" element={<AdminUsersPage />} />
                          <Route path="verifications" element={<AdminVerificationsPage />} />
                          <Route path="rides" element={<AdminRidesPage />} />
                          <Route path="cab-pools" element={<AdminCabPoolsPage />} />
                          <Route path="reports" element={<AdminReportsPage />} />
                          <Route path="dpdp" element={<AdminDpdpPage />} />
                          <Route path="places" element={<AdminPlacesPage />} />
                          <Route path="settings" element={<AdminSettingsPage />} />
                        </Route>

                        {/* DPDP Compliance Routes */}
                        {/* /privacy-notice route hidden — page file kept for reference */}
                        <Route path="/terms" element={<TermsPage />} />
                        <Route path="/data-rights" element={<DataRightsPage />} />
                        <Route path="/privacy" element={<Navigate to="/profile/privacy" replace />} />
                        <Route path="/privacy-notice" element={<Navigate to="/profile/privacy" replace />} />

                        {/* Utility Routes */}
                        <Route path="/forgot-password" element={<Placeholder title="Forgot Password (Future Step)" />} />

                        {/* Catch-all redirect to welcome */}
                        <Route path="*" element={<Navigate to="/" replace />} />
                      </Routes>
                    </Suspense>
                  </ConsentProvider>
                </NavigationProvider>
              </NotificationProvider>
              </ToastProvider>
            </BrowserRouter>
          </AdminProvider>
        </AuthProvider>
      </ThemeProvider>
    </ErrorBoundary>
  )
}

export default App
