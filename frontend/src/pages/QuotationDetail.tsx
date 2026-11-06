import * as React from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeft, CheckCircle2, Download, Pencil, RefreshCw, Save, X } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input, Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StatusBadge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Alert, ErrorState, LoadingState, Spinner, ValueOrMissing } from "@/components/ui/feedback"
import {
  useApplyCorrections,
  useLinkQuotation,
  useQuotation,
  useReprocess,
  useRequests,
} from "@/hooks/queries"
import { downloadFile, fileUrl } from "@/lib/api"
import { AgentRuns } from "@/components/AgentRuns"
import { formatCurrency, formatDate, formatDateTime, formatNumber } from "@/lib/utils"
import type { NormalizedQuotation } from "@/types"

function ItemsTable({
  data,
  currency,
  editable,
  onEdit,
}: {
  data: NormalizedQuotation
  currency: string
  editable: boolean
  onEdit: (path: string, value: unknown) => void
}) {
  if (data.items.length === 0) {
    return <p className="px-5 py-8 text-center text-muted-foreground">No items found in this quotation.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead className="text-right">GST</TableHead>
          <TableHead className="text-right">Total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.items.map((item, index) => (
          <TableRow key={item.line_id}>
            <TableCell className="max-w-[240px] font-medium">
              <ValueOrMissing value={item.original_name} missingLabel="No name" />
            </TableCell>
            <TableCell className="text-right">
              {editable ? (
                <Input
                  type="number"
                  step="any"
                  className="h-8 w-20 text-right"
                  defaultValue={item.quantity ?? ""}
                  onChange={(e) =>
                    onEdit(`items.${index}.quantity`, e.target.value === "" ? null : Number(e.target.value))
                  }
                />
              ) : (
                <span className="tabular">
                  {formatNumber(item.quantity, 2)}
                  {item.unit ? ` ${item.unit}` : ""}
                </span>
              )}
            </TableCell>
            <TableCell className="text-right">
              {editable ? (
                <Input
                  type="number"
                  step="any"
                  className="h-8 w-24 text-right"
                  defaultValue={item.unit_price ?? ""}
                  onChange={(e) =>
                    onEdit(`items.${index}.unit_price`, e.target.value === "" ? null : Number(e.target.value))
                  }
                />
              ) : (
                <span className="tabular">
                  {item.unit_price != null ? formatCurrency(item.unit_price, currency) : "—"}
                </span>
              )}
            </TableCell>
            <TableCell className="tabular text-right">
              {item.tax_percentage != null ? `${item.tax_percentage}%` : "—"}
            </TableCell>
            <TableCell className="tabular text-right">
              {item.total_price != null
                ? formatCurrency(item.total_price, currency)
                : item.computed_total != null
                  ? formatCurrency(item.computed_total, currency)
                  : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function plainField(name: string): string {
  const text = name.replace(/[._]/g, " ").trim().toLowerCase()
  return text
}

export function QuotationDetailPage() {
  const { quotationId } = useParams<{ quotationId: string }>()
  const { data, isLoading, error, refetch } = useQuotation(quotationId)
  const { data: requests } = useRequests()
  const applyCorrections = useApplyCorrections(quotationId ?? "")
  const reprocess = useReprocess(quotationId ?? "")
  const link = useLinkQuotation(quotationId ?? "")

  const [editing, setEditing] = React.useState(false)
  const [edits, setEdits] = React.useState<Record<string, unknown>>({})
  const [saveError, setSaveError] = React.useState<string | null>(null)

  if (isLoading) return <LoadingState label="Loading quotation…" />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (!data) return null

  const effective = data.effective_data ?? data.normalized_data
  const currency = effective?.pricing.currency ?? data.currency ?? "INR"
  const validation = data.validation
  const raw = data.raw_content

  function onEdit(path: string, value: unknown) {
    setEdits((current) => ({ ...current, [path]: value }))
  }

  async function save() {
    setSaveError(null)
    try {
      await applyCorrections.mutateAsync({
        corrections: edits,
        note: "Reviewed and corrected in the quotation review screen.",
      })
      setEdits({})
      setEditing(false)
    } catch {
      setSaveError("We could not save your changes. Please try again.")
    }
  }

  // One plain list of things the buyer should look at.
  const things: string[] = []
  validation?.issues.forEach((issue) => things.push(issue.message))
  if (effective && effective.missing_fields.length > 0) {
    things.push(`We could not find: ${effective.missing_fields.map(plainField).join(", ")}.`)
  }

  const busy = ["QUEUED", "UPLOADED", "EXTRACTING", "AI_EXTRACTING", "NORMALIZING"].includes(
    data.processing_status,
  )
  const failed = data.processing_status === "FAILED"

  const grandTotal = effective?.pricing.total_amount ?? effective?.pricing.landed_total ?? null
  const matchResult = data.match_result

  return (
    <div className="space-y-6">
      <Link
        to="/documents"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        All quotations
      </Link>

      <PageHeader
        title={data.supplier_name ?? data.source.original_filename ?? "Quotation"}
        description={`Added on ${formatDate(data.created_at)}`}
        actions={
          <>
            <Button variant="outline" onClick={() => downloadFile(fileUrl(data.id))}>
              <Download className="h-4 w-4" />
              Download original
            </Button>
            <Button variant="outline" onClick={() => reprocess.mutate()} disabled={reprocess.isPending}>
              {reprocess.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              Read again
            </Button>
          </>
        }
      />

      {/* One status line */}
      {failed ? (
        <Alert tone="error" title="Could not read">
          <p>We could not read this file. Try Read again, or upload a clearer copy.</p>
        </Alert>
      ) : busy ? (
        <Alert tone="info" title="Reading">
          <p>We are reading this quotation. It will be ready in a minute.</p>
        </Alert>
      ) : things.length > 0 ? (
        <Alert
          tone="warning"
          title={`Needs checking: ${things.length} ${things.length === 1 ? "thing" : "things"} to look at`}
        >
          <ul className="list-inside list-disc space-y-1">
            {things.map((message, index) => (
              <li key={index}>{message}</li>
            ))}
          </ul>
        </Alert>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border bg-card px-4 py-3">
          <CheckCircle2 className="h-5 w-5 text-success" />
          <span className="font-medium">Ready</span>
        </div>
      )}

      {saveError && (
        <Alert tone="error">
          <div className="flex flex-wrap items-center gap-3">
            <span>{saveError}</span>
            <Button variant="outline" size="sm" onClick={save}>
              Try again
            </Button>
          </div>
        </Alert>
      )}

      {effective && (
        <>
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Items</CardTitle>
              <div className="flex gap-2">
                {editing ? (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setEditing(false)
                        setEdits({})
                      }}
                    >
                      <X className="h-4 w-4" />
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={save}
                      disabled={Object.keys(edits).length === 0 || applyCorrections.isPending}
                    >
                      {applyCorrections.isPending ? <Spinner /> : <Save className="h-4 w-4" />}
                      Save changes
                    </Button>
                  </>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                    <Pencil className="h-4 w-4" />
                    Correct values
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <ItemsTable data={effective} currency={currency} editable={editing} onEdit={onEdit} />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Total</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {(
                  [
                    ["Subtotal", effective.pricing.subtotal],
                    ["GST", effective.pricing.tax_amount],
                    ["Delivery charge", effective.pricing.transportation_cost],
                  ] as const
                )
                  .filter(([, amount]) => amount != null)
                  .map(([label, amount]) => (
                    <div key={label} className="flex justify-between gap-3">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="tabular">{formatCurrency(amount as number, currency)}</span>
                    </div>
                  ))}
                <div className="flex justify-between gap-3 border-t pt-2 font-semibold">
                  <span>Grand total</span>
                  <span className="tabular">
                    {grandTotal != null ? formatCurrency(grandTotal, currency) : "—"}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Delivery</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">Time</span>
                  <span className="font-medium">
                    <ValueOrMissing
                      value={
                        effective.delivery.delivery_days != null
                          ? `${effective.delivery.delivery_days} days`
                          : null
                      }
                    />
                  </span>
                </div>
                {editing && (
                  <div className="space-y-1">
                    <Label>Delivery time (days)</Label>
                    <Input
                      type="number"
                      className="h-8"
                      defaultValue={effective.delivery.delivery_days ?? ""}
                      onChange={(e) =>
                        onEdit("delivery.delivery_days", e.target.value === "" ? null : Number(e.target.value))
                      }
                    />
                  </div>
                )}
                <div>
                  <span className="text-muted-foreground">Terms</span>
                  <p className="mt-0.5">
                    <ValueOrMissing value={effective.delivery.delivery_terms} />
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Payment</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">Pay within</span>
                  <span className="font-medium">
                    <ValueOrMissing
                      value={
                        effective.payment_terms.payment_days != null
                          ? `${effective.payment_terms.payment_days} days`
                          : null
                      }
                    />
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Terms</span>
                  <p className="mt-0.5">
                    <ValueOrMissing value={effective.payment_terms.raw_terms} />
                  </p>
                </div>
                <div className="flex justify-between gap-3 border-t pt-2">
                  <span className="text-muted-foreground">Supplier GST number</span>
                  <span className="font-medium">
                    <ValueOrMissing value={effective.supplier.gst_number} />
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Purchase request</CardTitle>
        </CardHeader>
        <CardContent>
          <Select
            className="max-w-md"
            value={data.procurement_request_id ?? ""}
            onChange={(e) => link.mutate({ procurement_request_id: e.target.value })}
          >
            <option value="">Not linked</option>
            {requests?.items.map((request) => (
              <option key={request.id} value={request.id}>
                {request.title}
              </option>
            ))}
          </Select>
        </CardContent>
      </Card>

      {/* Technical details, collapsed */}
      <details className="rounded-lg border bg-card">
        <summary className="cursor-pointer px-4 py-3 font-medium">Technical details</summary>
        <div className="space-y-6 border-t p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <StatusBadge status={data.processing_status} />
            <span>File: {data.source.original_filename ?? "Untitled"}</span>
          </div>

          {matchResult && (
            <div className="space-y-2">
              <h3 className="font-medium">Item matching</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Asked for</TableHead>
                    <TableHead>Quoted as</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {matchResult.matches.map((match) => (
                    <TableRow key={match.request_item_id}>
                      <TableCell className="font-medium">{match.request_item_name}</TableCell>
                      <TableCell>{match.quotation_item_name ?? "No match"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {raw && raw.tables.length > 0 && (
            <div className="space-y-4">
              <h3 className="font-medium">Tables in the file</h3>
              {raw.tables.map((table, index) => (
                <div key={index} className="space-y-1">
                  <p className="text-sm text-muted-foreground">{table.name ?? `Table ${index + 1}`}</p>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {table.headers.map((header, i) => (
                          <TableHead key={i}>{header}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {table.rows.slice(0, 50).map((row, rowIndex) => (
                        <TableRow key={rowIndex}>
                          {(row as unknown[]).map((cell, cellIndex) => (
                            <TableCell key={cellIndex}>{cell == null ? "" : String(cell)}</TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ))}
            </div>
          )}

          {raw && (
            <div className="space-y-2">
              <h3 className="font-medium">Text in the file</h3>
              <pre className="max-h-[360px] overflow-auto scrollbar-thin whitespace-pre-wrap rounded-lg bg-muted p-4 text-sm">
                {raw.raw_text || "No text found."}
              </pre>
            </div>
          )}

          {data.user_corrections.length > 0 && (
            <div className="space-y-2">
              <h3 className="font-medium">Changes you made</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>What</TableHead>
                    <TableHead>Before</TableHead>
                    <TableHead>Now</TableHead>
                    <TableHead>When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.user_corrections.map((correction, index) => (
                    <TableRow key={index}>
                      <TableCell>{plainField(correction.path)}</TableCell>
                      <TableCell className="text-muted-foreground line-through">
                        {correction.previous_value == null ? "empty" : String(correction.previous_value)}
                      </TableCell>
                      <TableCell className="font-medium">{String(correction.new_value)}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDateTime(correction.corrected_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {data.processing_history.length > 0 && (
            <div className="space-y-2">
              <h3 className="font-medium">History</h3>
              <ul className="space-y-2">
                {data.processing_history.map((event, index) => (
                  <li key={index} className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={event.status} />
                    <span className="text-xs text-muted-foreground">{formatDateTime(event.at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <AgentRuns filters={{ quotation_id: data.id, graph: "quotation_processing" }} title="Steps" />
        </div>
      </details>
    </div>
  )
}
