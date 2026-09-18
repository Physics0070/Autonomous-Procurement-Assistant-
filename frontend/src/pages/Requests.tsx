import * as React from "react"
import { DraftRfqDialog } from "@/pages/Communications"
import { AgentRuns } from "@/components/AgentRuns"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  ArrowLeft,
  BarChart3,
  ClipboardList,
  FileStack,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input, Select, Textarea } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge, RequestStatusBadge, StatusBadge } from "@/components/ui/badge"
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
import { Alert, EmptyState, ErrorState, LoadingState, Spinner, ValueOrMissing } from "@/components/ui/feedback"
import {
  useCreateRequest,
  useDeleteRequest,
  useQuotations,
  useRequest,
  useRequests,
  useUpdateRequest,
} from "@/hooks/queries"
import { UploadDialog } from "@/pages/Documents"
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils"
import type { ProcurementStatus } from "@/types"

const STATUSES: ProcurementStatus[] = ["draft", "open", "comparing", "awarded", "closed", "cancelled"]

interface DraftItem {
  key: string
  name: string
  quantity: string
  unit: string
  specifications: string
}

function newItem(): DraftItem {
  return { key: Math.random().toString(36).slice(2), name: "", quantity: "", unit: "Nos", specifications: "" }
}

function CreateRequestDialog() {
  const [open, setOpen] = React.useState(false)
  const [items, setItems] = React.useState<DraftItem[]>([newItem()])
  const [error, setError] = React.useState<string | null>(null)
  const create = useCreateRequest()
  const navigate = useNavigate()

  function update(key: string, patch: Partial<DraftItem>) {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const form = new FormData(event.currentTarget)

    const payloadItems = items
      .filter((item) => item.name.trim())
      .map((item) => ({
        name: item.name.trim(),
        quantity: item.quantity ? Number(item.quantity) : null,
        unit: item.unit.trim() || null,
        specifications: item.specifications.trim() || null,
      }))

    if (payloadItems.length === 0) {
      setError("Add at least one item with a name.")
      return
    }

    try {
      const created = await create.mutateAsync({
        title: String(form.get("title")).trim(),
        description: String(form.get("description") ?? "").trim() || null,
        department: String(form.get("department") ?? "").trim() || null,
        currency: String(form.get("currency") || "INR"),
        status: String(form.get("status") || "open"),
        items: payloadItems,
      })
      setOpen(false)
      setItems([newItem()])
      navigate(`/requests/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the request.")
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="h-4 w-4" />
          New request
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New procurement request</DialogTitle>
          <DialogDescription>
            Describe what you need. Item names are normalized on save so supplier quotations can be
            matched against them regardless of how each supplier writes them.
          </DialogDescription>
        </DialogHeader>

        {error && <Alert tone="error">{error}</Alert>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="title">Title *</Label>
            <Input id="title" name="title" required placeholder="Plumbing materials for Unit 2" />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              name="description"
              rows={2}
              placeholder="Need 100 units of 2-inch PVC pipe plus fittings."
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="department">Department</Label>
              <Input id="department" name="department" placeholder="Maintenance" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="currency">Currency</Label>
              <Select id="currency" name="currency" defaultValue="INR">
                <option value="INR">INR</option>
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="status">Status</Label>
              <Select id="status" name="status" defaultValue="open">
                {STATUSES.map((status) => (
                  <option key={status} value={status} className="capitalize">
                    {status}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Items *</Label>
              <Button type="button" variant="ghost" size="sm" onClick={() => setItems((c) => [...c, newItem()])}>
                <Plus className="h-3.5 w-3.5" />
                Add item
              </Button>
            </div>

            <div className="space-y-2">
              {items.map((item, index) => (
                <div key={item.key} className="rounded-lg border p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">Item {index + 1}</span>
                    {items.length > 1 && (
                      <button
                        type="button"
                        className="rounded p-1 text-muted-foreground hover:bg-accent"
                        onClick={() => setItems((c) => c.filter((i) => i.key !== item.key))}
                        aria-label="Remove item"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[1fr_90px_90px]">
                    <Input
                      placeholder="PVC Pipe, 2 inch"
                      value={item.name}
                      onChange={(e) => update(item.key, { name: e.target.value })}
                    />
                    <Input
                      type="number"
                      min={0}
                      step="any"
                      placeholder="Qty"
                      value={item.quantity}
                      onChange={(e) => update(item.key, { quantity: e.target.value })}
                    />
                    <Input
                      placeholder="Unit"
                      value={item.unit}
                      onChange={(e) => update(item.key, { unit: e.target.value })}
                    />
                  </div>
                  <Input
                    className="mt-2"
                    placeholder="Specifications (optional)"
                    value={item.specifications}
                    onChange={(e) => update(item.key, { specifications: e.target.value })}
                  />
                </div>
              ))}
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Spinner />}
              Create request
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function RequestsPage() {
  const [status, setStatus] = React.useState<string>("")
  const { data, isLoading, error, refetch } = useRequests(status || undefined)
  const remove = useDeleteRequest()

  return (
    <div className="space-y-6">
      <PageHeader
        title="Procurement requests"
        description="What your organization needs to buy, and the quotations received against each."
        actions={<CreateRequestDialog />}
      />

      <Select value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-[200px]">
        <option value="">All statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s} className="capitalize">
            {s}
          </option>
        ))}
      </Select>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="No procurement requests yet"
          description="Create one to describe what you need, then upload supplier quotations against it."
          action={<CreateRequestDialog />}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Request</TableHead>
                  <TableHead>Department</TableHead>
                  <TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Quotations</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((request) => (
                  <TableRow key={request.id}>
                    <TableCell>
                      <Link to={`/requests/${request.id}`} className="font-medium hover:underline">
                        {request.title}
                      </Link>
                      {request.description && (
                        <p className="max-w-md truncate text-xs text-muted-foreground">
                          {request.description}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">
                      <ValueOrMissing value={request.department} missingLabel="—" />
                    </TableCell>
                    <TableCell className="tabular text-right">{request.items.length}</TableCell>
                    <TableCell className="tabular text-right">{request.quotation_count}</TableCell>
                    <TableCell>
                      <RequestStatusBadge status={request.status} />
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(request.created_at)}
                    </TableCell>
                    <TableCell>
                      <button
                        className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                        aria-label={`Delete ${request.title}`}
                        onClick={() => {
                          if (window.confirm(`Delete "${request.title}"? This cannot be undone.`)) {
                            remove.mutate(request.id)
                          }
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export function RequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>()
  const { data: request, isLoading, error, refetch } = useRequest(requestId)
  const { data: quotations } = useQuotations({ procurement_request_id: requestId })
  const update = useUpdateRequest(requestId ?? "")

  if (isLoading) return <LoadingState />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!request) return null

  return (
    <div className="space-y-6">
      <Link
        to="/requests"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All requests
      </Link>

      <PageHeader
        title={request.title}
        description={request.description ?? undefined}
        actions={
          <>
            <UploadDialog defaultRequestId={request.id} />
            <DraftRfqDialog requestId={request.id} />
            <Button variant="outline" asChild>
              <Link to={`/comparison/${request.id}`}>
                <BarChart3 className="h-4 w-4" />
                Compare suppliers
              </Link>
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <RequestStatusBadge status={request.status} />
        <Select
          value={request.status}
          onChange={(e) => update.mutate({ status: e.target.value })}
          className="h-8 max-w-[160px] text-xs"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s} className="capitalize">
              {s}
            </option>
          ))}
        </Select>
        <span className="text-sm text-muted-foreground">
          {request.department ?? "No department"} · {request.currency} · created{" "}
          {formatDate(request.created_at)}
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Requested items</CardTitle>
          <p className="text-sm text-muted-foreground">
            The normalized form is what quotation line items are matched against.
          </p>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Normalized</TableHead>
                <TableHead className="text-right">Quantity</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead>Specifications</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {request.items.map((item) => (
                <TableRow key={item.item_id}>
                  <TableCell className="font-medium">{item.name}</TableCell>
                  <TableCell>
                    <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                      {item.normalized_name ?? "—"}
                    </code>
                  </TableCell>
                  <TableCell className="tabular text-right">{formatNumber(item.quantity, 2)}</TableCell>
                  <TableCell className="text-sm">
                    {item.unit ?? "—"}
                    {item.normalized_unit && item.normalized_unit !== item.unit?.toLowerCase() && (
                      <span className="ml-1 text-xs text-muted-foreground">→ {item.normalized_unit}</span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-xs text-sm text-muted-foreground">
                    <ValueOrMissing value={item.specifications} missingLabel="—" />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Quotations received{" "}
            <Badge variant="secondary" className="ml-1">
              {quotations?.total ?? 0}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className={quotations?.items.length ? "p-0" : undefined}>
          {!quotations || quotations.items.length === 0 ? (
            <EmptyState
              icon={FileStack}
              title="No quotations yet"
              description="Upload supplier quotations against this request to compare them."
              action={<UploadDialog defaultRequestId={request.id} />}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Document</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {quotations.items.map((quotation) => (
                  <TableRow key={quotation.id}>
                    <TableCell>
                      <Link to={`/documents/${quotation.id}`} className="font-medium hover:underline">
                        {quotation.source.original_filename ?? "Untitled"}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm">
                      <ValueOrMissing value={quotation.supplier_name} missingLabel="Not identified" />
                    </TableCell>
                    <TableCell className="tabular text-right">{quotation.item_count}</TableCell>
                    <TableCell className="tabular text-right">
                      {quotation.total_amount != null
                        ? formatCurrency(quotation.total_amount, quotation.currency)
                        : "—"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={quotation.processing_status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <AgentRuns filters={{ procurement_request_id: request.id }} />
    </div>
  )
}
