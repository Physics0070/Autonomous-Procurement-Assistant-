import * as React from "react"
import { CloudUpload, Download, ExternalLink, FileText, PackageCheck } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/feedback"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  useFileToDrive, usePurchaseOrderActions, usePurchaseOrders, type POActionBody, type PurchaseOrder, type Receipt,
} from "@/hooks/automation"
import { downloadFile } from "@/lib/api"
import { cn, formatCurrency, formatDate, formatNumber } from "@/lib/utils"

const STATUS_LABEL = {
  draft: "Draft", approved: "Approved", issued: "Sent", delivered: "Delivered", closed: "Closed", cancelled: "Cancelled",
} as const

const GENERIC_ERROR = "Something went wrong, please try again."
function friendly(e: unknown): string {
  const msg = e instanceof Error ? e.message : ""
  if (/google|drive|connect/i.test(msg) && !/5\d\d/.test(msg) && msg.length < 140) return msg
  if (!msg || msg.length > 140 || /[45]\d\d|gateway|unavailable|traceback|exception|json/i.test(msg)) return GENERIC_ERROR
  return msg
}

const STATUS_TONE = {
  draft: "muted", approved: "default", issued: "warning", delivered: "success", closed: "secondary", cancelled: "destructive",
} as const

// What the next button does in each state (cancel is separate).
const NEXT: Partial<Record<PurchaseOrder["status"], { action: string; label: string }>> = {
  draft: { action: "approve", label: "Approve" },
  approved: { action: "issue", label: "Send to supplier" },
  delivered: { action: "close", label: "Close" },
}

/** Received / rejected per line and the invoiced amount, recorded at delivery (or afterwards). */
function ReceiptFields({ po, onSubmit, submitLabel, busy, children }: {
  po: PurchaseOrder; onSubmit: (receipt: Receipt) => void; submitLabel: string; busy: boolean; children?: React.ReactNode
}) {
  const [received, setReceived] = React.useState(() => po.lines.map((l) => String(l.quantity)))
  const [rejected, setRejected] = React.useState(() => po.lines.map(() => "0"))
  const [invoice, setInvoice] = React.useState("")
  const [invoiceType, setInvoiceType] = React.useState<NonNullable<Receipt["invoice_type"]>>("final")
  const [approved, setApproved] = React.useState("")
  const edit = (setter: typeof setReceived, i: number) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setter((rows) => rows.map((v, j) => (j === i ? e.target.value : v)))
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({
      lines: po.lines.map((_, i) => ({ line: i, received_quantity: Number(received[i] || 0), rejected_quantity: Number(rejected[i] || 0) })),
      invoice_amount: invoice.trim() === "" ? null : Number(invoice),
      invoice_type: invoiceType,
      approved_amount: approved.trim() === "" ? null : Number(approved),
    })
  }
  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border p-3">
      <p className="text-sm text-muted-foreground">What arrived. This feeds the supplier's performance score.</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Item</TableHead>
            <TableHead className="text-right">Ordered</TableHead>
            <TableHead className="text-right">Received</TableHead>
            <TableHead className="text-right">Rejected</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {po.lines.map((line, i) => (
            <TableRow key={i}>
              <TableCell>{line.description}</TableCell>
              <TableCell className="text-right">{formatNumber(line.quantity, 2)} {line.unit}</TableCell>
              <TableCell className="text-right">
                <Input aria-label={`Received, ${line.description}`} type="number" min={0} step="any" required
                       value={received[i]} onChange={edit(setReceived, i)} className="ml-auto w-24 text-right" />
              </TableCell>
              <TableCell className="text-right">
                <Input aria-label={`Rejected at inspection, ${line.description}`} type="number" min={0} step="any"
                       value={rejected[i]} onChange={edit(setRejected, i)} className="ml-auto w-24 text-right" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="flex flex-wrap items-end gap-2">
        {children}
        <div className="space-y-1">
          <Label htmlFor={`invoice-${po.id}`}>Invoice amount (optional)</Label>
          <Input id={`invoice-${po.id}`} type="number" min={0} step="any" value={invoice}
                 onChange={(e) => setInvoice(e.target.value)} className="w-40" placeholder={String(po.pricing.total)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`invoice-type-${po.id}`}>Invoice type</Label>
          <select id={`invoice-type-${po.id}`} value={invoiceType} onChange={(e) => setInvoiceType(e.target.value as typeof invoiceType)}
                  className="h-9 rounded-md border bg-background px-2 text-sm">
            <option value="final">Final invoice</option>
            <option value="partial">Partial invoice</option>
            <option value="credit_note">Credit note</option>
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor={`approved-${po.id}`}>Agreed revised total (if the price was changed)</Label>
          <Input id={`approved-${po.id}`} type="number" min={0} step="any" value={approved}
                 onChange={(e) => setApproved(e.target.value)} className="w-40" />
        </div>
        <Button type="submit" disabled={busy}>{busy ? <Spinner /> : <PackageCheck className="h-4 w-4" />}{submitLabel}</Button>
      </div>
    </form>
  )
}

function ReceiptSummary({ po }: { po: PurchaseOrder }) {
  const r = po.receipt
  if (!r) return null
  const rejected = r.lines.reduce((sum, l) => sum + l.rejected_quantity, 0)
  const kind = { final: "", partial: " (partial invoice)", credit_note: " (credit note)" }[r.invoice_type ?? "final"]
  return (
    <p className="text-sm">
      <span className="text-muted-foreground">Received:</span>{" "}
      <Badge variant={r.in_full ? "success" : "warning"}>{r.in_full ? "Accepted in full" : "Not accepted in full"}</Badge>{" "}
      {rejected > 0 && <Badge variant="destructive">{formatNumber(rejected, 2)} rejected</Badge>}{" "}
      {r.invoice_amount != null && (
        <span className="text-muted-foreground">Invoiced {formatCurrency(r.invoice_amount, po.pricing.currency)}{kind}</span>
      )}
    </p>
  )
}

function Detail({ po }: { po: PurchaseOrder }) {
  const { act, receipt } = usePurchaseOrderActions()
  const drive = useFileToDrive()
  const [deliveredOn, setDeliveredOn] = React.useState(() => new Date().toISOString().slice(0, 10))
  const [confirmCancel, setConfirmCancel] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const run = (action: string, body?: POActionBody) =>
    act.mutateAsync({ id: po.id, action, body }).then(() => setError(null)).catch((e) => setError(friendly(e)))
  const saveReceipt = (r: Receipt) =>
    receipt.mutateAsync({ id: po.id, receipt: r }).then(() => setError(null)).catch((e) => setError(friendly(e)))
  const next = NEXT[po.status]
  const cur = po.pricing.currency

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-base">{po.po_number}</CardTitle>
          <p className="text-sm text-muted-foreground">{po.supplier.name} · {formatDate(po.created_at)}</p>
        </div>
        <Badge variant={STATUS_TONE[po.status]}>{STATUS_LABEL[po.status]}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        {drive.error && <Alert tone="error">{friendly(drive.error)}</Alert>}
        {po.warnings.length > 0 && (
          <Alert tone="warning" title="Please check">
            <ul className="list-inside list-disc">{po.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          </Alert>
        )}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Price</TableHead>
              <TableHead className="text-right">GST</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {po.lines.map((line, i) => (
              <TableRow key={i}>
                <TableCell>{line.description}</TableCell>
                <TableCell className="text-right">{formatNumber(line.quantity, 2)} {line.unit}</TableCell>
                <TableCell className="text-right">{formatCurrency(line.unit_price, cur)}</TableCell>
                <TableCell className="text-right">{line.tax_percentage}%</TableCell>
                <TableCell className="text-right">{formatCurrency(line.line_total, cur)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        <dl className="ml-auto max-w-xs space-y-1 text-sm">
          <div className="flex justify-between"><dt className="text-muted-foreground">Subtotal</dt><dd>{formatCurrency(po.pricing.subtotal, cur)}</dd></div>
          {!!po.pricing.discount && (
            <div className="flex justify-between"><dt className="text-muted-foreground">Less discount</dt><dd>−{formatCurrency(po.pricing.discount, cur)}</dd></div>
          )}
          {po.pricing.taxes.map((t) => (
            <div key={t.name} className="flex justify-between"><dt className="text-muted-foreground">{t.name} {t.rate}%</dt><dd>{formatCurrency(t.amount, cur)}</dd></div>
          ))}
          <div className="flex justify-between"><dt className="text-muted-foreground">Freight</dt><dd>{formatCurrency(po.pricing.freight, cur)}</dd></div>
          <div className="flex justify-between border-t pt-1 font-semibold"><dt>Total</dt><dd>{formatCurrency(po.pricing.total, cur)}</dd></div>
        </dl>

        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <p><span className="text-muted-foreground">Delivery time:</span> {po.terms.delivery_days != null ? `${po.terms.delivery_days} days` : "Not given"}</p>
          <p><span className="text-muted-foreground">Payment:</span> {po.terms.payment_terms ?? "Not given"}</p>
          {po.expected_delivery_date && (
            <p>
              <span className="text-muted-foreground">Expected:</span> {formatDate(po.expected_delivery_date)}
            </p>
          )}
          {po.delivered_at && (
            <p>
              <span className="text-muted-foreground">Delivered:</span> {formatDate(po.delivered_at)}{" "}
              {po.on_time != null && (
                <Badge variant={po.on_time ? "success" : "destructive"}>{po.on_time ? "On time" : `${po.delay_days} day(s) late`}</Badge>
              )}
            </p>
          )}
          <ReceiptSummary po={po} />
          {po.status === "cancelled" && po.cancelled_by && (
            <p><span className="text-muted-foreground">Cancelled by:</span> {po.cancelled_by === "supplier" ? "the supplier" : "us"}</p>
          )}
        </div>

        {po.status === "issued" && (
          <ReceiptFields po={po} busy={act.isPending} submitLabel="Mark as delivered"
                         onSubmit={(r) => run("deliver", { delivered_at: new Date(`${deliveredOn}T12:00:00`).toISOString(), receipt: r })}>
            <div className="space-y-1">
              <Label htmlFor={`delivered-${po.id}`}>Delivered on</Label>
              <Input id={`delivered-${po.id}`} type="date" value={deliveredOn} onChange={(e) => setDeliveredOn(e.target.value)} className="w-40" />
            </div>
          </ReceiptFields>
        )}
        {["delivered", "closed"].includes(po.status) && !po.receipt && (
          <ReceiptFields po={po} busy={receipt.isPending} submitLabel="Save what arrived" onSubmit={saveReceipt} />
        )}

        <div className="flex flex-wrap items-end gap-2">
          {next && (
            <Button onClick={() => run(next.action)} disabled={act.isPending}>
              {act.isPending && <Spinner />}{next.label}
            </Button>
          )}
          <Button variant="outline" onClick={() => downloadFile(`/purchase-orders/${po.id}/pdf`, `${po.po_number}.pdf`).catch((e) => setError(friendly(e)))}>
            <Download className="h-4 w-4" />Download PDF
          </Button>
          {po.drive_file ? (
            <Button variant="outline" asChild>
              <a href={po.drive_file.link} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />Open in Drive
              </a>
            </Button>
          ) : (
            <Button variant="outline" onClick={() => drive.mutate(po.id)} disabled={drive.isPending}>
              {drive.isPending ? <Spinner /> : <CloudUpload className="h-4 w-4" />}Save to Drive
            </Button>
          )}
          {["draft", "approved"].includes(po.status) && (
            <Button variant="ghost" className="text-destructive" onClick={() => run("cancel", { cancelled_by: "buyer" })} disabled={act.isPending}>Cancel</Button>
          )}
          {po.status === "issued" && !confirmCancel && (
            <Button variant="ghost" className="text-destructive" onClick={() => setConfirmCancel(true)}>Cancel</Button>
          )}
          {po.status === "issued" && confirmCancel && (
            <div className="flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Who cancelled this order?">
              <span className="text-muted-foreground">Who cancelled?</span>
              <Button variant="outline" className="text-destructive" disabled={act.isPending}
                      onClick={() => run("cancel", { cancelled_by: "supplier" })}>Supplier could not deliver</Button>
              <Button variant="outline" disabled={act.isPending} onClick={() => run("cancel", { cancelled_by: "buyer" })}>We cancelled</Button>
              <Button variant="ghost" onClick={() => setConfirmCancel(false)}>Keep order</Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function PurchaseOrdersPage() {
  const { data, isLoading, error, refetch } = usePurchaseOrders()
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  const selected = data?.find((p) => p.id === selectedId) ?? data?.[0]

  return (
    <div>
      <PageHeader title="Purchase orders" />
      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data?.length ? (
        <EmptyState icon={FileText} title="No purchase orders yet" description="Compare prices and pick a supplier to create one." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <Card className="h-fit">
            <ul className="divide-y">
              {data.map((po) => (
                <li key={po.id}>
                  <button onClick={() => setSelectedId(po.id)} className={cn("w-full px-4 py-3 text-left hover:bg-accent", selected?.id === po.id && "bg-primary/5")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{po.po_number}</span>
                      <Badge variant={STATUS_TONE[po.status]}>{STATUS_LABEL[po.status]}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {po.supplier.name} · {formatCurrency(po.pricing.total, po.pricing.currency)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {selected && <Detail po={selected} />}
        </div>
      )}
    </div>
  )
}
