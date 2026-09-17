import * as React from "react"
import { NavLink, Outlet, useNavigate } from "react-router-dom"
import {
  BarChart3,
  Building2,
  ClipboardList,
  FileStack,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Sun,
  X,
} from "lucide-react"
import { useAuth } from "@/features/auth"
import { useCapabilities } from "@/hooks/queries"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn, initials } from "@/lib/utils"

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/requests", label: "Procurement", icon: ClipboardList },
  { to: "/documents", label: "Documents", icon: FileStack },
  { to: "/suppliers", label: "Suppliers", icon: Building2 },
  { to: "/comparison", label: "Comparison", icon: BarChart3 },
]

function useTheme() {
  const [theme, setTheme] = React.useState<"light" | "dark">(() => {
    try {
      const stored = localStorage.getItem("apa.theme")
      if (stored === "dark" || stored === "light") return stored
    } catch {
      /* storage unavailable */
    }
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light"
  })

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    try {
      localStorage.setItem("apa.theme", theme)
    } catch {
      /* storage unavailable */
    }
  }, [theme])

  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) }
}

export function AppShell() {
  const { user, organization, logout } = useAuth()
  const { data: capabilities } = useCapabilities()
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const [mobileOpen, setMobileOpen] = React.useState(false)

  const degraded = capabilities && (!capabilities.ai.configured || !capabilities.ocr.available)

  return (
    <div className="min-h-screen bg-background">
      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r bg-card transition-transform lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-16 items-center gap-2.5 border-b px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <FileStack className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold leading-tight">Procurement</p>
            <p className="truncate text-xs text-muted-foreground">Assistant</p>
          </div>
          <button
            className="ml-auto rounded-md p-1 lg:hidden"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Capability status: says plainly when the deployment is degraded. */}
        {capabilities && (
          <div className="space-y-2 border-t p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">AI extraction</span>
              <Badge variant={capabilities.ai.configured ? "success" : "warning"}>
                {capabilities.ai.configured ? capabilities.ai.provider : "Not configured"}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">OCR</span>
              <Badge variant={capabilities.ocr.available ? "success" : "destructive"}>
                {capabilities.ocr.engine ?? "Unavailable"}
              </Badge>
            </div>
          </div>
        )}

        <div className="border-t p-3">
          <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold">
              {initials(user?.name)}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium leading-tight">{user?.name}</p>
              <p className="truncate text-xs text-muted-foreground">{organization?.name}</p>
            </div>
          </div>
          <div className="mt-2 flex gap-1.5">
            <Button variant="ghost" size="sm" className="flex-1 justify-start" onClick={toggle}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {theme === "dark" ? "Light" : "Dark"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="flex-1 justify-start text-muted-foreground"
              onClick={() => {
                logout()
                navigate("/login")
              }}
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </div>
        </div>
      </aside>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {/* Main */}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur sm:px-6 lg:hidden">
          <button className="rounded-md p-2 hover:bg-accent" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold">Procurement Assistant</span>
        </header>

        {degraded && (
          <div className="border-b border-warning/30 bg-warning/8 px-4 py-2 text-xs text-foreground sm:px-6">
            <span className="font-medium">Running in degraded mode.</span>{" "}
            {capabilities && !capabilities.ai.configured && (
              <span className="text-muted-foreground">
                AI extraction is off — a deterministic heuristic parser is being used instead.{" "}
              </span>
            )}
            {capabilities && !capabilities.ocr.available && (
              <span className="text-muted-foreground">No OCR engine — scanned documents cannot be read.</span>
            )}
          </div>
        )}

        <main className="px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
