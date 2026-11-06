import * as React from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  Bot,
  Building2,
  ClipboardList,
  FileStack,
  FileText,
  GitCompareArrows,
  LayoutDashboard,
  LineChart,
  LogOut,
  Mail,
  Menu,
  Moon,
  Plug,
  Settings,
  Sun,
  X,
} from "lucide-react"
import { useAuth } from "@/features/auth"
import { Button } from "@/components/ui/button"
import { BrandMark } from "@/components/BrandMark"
import { cn, initials } from "@/lib/utils"

// Everyday words only. The first group is the daily work; the second is occasional.
const MAIN_NAV = [
  { to: "/", label: "Home", icon: LayoutDashboard, end: true },
  { to: "/requests", label: "Purchase requests", icon: ClipboardList },
  { to: "/documents", label: "Quotations", icon: FileStack },
  { to: "/comparison", label: "Compare prices", icon: GitCompareArrows },
  { to: "/suppliers", label: "Suppliers", icon: Building2 },
  { to: "/purchase-orders", label: "Purchase orders", icon: FileText },
  { to: "/communications", label: "Emails", icon: Mail },
]
const MORE_NAV = [
  { to: "/analytics", label: "Reports", icon: LineChart },
  { to: "/assistant", label: "Ask AI", icon: Bot },
  { to: "/integrations", label: "Connections", icon: Plug },
  { to: "/settings", label: "Settings", icon: Settings },
]

function useTheme() {
  const [theme, setTheme] = React.useState<"light" | "dark">(() => {
    try {
      return localStorage.getItem("apa.theme") === "dark" ? "dark" : "light"
    } catch {
      return "light"
    }
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

type NavItem = (typeof MAIN_NAV)[number]

function NavGroup({ items, onNavigate }: { items: NavItem[]; onNavigate: () => void }) {
  return (
    <div className="space-y-0.5">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] font-medium transition-colors",
              isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )
          }
        >
          <Icon className="h-[18px] w-[18px] shrink-0" />
          {label}
        </NavLink>
      ))}
    </div>
  )
}

export function AppShell() {
  const { user, organization, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { theme, toggle } = useTheme()
  const [mobileOpen, setMobileOpen] = React.useState(false)
  const close = () => setMobileOpen(false)

  return (
    <div className="min-h-screen bg-background">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r bg-card transition-transform lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-16 items-center gap-3 border-b px-5">
          <BrandMark className="h-8 w-8 shrink-0" />
          <p className="truncate text-base font-semibold leading-tight">Procurement</p>
          <button className="ml-auto rounded-md p-1 lg:hidden" onClick={close} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto p-3 scrollbar-thin" aria-label="Main">
          <NavGroup items={MAIN_NAV} onNavigate={close} />
          <div className="space-y-1">
            <p className="px-3 text-xs font-semibold text-muted-foreground">More</p>
            <NavGroup items={MORE_NAV} onNavigate={close} />
          </div>
        </nav>

        <div className="border-t p-3">
          <div className="flex items-center gap-3 px-2 py-1.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
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
              {theme === "dark" ? "Light mode" : "Dark mode"}
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

      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={close} aria-hidden />}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-card px-4 lg:hidden">
          <button className="rounded-md p-2 hover:bg-accent" onClick={() => setMobileOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-base font-semibold">Procurement</span>
        </header>

        <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div key={location.pathname} className="animate-fade-in">
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
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
