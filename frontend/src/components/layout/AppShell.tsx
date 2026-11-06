import * as React from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  BarChart3,
  Building2,
  ClipboardList,
  FileStack,
  LayoutDashboard,
  LogOut,
  Bot,
  FileText,
  LineChart,
  Mail,
  Menu,
  Moon,
  Plug,
  Search,
  Settings,
  Sun,
  X,
} from "lucide-react"
import { useAuth } from "@/features/auth"
import { useCapabilities } from "@/hooks/queries"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn, initials } from "@/lib/utils"
import { CommandPalette, type Command } from "@/components/CommandPalette"
import { BrandMark } from "@/components/BrandMark"

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/requests", label: "Procurement", icon: ClipboardList },
  { to: "/documents", label: "Documents", icon: FileStack },
  { to: "/suppliers", label: "Suppliers", icon: Building2 },
  { to: "/comparison", label: "Comparison", icon: BarChart3 },
  { to: "/communications", label: "Communications", icon: Mail },
  { to: "/purchase-orders", label: "Purchase orders", icon: FileText },
  { to: "/assistant", label: "Assistant", icon: Bot },
  { to: "/analytics", label: "Analytics", icon: LineChart },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/settings", label: "Settings", icon: Settings },
]

function useTheme() {
  const [theme, setTheme] = React.useState<"light" | "dark">(() => {
    try {
      const stored = localStorage.getItem("apa.theme")
      if (stored === "dark" || stored === "light") return stored
    } catch {
      /* storage unavailable */
    }
    return "dark"
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
  const location = useLocation()
  const { theme, toggle } = useTheme()
  const [mobileOpen, setMobileOpen] = React.useState(false)
  const [paletteOpen, setPaletteOpen] = React.useState(false)

  const degraded = capabilities && (!capabilities.ai.configured || !capabilities.ocr.available)
  const current = NAV.find((item) => (item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)))

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const commands: Command[] = React.useMemo(
    () => [
      ...NAV.map((item) => ({ id: item.to, label: item.label, hint: "Go to page", icon: item.icon, run: () => navigate(item.to) })),
      {
        id: "theme",
        label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        hint: "Appearance",
        icon: theme === "dark" ? Sun : Moon,
        run: toggle,
      },
      {
        id: "signout",
        label: "Sign out",
        hint: "Account",
        icon: LogOut,
        run: () => {
          logout()
          navigate("/login")
        },
      },
    ],
    [navigate, theme, toggle, logout],
  )

  return (
    <div className="min-h-screen">
      <div className="stage" aria-hidden>
        <i />
      </div>
      <div className="grain" aria-hidden />
      <CommandPalette commands={commands} open={paletteOpen} onOpenChange={setPaletteOpen} />

      {/* Floating glass sidebar */}
      <aside
        className={cn(
          "glass fixed inset-y-3 left-3 z-40 flex w-64 flex-col rounded-3xl transition-transform duration-300 lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-[110%]",
        )}
      >
        <div className="flex h-[4.5rem] items-center gap-3 px-5">
          <BrandMark className="h-9 w-9 shrink-0 drop-shadow-[0_0_14px_hsl(var(--glow)/0.55)]" />
          <div className="min-w-0">
            <p className="truncate font-display text-[15px] font-bold leading-tight tracking-tight">Procurement</p>
            <p className="truncate font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">Ledger console</p>
          </div>
          <button className="ml-auto rounded-md p-1 lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-1 scrollbar-thin" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                cn(
                  "group/nav relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                  isActive ? "text-foreground" : "text-muted-foreground hover:translate-x-0.5 hover:text-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute inset-0 -z-10 rounded-xl bg-gradient-to-r from-primary/20 via-primary/10 to-transparent shadow-[0_0_0_1px_hsl(var(--primary)/0.28)_inset]" />
                  )}
                  {isActive && (
                    <span className="absolute -left-3 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-primary shadow-[0_0_14px_hsl(var(--glow))]" />
                  )}
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0 transition-all duration-200",
                      isActive ? "text-primary drop-shadow-[0_0_8px_hsl(var(--glow)/0.8)]" : "group-hover/nav:text-primary",
                    )}
                  />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Capability status: says plainly when the deployment is degraded. */}
        {capabilities && (
          <div className="mx-3 mb-2 space-y-2 rounded-2xl border bg-background/30 p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">AI</span>
              <Badge variant={capabilities.ai.configured ? "success" : "warning"}>
                {capabilities.ai.configured ? capabilities.ai.provider : "Not configured"}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">OCR</span>
              <Badge variant={capabilities.ocr.available ? "success" : "destructive"}>{capabilities.ocr.engine ?? "Unavailable"}</Badge>
            </div>
          </div>
        )}

        <div className="border-t p-3">
          <div className="flex items-center gap-2.5 rounded-xl px-2 py-1.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-[hsl(var(--glow-2))] text-xs font-bold text-primary-foreground shadow-[0_0_18px_-4px_hsl(var(--glow)/0.8)]">
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

      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm lg:hidden" onClick={() => setMobileOpen(false)} aria-hidden />}

      {/* Main */}
      <div className="lg:pl-[17.5rem]">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
          <button className="rounded-lg p-2 hover:bg-accent lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu className="h-4 w-4" />
          </button>
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
            </span>
            <span className="hidden sm:inline">Agents online</span>
            <span className="hidden text-border sm:inline">/</span>
            <span className="text-foreground">{current?.label ?? "Workspace"}</span>
          </div>
          <button
            onClick={() => setPaletteOpen(true)}
            className="ml-auto flex h-9 items-center gap-2 rounded-xl border bg-background/40 px-3 text-sm text-muted-foreground backdrop-blur transition-all hover:border-primary/50 hover:text-foreground hover:shadow-[0_0_24px_-8px_hsl(var(--glow)/0.7)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Open command palette"
          >
            <Search className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Jump to…</span>
            <span className="kbd">Ctrl K</span>
          </button>
        </header>

        {degraded && (
          <div className="mx-4 mb-2 rounded-xl border border-warning/30 bg-warning/10 px-4 py-2 text-xs text-foreground sm:mx-6 lg:mx-8">
            <span className="font-medium">Running in degraded mode.</span>{" "}
            {capabilities && !capabilities.ai.configured && (
              <span className="text-muted-foreground">AI extraction is off, so a deterministic heuristic parser is being used instead. </span>
            )}
            {capabilities && !capabilities.ocr.available && <span className="text-muted-foreground">No OCR engine: scanned documents cannot be read.</span>}
          </div>
        )}

        <main className="px-4 pb-16 pt-2 sm:px-6 lg:px-8">
          <div key={location.pathname} className="animate-rise">
            <Outlet />
          </div>
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
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-2">
        <h1 className="font-display text-4xl font-bold tracking-tight sm:text-5xl">
          <span className="text-gradient">{title}</span>
        </h1>
        {description && <p className="max-w-2xl text-[15px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
