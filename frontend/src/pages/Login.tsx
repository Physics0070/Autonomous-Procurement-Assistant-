import * as React from "react"
import { Navigate, useNavigate } from "react-router-dom"
import { FileStack } from "lucide-react"
import { useAuth } from "@/features/auth"
import { Button } from "@/components/ui/button"
import { Input, Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, Spinner } from "@/components/ui/feedback"

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
      {/* Brand panel */}
      <div className="hidden w-1/2 flex-col justify-between bg-primary p-12 text-primary-foreground lg:flex">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-foreground/15">
            <FileStack className="h-5 w-5" />
          </div>
          <span className="font-semibold">Autonomous Procurement Assistant</span>
        </div>

        <div className="space-y-6">
          <h1 className="max-w-md text-3xl font-semibold leading-tight tracking-tight">
            Turn messy supplier quotations into decisions you can defend.
          </h1>
          <p className="max-w-md text-primary-foreground/75">
            Ingest PDFs, scans, photos and spreadsheets. Extract and normalize them into one
            comparable structure. Rank suppliers on numbers you can audit.
          </p>
          <ul className="space-y-2.5 text-sm text-primary-foreground/85">
            {[
              "Original documents are never overwritten",
              "Scoring is deterministic — AI only explains it",
              "Missing data is flagged, never invented",
            ].map((line) => (
              <li key={line} className="flex items-start gap-2.5">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-foreground/60" />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-primary-foreground/50">Built for small and mid-sized enterprises.</p>
      </div>

      {/* Form panel */}
      <div className="flex w-full items-center justify-center px-6 py-12 lg:w-1/2">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-2 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <FileStack className="h-5 w-5" />
            </div>
          </div>

          <div className="space-y-1.5">
            <h2 className="text-2xl font-semibold tracking-tight">
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
