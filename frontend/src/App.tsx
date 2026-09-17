import { Suspense, lazy } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { useAuth } from "@/features/auth"
import { LoadingState } from "@/components/ui/feedback"
import { LoginPage } from "@/pages/Login"
import { RequestDetailPage, RequestsPage } from "@/pages/Requests"
import { DocumentsPage } from "@/pages/Documents"
import { QuotationDetailPage } from "@/pages/QuotationDetail"
import { SuppliersPage } from "@/pages/Suppliers"

// Recharts is heavy and only these routes need it, so they load on demand.
const DashboardPage = lazy(() =>
  import("@/pages/Dashboard").then((m) => ({ default: m.DashboardPage })),
)
const ComparisonIndexPage = lazy(() =>
  import("@/pages/Comparison").then((m) => ({ default: m.ComparisonIndexPage })),
)
const ComparisonPage = lazy(() =>
  import("@/pages/Comparison").then((m) => ({ default: m.ComparisonPage })),
)

function ProtectedRoutes() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState label="Restoring your session…" />
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <AppShell />
}

export default function App() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoutes />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/requests/:requestId" element={<RequestDetailPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:quotationId" element={<QuotationDetailPage />} />
          <Route path="/suppliers" element={<SuppliersPage />} />
          <Route path="/comparison" element={<ComparisonIndexPage />} />
          <Route path="/comparison/:requestId" element={<ComparisonPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
