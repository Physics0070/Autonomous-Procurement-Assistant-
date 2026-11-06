import * as React from "react"
import { Navigate, useNavigate } from "react-router-dom"
import { useAuth } from "@/features/auth"
import { Button } from "@/components/ui/button"
import { Input, Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, Spinner } from "@/components/ui/feedback"
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
    <div className="flex min-h-screen bg-background">
      <div className="hidden w-1/2 flex-col justify-between bg-primary p-12 text-primary-foreground lg:flex">
        <div className="flex items-center gap-3">
          <BrandMark className="h-10 w-10" />
          <span className="text-lg font-semibold">Procurement</span>
        </div>

        <div className="space-y-8">
          <h1 className="max-w-md text-4xl font-semibold leading-tight tracking-tight">Buy smarter. Compare supplier prices in minutes.</h1>
          <ul className="space-y-4 text-lg">
            {[
              "Upload quotations as a PDF, photo or Excel file",
              "See the best supplier at a glance",
              "Create the purchase order in one click",
            ].map((line) => (
              <li key={line} className="flex items-start gap-3">
                <span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-primary-foreground" />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-sm text-primary-foreground/80">Made for small and medium businesses in India.</p>
      </div>

      {/* Form panel */}
      <div className="flex w-full items-center justify-center px-6 py-12 lg:w-1/2">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-2 lg:hidden">
            <BrandMark className="h-10 w-10" />
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
