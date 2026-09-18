import * as React from "react"
import { Link } from "react-router-dom"
import { Building2, Plus, Search } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input, Textarea } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Alert, EmptyState, ErrorState, LoadingState, ScoreBar, Spinner, ValueOrMissing } from "@/components/ui/feedback"
import { useCreateSupplier, useSuppliers } from "@/hooks/queries"
import { formatDate, percent } from "@/lib/utils"

function reliabilityTone(score: number) {
  if (score >= 0.7) return "success" as const
  if (score >= 0.45) return "warning" as const
  return "destructive" as const
}

function CreateSupplierDialog() {
  const [open, setOpen] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const create = useCreateSupplier()

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const form = new FormData(event.currentTarget)
    const value = (key: string) => {
      const raw = String(form.get(key) ?? "").trim()
      return raw === "" ? null : raw
    }
    try {
      await create.mutateAsync({
        name: String(form.get("name")).trim(),
        email: value("email"),
        phone: value("phone"),
        gst_number: value("gst_number"),
        address: value("address"),
      } as any)
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the supplier.")
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="h-4 w-4" />
          Add supplier
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add supplier</DialogTitle>
          <DialogDescription>
            Only the name is required. Suppliers routinely arrive with partial details, and missing
            fields lower the reliability score rather than blocking the record.
          </DialogDescription>
        </DialogHeader>

        {error && <Alert tone="error">{error}</Alert>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">Name *</Label>
            <Input id="name" name="name" required placeholder="Shree Plastics & Pipes Pvt Ltd" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" placeholder="sales@supplier.co.in" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="phone">Phone</Label>
              <Input id="phone" name="phone" placeholder="+91 98220 41556" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gst_number">GST number</Label>
            <Input id="gst_number" name="gst_number" placeholder="27AABCS1429B1ZQ" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="address">Address</Label>
            <Textarea id="address" name="address" rows={2} placeholder="Plot 42, MIDC, Pune - 411018" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Spinner />}
              Add supplier
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function SuppliersPage() {
  const [search, setSearch] = React.useState("")
  const [debounced, setDebounced] = React.useState("")
  const { data, isLoading, error, refetch } = useSuppliers(debounced || undefined)

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Suppliers"
        description="Suppliers you added, plus any identified automatically from uploaded quotations."
        actions={<CreateSupplierDialog />}
      />

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search suppliers…"
          className="pl-9"
        />
      </div>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={Building2}
          title={debounced ? "No suppliers match that search" : "No suppliers yet"}
          description={
            debounced
              ? "Try a different name."
              : "Add one manually, or upload a quotation — suppliers are created automatically from extracted GST numbers, emails and names."
          }
          action={!debounced ? <CreateSupplierDialog /> : undefined}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead>GST</TableHead>
                  <TableHead className="text-right">Quotations</TableHead>
                  <TableHead className="w-44">Reliability</TableHead>
                  <TableHead>Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((supplier) => (
                  <TableRow key={supplier.id}>
                    <TableCell>
                      <div className="font-medium">{supplier.name}</div>
                      {supplier.address && (
                        <div className="max-w-xs truncate text-xs text-muted-foreground">
                          {supplier.address}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">
                      <div>
                        <ValueOrMissing value={supplier.email} missingLabel="No email" />
                      </div>
                      <div className="text-xs text-muted-foreground">
                        <ValueOrMissing value={supplier.phone} missingLabel="No phone" />
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      <ValueOrMissing value={supplier.gst_number} missingLabel="Not provided" />
                    </TableCell>
                    <TableCell className="tabular text-right">{supplier.quotation_count}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <ScoreBar
                          value={supplier.reliability.score}
                          tone={reliabilityTone(supplier.reliability.score)}
                          className="flex-1"
                        />
                        <span className="tabular w-9 text-right text-xs">
                          {percent(supplier.reliability.score)}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        rule-based · n={supplier.reliability.sample_size}
                      </p>
                      {supplier.reliability.ml && (
                        <p className="mt-1 text-[11px]" title={[`${supplier.reliability.ml.model_version} · ${supplier.reliability.ml.trained_on}`,
                                  ...supplier.reliability.ml.signals.map((s) => s.text)].join(" | ")}>
                          <Badge variant={{ low: "success", medium: "warning", high: "destructive" }[supplier.reliability.ml.risk_level] as "success"}>
                            ML late risk {percent(supplier.reliability.ml.late_probability)}
                          </Badge>{" "}
                          <span className="text-muted-foreground">from {supplier.reliability.ml.history_count} deliveries</span>
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(supplier.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Alert tone="info" title="How reliability is calculated">
        <p>
          The bar is a transparent rule-based score from profile completeness, quotation history,
          extraction data quality and responsiveness.
        </p>
        <p>
          Once a supplier has delivered purchase orders, an <strong>ML late-delivery risk</strong> appears
          under it: a random-forest model trained on real USAID SCMS shipments (2006–2013) and tested on
          later ones it never saw. Hover it for the reasons. Its test scores are on the{" "}
          <Link to="/analytics" className="text-primary hover:underline">Analytics</Link> page.
        </p>
      </Alert>
    </div>
  )
}
