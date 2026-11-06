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

const STATUS_LABELS: Record<ProcurementStatus, string> = {
  draft: "Draft",
  open: "Open",
  comparing: "Comparing",
  awarded: "Awarded",
  closed: "Closed",
  cancelled: "Cancelled",
}

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
      setError("Add at least one item and give it a name.")
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
      setError(err instanceof Error ? err.message : "We could not save this request. Please try again.")
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
          <DialogTitle>New purchase request</DialogTitle>
        </DialogHeader>

        {error && <Alert tone="error">{error}</Alert>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="title">Title</Label>
            <Input id="title" name="title" required placeholder="Plumbing materials for Unit 2" />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="description">Details (optional)</Label>
            <Textarea
              id="description"
              name="description"
              rows={2}
              placeholder="Need 100 units of 2-inch PVC pipe plus fittings."
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="department">Department (optional)</Label>
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
                  <option key={status} value={status}>
                    {STATUS_LABELS[status]}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Items</Label>
              <Button type="button" variant="ghost" size="sm" onClick={() => setItems((c) => [...c, newItem()])}>
                <Plus className="h-3.5 w-3.5" />
                Add item
              </Button>
            </div>

            <div className="space-y-2">
              {items.map((item, index) => (
                <div key={item.key} className="rounded-lg border p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm font-medium text-muted-foreground">Item {index + 1}</span>
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
                      placeholder="Item name, e.g. PVC pipe 2 inch"
                      value={item.name}
                      onChange={(e) => update(item.key, { name: e.target.value })}
                    />
                    <Input
                      type="number"
                      min={0}
                      step="any"
                      placeholder="Quantity"
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
                    placeholder="Details (optional)"
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
              Save request
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
        title="Purchase requests"
        actions={<CreateRequestDialog />}
      />

      <Select value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-[200px]">
        <option value="">All requests</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
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
          title="No purchase requests yet. Create your first request."
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
                        <p className="max-w-md truncate text-sm text-muted-foreground">
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
                          if (window.confirm(`Delete "${request.title}"? You cannot undo this.`)) {
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
        Purchase requests
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
          className="h-9 max-w-[160px] text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </Select>
        <span className="text-sm text-muted-foreground">
          {request.department ? `${request.department} · ` : ""}Created {formatDate(request.created_at)}
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Items you need</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">Quantity</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {request.items.map((item) => (
                <TableRow key={item.item_id}>
                  <TableCell className="font-medium">{item.name}</TableCell>
                  <TableCell className="tabular text-right">{formatNumber(item.quantity, 2)}</TableCell>
                  <TableCell className="text-sm">{item.unit ?? "—"}</TableCell>
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
              title="No quotations yet. Upload your first quotation."
              action={<UploadDialog defaultRequestId={request.id} />}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Quotation</TableHead>
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
                      <ValueOrMissing value={quotation.supplier_name} missingLabel="Not known" />
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
      <AgentRuns filters={{ procurement_request_id: request.id }} title="Activity" />
    </div>
  )
}
