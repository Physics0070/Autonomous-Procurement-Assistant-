import * as React from "react"
import { Navigate, useNavigate } from "react-router-dom"
import { useAuth } from "@/features/auth"
import { Button } from "@/components/ui/button"
import { Input, Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, Spinner } from "@/components/ui/feedback"
import { SupplyNetwork } from "@/components/SupplyNetwork"
import { BrandMark } from "@/components/BrandMark"

const INDUSTRIES = [
  "Manufacturing",
  "Construction",
  "Engineering",
  "Retail",
  "Pharmaceuticals",
  "Textiles",
  "Food Processing",
  "Logistics",
  "Other",
]

export function LoginPage() {
  const { login, register, isAuthenticated, isLoading } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = React.useState<"login" | "register">("login")
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  if (isAuthenticated) return <Navigate to="/" replace />

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    const form = new FormData(event.currentTarget)
    try {
      if (mode === "login") {
        await login(String(form.get("email")), String(form.get("password")))
      } else {
        await register({
          name: String(form.get("name")),
          email: String(form.get("email")),
          password: String(form.get("password")),
          organization_name: String(form.get("organization_name")),
          industry: String(form.get("industry") || "") || undefined,
        })
      }
      navigate("/")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      <div className="stage" aria-hidden>
        <i />
      </div>
      <div className="grain" aria-hidden />

      {/* Brand panel: the live supply network is the first thing anyone sees. */}
      <div className="relative hidden w-[55%] flex-col justify-between overflow-hidden p-12 lg:flex">
        <SupplyNetwork className="absolute inset-0 h-full w-full [mask-image:linear-gradient(to_right,black_70%,transparent)]" nodes={34} hubPulse={3} />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-background/70 via-transparent to-background/80" />
        <div className="relative flex items-center gap-3">
          <BrandMark className="h-11 w-11 drop-shadow-[0_0_18px_hsl(var(--glow)/0.6)]" />
          <span className="font-display text-lg font-bold tracking-tight">Autonomous Procurement Assistant</span>
        </div>

        <div className="relative space-y-7">
          <p className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-primary">
            <span className="h-px w-8 bg-primary" /> Ledger console
          </p>
          <h1 className="max-w-xl font-display text-5xl font-bold leading-[1.02] tracking-tight xl:text-6xl">
            Turn messy quotations into <span className="text-gradient">decisions you can defend.</span>
          </h1>
          <p className="max-w-md text-[15px] text-muted-foreground">
            Ingest PDFs, scans, photos and spreadsheets. Normalise them into one comparable structure. Rank suppliers on numbers you can audit.
          </p>
          <ul className="space-y-3 text-sm">
            {[
              "Original documents are never overwritten",
              "Scoring is deterministic; AI only explains it",
              "Missing data is flagged, never invented",
            ].map((line) => (
              <li key={line} className="flex items-center gap-3 text-foreground/85">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary shadow-[0_0_10px_hsl(var(--glow))]" />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Built for small and mid-sized enterprises</p>
      </div>

      {/* Form panel */}
      <div className="relative flex w-full items-center justify-center px-6 py-12 lg:w-[45%]">
        <div className="glass w-full max-w-sm animate-rise space-y-6 rounded-3xl p-8">
          <div className="space-y-2 lg:hidden">
            <BrandMark className="h-10 w-10" />
          </div>

          <div className="space-y-1.5">
            <h2 className="font-display text-3xl font-bold tracking-tight">
              {mode === "login" ? "Sign in" : "Create your workspace"}
            </h2>
            <p className="text-sm text-muted-foreground">
              {mode === "login"
                ? "Access your organization's procurement workspace."
                : "Set up an organization and become its administrator."}
            </p>
          </div>

          {error && <Alert tone="error">{error}</Alert>}

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div className="space-y-1.5">
                <Label htmlFor="name">Your name</Label>
                <Input id="name" name="name" required placeholder="Asha Patil" autoComplete="name" />
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="email">Work email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                required
                placeholder="you@company.com"
                autoComplete="email"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                required
                minLength={8}
                placeholder={mode === "register" ? "At least 8 characters" : "••••••••"}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </div>

            {mode === "register" && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="organization_name">Organization</Label>
                  <Input
                    id="organization_name"
                    name="organization_name"
                    required
                    placeholder="Acme Engineering Pvt Ltd"
                    autoComplete="organization"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="industry">Industry</Label>
                  <Select id="industry" name="industry" defaultValue="Manufacturing">
                    {INDUSTRIES.map((industry) => (
                      <option key={industry} value={industry}>
                        {industry}
                      </option>
                    ))}
                  </Select>
                </div>
              </>
            )}

            <Button type="submit" className="w-full" disabled={busy || isLoading}>
              {busy && <Spinner />}
              {mode === "login" ? "Sign in" : "Create workspace"}
            </Button>
          </form>

          <p className="text-center text-sm text-muted-foreground">
            {mode === "login" ? "No workspace yet?" : "Already have an account?"}{" "}
            <button
              type="button"
              className="font-medium text-primary underline-offset-4 hover:underline"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login")
                setError(null)
              }}
            >
              {mode === "login" ? "Create one" : "Sign in"}
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
