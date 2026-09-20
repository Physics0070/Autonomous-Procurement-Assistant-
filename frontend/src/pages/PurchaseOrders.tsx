import * as React from "react"
import { CloudUpload, Download, ExternalLink, FileText, PackageCheck } from "lucide-react"
import { Link } from "react-router-dom"
import { PageHeader } from "@/components/layout/AppShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/feedback"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useFileToDrive, usePurchaseOrderActions, usePurchaseOrders, type PurchaseOrder } from "@/hooks/automation"
import { downloadFile } from "@/lib/api"
import { cn, formatCurrency, formatDate, formatDateTime, formatNumber } from "@/lib/utils"

const STATUS_TONE = {
  draft: "muted", approved: "default", issued: "warning", delivered: "success", closed: "secondary", cancelled: "destructive",
} as const

// What the next button does in each state (cancel is separate).
const NEXT: Partial<Record<PurchaseOrder["status"], { action: string; label: string }>> = {
  draft: { action: "approve", label: "Approve" },
  approved: { action: "issue", label: "Issue to supplier" },
  delivered: { action: "close", label: "Close" },
}

function Detail({ po }: { po: PurchaseOrder }) {
  const { act } = usePurchaseOrderActions()
  const drive = useFileToDrive()
  const [deliveredOn, setDeliveredOn] = React.useState(() => new Date().toISOString().slice(0, 10))
  const [error, setError] = React.useState<string | null>(null)
  const run = (action: string, deliveredAt?: string) =>
    act.mutateAsync({ id: po.id, action, deliveredAt }).then(() => setError(null)).catch((e) => setError(e.message))
  const next = NEXT[po.status]
  const cur = po.pricing.currency

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-base">{po.po_number}</CardTitle>
          <p className="text-sm text-muted-foreground">{po.supplier.name} · created {formatDate(po.created_at)}</p>
        </div>
        <Badge variant={STATUS_TONE[po.status]}>{po.status}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        {drive.error && <Alert tone="warning">{drive.error.message}</Alert>}
        {po.warnings.length > 0 && (
          <Alert tone="warning" title="Not on this purchase order">
            <ul className="list-inside list-disc">{po.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          </Alert>
        )}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Rate</TableHead>
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
          {po.pricing.taxes.map((t) => (
            <div key={t.name} className="flex justify-between"><dt className="text-muted-foreground">{t.name} {t.rate}%</dt><dd>{formatCurrency(t.amount, cur)}</dd></div>
          ))}
          <div className="flex justify-between"><dt className="text-muted-foreground">Freight</dt><dd>{formatCurrency(po.pricing.freight, cur)}</dd></div>
          <div className="flex justify-between border-t pt-1 font-semibold"><dt>Total</dt><dd>{formatCurrency(po.pricing.total, cur)}</dd></div>
        </dl>

        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <p><span className="text-muted-foreground">Delivery terms:</span> {po.terms.delivery_days != null ? `${po.terms.delivery_days} days` : "not stated"}</p>
          <p><span className="text-muted-foreground">Payment:</span> {po.terms.payment_terms ?? "not stated"}</p>
          {po.expected_delivery_date && (
            <p>
              <span className="text-muted-foreground">Expected:</span> {formatDate(po.expected_delivery_date)}
              {po.terms.delivery_date && <span className="text-muted-foreground"> (supplier committed to this date)</span>}
            </p>
          )}
          {po.delivered_at && (
            <p>
              <span className="text-muted-foreground">Delivered:</span> {formatDate(po.delivered_at)}{" "}
              {po.on_time != null && (
                <Badge variant={po.on_time ? "success" : "destructive"}>{po.on_time ? "on time" : `${po.delay_days} day(s) late`}</Badge>
              )}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-2">
          {next && (
            <Button onClick={() => run(next.action)} disabled={act.isPending}>
              {act.isPending && <Spinner />}{next.label}
            </Button>
          )}
          {po.status === "issued" && (
            <>
              <div className="space-y-1">
                <Label htmlFor="delivered">Delivered on</Label>
                <Input id="delivered" type="date" value={deliveredOn} onChange={(e) => setDeliveredOn(e.target.value)} className="w-40" />
              </div>
              <Button onClick={() => run("deliver", new Date(`${deliveredOn}T12:00:00`).toISOString())} disabled={act.isPending}>
                <PackageCheck className="h-4 w-4" />Record delivery
              </Button>
            </>
          )}
          <Button variant="outline" onClick={() => downloadFile(`/purchase-orders/${po.id}/pdf`, `${po.po_number}.pdf`).catch((e) => setError(e.message))}>
            <Download className="h-4 w-4" />PDF
          </Button>
          {po.drive_file ? (
            <Button variant="outline" asChild>
              <a href={po.drive_file.link} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" />In Drive
              </a>
            </Button>
          ) : (
            <Button variant="outline" onClick={() => drive.mutate(po.id)} disabled={drive.isPending}
                    title="Uploads this PO's PDF to your Google Drive (needs the Google connection)">
              {drive.isPending ? <Spinner /> : <CloudUpload className="h-4 w-4" />}Save to Drive
            </Button>
          )}
          {["draft", "approved", "issued"].includes(po.status) && (
            <Button variant="ghost" className="text-destructive" onClick={() => run("cancel")} disabled={act.isPending}>Cancel</Button>
          )}
        </div>
        {po.status === "approved" && (
          <p className="text-xs text-muted-foreground">
            A covering email draft was created — find it on <Link to="/communications" className="text-primary hover:underline">Communications</Link> and attach the PDF when you send it.
          </p>
        )}
        <p className="text-xs text-muted-foreground">Recorded deliveries become the supplier's delivery history, which the ML reliability model uses.</p>

        <div className="border-t pt-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">History</p>
          <ul className="space-y-1 text-xs">
            {po.history.map((h, i) => (
              <li key={i} className="flex justify-between"><span>{h.action}</span><span className="text-muted-foreground">{formatDateTime(h.at)}</span></li>
            ))}
          </ul>
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
      <PageHeader title="Purchase orders" description="Created by awarding a quotation on the comparison page. Approve, issue, then record delivery." />
      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data?.length ? (
        <EmptyState icon={FileText} title="No purchase orders yet" description="Open a comparison and choose Award on the supplier you want to buy from." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <Card className="h-fit">
            <ul className="divide-y">
              {data.map((po) => (
                <li key={po.id}>
                  <button onClick={() => setSelectedId(po.id)} className={cn("w-full px-4 py-3 text-left hover:bg-accent", selected?.id === po.id && "bg-primary/5")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{po.po_number}</span>
                      <Badge variant={STATUS_TONE[po.status]}>{po.status}</Badge>
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
