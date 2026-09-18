import * as React from "react"
import { Link, useParams } from "react-router-dom"
import {
  AlertTriangle,
  ArrowLeft,
  Download,
  History,
  Pencil,
  RefreshCw,
  Save,
  Sparkles,
  X,
} from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input, Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge, ConfidenceBadge, StatusBadge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  Alert,
  ErrorState,
  LoadingState,
  ScoreBar,
  Spinner,
  ValueOrMissing,
} from "@/components/ui/feedback"
import {
  useApplyCorrections,
  useLinkQuotation,
  useQuotation,
  useReprocess,
  useRequests,
} from "@/hooks/queries"
import { downloadFile, fileUrl } from "@/lib/api"
import { AgentRuns } from "@/components/AgentRuns"
import { formatCurrency, formatDateTime, formatNumber, percent } from "@/lib/utils"
import type { NormalizedQuotation, QuotationDetail } from "@/types"

/** One row of the "where did this value come from" ladder. */
function ProvenanceRow({
  label,
  tone,
  children,
  note,
}: {
  label: string
  tone: "muted" | "ai" | "normalized" | "corrected"
  children: React.ReactNode
  note?: string
}) {
  const styles = {
    muted: "border-l-muted-foreground/30",
    ai: "border-l-primary/60",
    normalized: "border-l-success/60",
    corrected: "border-l-warning/70",
  }[tone]
  return (
    <div className={`border-l-2 pl-3 ${styles}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-0.5 text-sm">{children}</div>
      {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
    </div>
  )
}

function ItemsTable({
  data,
  currency,
  editable,
  edits,
  onEdit,
}: {
  data: NormalizedQuotation
  currency: string
  editable: boolean
  edits: Record<string, unknown>
  onEdit: (path: string, value: unknown) => void
}) {
  if (data.items.length === 0) {
    return <p className="px-5 py-8 text-center text-sm text-muted-foreground">No line items were extracted.</p>
  }

  const value = (path: string, fallback: unknown) => (path in edits ? edits[path] : fallback)

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item (as written)</TableHead>
          <TableHead>Normalized</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead>Unit</TableHead>
          <TableHead className="text-right">Unit price</TableHead>
          <TableHead className="text-right">Tax %</TableHead>
          <TableHead className="text-right">Line total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.items.map((item, index) => {
          const anomaly = (item.attributes?._price_anomaly ?? null) as
            | { status?: string; reason?: string }
            | null
          const note = item.attributes?._note as string | undefined
          return (
            <TableRow key={item.line_id}>
              <TableCell className="max-w-[240px]">
                <div className="font-medium">
                  <ValueOrMissing value={item.original_name} missingLabel="No description" />
                </div>
                {note && <p className="mt-0.5 text-xs italic text-warning">{note}</p>}
                {anomaly?.status && anomaly.status !== "NORMAL" && anomaly.status !== "INSUFFICIENT_DATA" && (
                  <p className="mt-0.5 text-xs text-warning">{anomaly.status.replace(/_/g, " ")}</p>
                )}
              </TableCell>
              <TableCell>
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                  {item.normalized_name ?? "—"}
                </code>
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
                  <span className="tabular">{formatNumber(item.quantity, 2)}</span>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {item.unit ?? "—"}
                {item.normalized_unit && (
                  <span className="ml-1 text-xs text-muted-foreground">→ {item.normalized_unit}</span>
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
                {item.total_price != null ? (
                  formatCurrency(item.total_price, currency)
                ) : item.computed_total != null ? (
                  <span title="Computed from quantity x unit price" className="text-muted-foreground">
                    {formatCurrency(item.computed_total, currency)}*
                  </span>
                ) : (
                  "—"
                )}
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
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
  const ai = data.ai_extraction
  const isHeuristic = ai?.provider === "heuristic"

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
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save corrections.")
    }
  }

  return (
    <div className="space-y-6">
      <Link
        to="/documents"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All documents
      </Link>

      <PageHeader
        title={data.source.original_filename ?? "Quotation"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.processing_status} />
            <span>
              {data.supplier_name ?? "Supplier not identified"} · uploaded{" "}
              {formatDateTime(data.created_at)}
            </span>
          </span>
        }
        actions={
          <>
            <Button variant="outline" onClick={() => downloadFile(fileUrl(data.id))}>
              <Download className="h-4 w-4" />
              Original
            </Button>
            <Button variant="outline" onClick={() => reprocess.mutate()} disabled={reprocess.isPending}>
              {reprocess.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              Reprocess
            </Button>
          </>
        }
      />

      {data.error && <Alert tone="error" title="Processing failed">{data.error}</Alert>}

      {isHeuristic && (
        <Alert tone="warning" title="Extracted without AI">
          <p>
            No AI provider is configured, so a deterministic heuristic parser produced these values.
            It fills a field only when the pattern is unambiguous and leaves everything else empty
            rather than guessing. Review carefully before relying on it.
          </p>
        </Alert>
      )}

      {/* Provenance ladder */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Where these values came from</CardTitle>
          <p className="text-sm text-muted-foreground">
            Each layer is stored separately. Later layers never overwrite earlier ones.
          </p>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <ProvenanceRow label="1 · Original file" tone="muted" note={`${data.document_type.replace(/_/g, " ")}`}>
            <a
              href="#"
              onClick={(event) => {
                event.preventDefault()
                void downloadFile(fileUrl(data.id))
              }}
              className="text-primary underline-offset-4 hover:underline"
            >
              {data.source.original_filename}
            </a>
          </ProvenanceRow>
          <ProvenanceRow
            label="2 · Raw extraction"
            tone="muted"
            note={raw?.ocr_used ? `OCR via ${raw.ocr_engine}` : "Native text layer"}
          >
            {raw ? `${raw.raw_text.length.toLocaleString()} chars · ${raw.tables.length} table(s)` : "—"}
          </ProvenanceRow>
          <ProvenanceRow
            label="3 · AI extraction"
            tone="ai"
            note={ai?.provider ? `${ai.provider}${ai.model ? ` · ${ai.model}` : ""}` : undefined}
          >
            {ai ? `${ai.items.length} item(s)` : "—"}
          </ProvenanceRow>
          <ProvenanceRow
            label="4 · Normalized"
            tone="normalized"
            note={
              data.normalized_data?.missing_fields.length
                ? `${data.normalized_data.missing_fields.length} field(s) missing`
                : "Complete"
            }
          >
            {data.normalized_data ? `${data.normalized_data.items.length} item(s)` : "—"}
          </ProvenanceRow>
          <ProvenanceRow
            label="5 · Your corrections"
            tone="corrected"
            note={data.user_corrections.length ? "Applied on top of normalized data" : undefined}
          >
            {data.user_corrections.length > 0
              ? `${data.user_corrections.length} correction(s)`
              : "None yet"}
          </ProvenanceRow>
        </CardContent>
      </Card>

      {/* Confidence */}
      {data.confidence?.overall != null && (
        <div className="grid gap-4 sm:grid-cols-4">
          {(
            [
              ["Overall", data.confidence.overall],
              ["OCR", data.confidence.ocr],
              ["Extraction", data.confidence.extraction],
              ["Normalization", data.confidence.normalization],
            ] as const
          ).map(([label, score]) => (
            <Card key={label}>
              <CardContent className="space-y-2 p-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-muted-foreground">{label}</span>
                  <span className="tabular text-lg font-semibold">
                    {score != null ? percent(score) : "n/a"}
                  </span>
                </div>
                <ScoreBar
                  value={score ?? 0}
                  tone={score == null ? "primary" : score >= 0.75 ? "success" : score >= 0.5 ? "warning" : "destructive"}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Validation issues */}
      {validation && validation.issues.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-warning" />
              Validation findings
              <Badge variant="destructive">{validation.error_count} errors</Badge>
              <Badge variant="warning">{validation.warning_count} warnings</Badge>
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Flagged, not corrected. The extracted values below are exactly what was found.
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            {validation.issues.map((issue, index) => (
              <div
                key={`${issue.field}-${index}`}
                className="flex flex-wrap items-start gap-2 rounded-lg border px-3 py-2 text-sm"
              >
                <Badge variant={issue.severity === "error" ? "destructive" : "warning"}>
                  {issue.severity}
                </Badge>
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{issue.field}</code>
                <span className="min-w-0 flex-1">{issue.message}</span>
                {issue.observed != null && (
                  <span className="text-xs text-muted-foreground">
                    found <strong className="tabular">{String(issue.observed)}</strong>
                    {issue.expected != null && (
                      <>
                        , expected <strong className="tabular">{String(issue.expected)}</strong>
                      </>
                    )}
                  </span>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Data tabs */}
      <Tabs defaultValue="normalized">
        <TabsList className="flex-wrap">
          <TabsTrigger value="normalized">Reviewed data</TabsTrigger>
          <TabsTrigger value="ai">AI extraction</TabsTrigger>
          <TabsTrigger value="raw">Raw text</TabsTrigger>
          <TabsTrigger value="tables">Tables</TabsTrigger>
          <TabsTrigger value="matching">Item matching</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        {/* --- Reviewed / normalized --- */}
        <TabsContent value="normalized">
          {!effective ? (
            <Alert tone="info">Normalization has not produced data for this document yet.</Alert>
          ) : (
            <div className="space-y-4">
              {saveError && <Alert tone="error">{saveError}</Alert>}

              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <div>
                    <CardTitle className="text-base">Line items</CardTitle>
                    <p className="text-sm text-muted-foreground">
                      Editing writes to a separate corrections layer — the AI and raw extractions stay intact.
                    </p>
                  </div>
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
                          <X className="h-3.5 w-3.5" />
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          onClick={save}
                          disabled={Object.keys(edits).length === 0 || applyCorrections.isPending}
                        >
                          {applyCorrections.isPending ? <Spinner /> : <Save className="h-3.5 w-3.5" />}
                          Save {Object.keys(edits).length > 0 && `(${Object.keys(edits).length})`}
                        </Button>
                      </>
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                        <Pencil className="h-3.5 w-3.5" />
                        Correct values
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <ItemsTable
                    data={effective}
                    currency={currency}
                    editable={editing}
                    edits={edits}
                    onEdit={onEdit}
                  />
                </CardContent>
              </Card>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Pricing</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {(
                      [
                        ["Subtotal", effective.pricing.subtotal],
                        ["Tax", effective.pricing.tax_amount],
                        ["Transportation", effective.pricing.transportation_cost],
                        ["Stated total", effective.pricing.total_amount],
                        ["Landed total", effective.pricing.landed_total],
                      ] as const
                    ).map(([label, amount]) => (
                      <div key={label} className="flex justify-between gap-3">
                        <span className="text-muted-foreground">{label}</span>
                        <span className="tabular font-medium">
                          {amount != null ? (
                            formatCurrency(amount, currency)
                          ) : (
                            <ValueOrMissing value={null} />
                          )}
                        </span>
                      </div>
                    ))}
                    {effective.pricing.tax_percentage != null && (
                      <div className="flex justify-between gap-3">
                        <span className="text-muted-foreground">Tax rate</span>
                        <span className="tabular font-medium">{effective.pricing.tax_percentage}%</span>
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Delivery</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Lead time</span>
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
                        <Label className="text-xs">Correct lead time (days)</Label>
                        <Input
                          type="number"
                          className="h-8"
                          defaultValue={effective.delivery.delivery_days ?? ""}
                          onChange={(e) =>
                            onEdit(
                              "delivery.delivery_days",
                              e.target.value === "" ? null : Number(e.target.value),
                            )
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
                    <CardTitle className="text-base">Payment & supplier</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Credit period</span>
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
                    <div className="border-t pt-2">
                      <span className="text-muted-foreground">GST</span>
                      <p className="mt-0.5 font-mono text-xs">
                        <ValueOrMissing value={effective.supplier.gst_number} />
                      </p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Reference</span>
                      <p className="mt-0.5">
                        <ValueOrMissing value={effective.quotation_reference} />
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </div>

              {effective.missing_fields.length > 0 && (
                <Alert tone="warning" title="Fields the source did not provide">
                  <p>{effective.missing_fields.join(", ")}</p>
                  <p className="mt-1">
                    These were left empty rather than filled with plausible values. Correct them above
                    if you can confirm them with the supplier.
                  </p>
                </Alert>
              )}

              {/* Link to a request */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Procurement request</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Linking enables item matching and inclusion in supplier comparison.
                  </p>
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
            </div>
          )}
        </TabsContent>

        {/* --- AI extraction --- */}
        <TabsContent value="ai">
          {!ai ? (
            <Alert tone="info">No structured extraction has been stored yet.</Alert>
          ) : (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Sparkles className="h-4 w-4 text-primary" />
                    Structured extraction
                    <Badge variant={isHeuristic ? "warning" : "default"}>
                      {ai.provider ?? "unknown"}
                    </Badge>
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Exactly what the extractor returned, before normalization. Read-only by design.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Description</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead>Unit</TableHead>
                        <TableHead className="text-right">Unit price</TableHead>
                        <TableHead className="text-right">GST %</TableHead>
                        <TableHead className="text-right">Total</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {ai.items.map((item, index) => (
                        <TableRow key={index}>
                          <TableCell className="font-medium">
                            <ValueOrMissing value={item.original_name} />
                          </TableCell>
                          <TableCell className="tabular text-right">
                            <ValueOrMissing value={item.quantity} missingLabel="null" />
                          </TableCell>
                          <TableCell>
                            <ValueOrMissing value={item.unit} missingLabel="null" />
                          </TableCell>
                          <TableCell className="tabular text-right">
                            <ValueOrMissing value={item.unit_price} missingLabel="null" />
                          </TableCell>
                          <TableCell className="tabular text-right">
                            <ValueOrMissing value={item.gst_percentage} missingLabel="null" />
                          </TableCell>
                          <TableCell className="tabular text-right">
                            <ValueOrMissing value={item.total_price} missingLabel="null" />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              {ai.notes.length > 0 && (
                <Alert tone="info" title="Extractor notes">
                  <ul className="list-inside list-disc space-y-1">
                    {ai.notes.map((note, index) => (
                      <li key={index}>{note}</li>
                    ))}
                  </ul>
                </Alert>
              )}
            </div>
          )}
        </TabsContent>

        {/* --- Raw text --- */}
        <TabsContent value="raw">
          {!raw ? (
            <Alert tone="info">No raw extraction stored.</Alert>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Raw extracted text</CardTitle>
                <p className="text-sm text-muted-foreground">
                  {raw.document_type.replace(/_/g, " ")} · {raw.pages.length} page(s) ·{" "}
                  language {raw.detected_language ?? "unknown"}
                  {raw.ocr_used && (
                    <>
                      {" "}
                      · OCR {raw.ocr_engine}
                      {raw.ocr_confidence != null && ` at ${percent(raw.ocr_confidence)} confidence`}
                    </>
                  )}
                </p>
              </CardHeader>
              <CardContent>
                {raw.extraction_errors.length > 0 && (
                  <Alert tone="warning" title="Extraction warnings" className="mb-3">
                    <ul className="list-inside list-disc">
                      {raw.extraction_errors.map((message, index) => (
                        <li key={index}>{message}</li>
                      ))}
                    </ul>
                  </Alert>
                )}
                <pre className="max-h-[480px] overflow-auto scrollbar-thin whitespace-pre-wrap rounded-lg bg-muted p-4 text-xs leading-relaxed">
                  {raw.raw_text || "(no text extracted)"}
                </pre>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* --- Tables --- */}
        <TabsContent value="tables">
          {!raw || raw.tables.length === 0 ? (
            <Alert tone="info">No tables were detected in this document.</Alert>
          ) : (
            <div className="space-y-4">
              {raw.tables.map((table, index) => (
                <Card key={index}>
                  <CardHeader>
                    <CardTitle className="text-base">{table.name ?? `Table ${index + 1}`}</CardTitle>
                    <p className="text-sm text-muted-foreground">
                      {table.row_count} rows × {table.column_count} columns · {table.source}
                    </p>
                  </CardHeader>
                  <CardContent className="p-0">
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
                              <TableCell key={cellIndex} className="text-sm">
                                {cell == null ? "" : String(cell)}
                              </TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* --- Matching --- */}
        <TabsContent value="matching">
          {!data.match_result ? (
            <Alert tone="info" title="Not matched">
              <p>
                Link this quotation to a procurement request to match its line items against the
                requested items.
              </p>
            </Alert>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Item matching</CardTitle>
                <p className="text-sm text-muted-foreground">
                  {data.match_result.matched_count} auto-matched · {data.match_result.review_count} need
                  review · {data.match_result.unmatched_count} unmatched · coverage{" "}
                  {percent(data.match_result.coverage)}
                  {data.match_result.ai_assisted && " · AI assisted on ambiguous pairs"}
                </p>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Requested</TableHead>
                      <TableHead>Matched to</TableHead>
                      <TableHead>Confidence</TableHead>
                      <TableHead>Method</TableHead>
                      <TableHead>Reason</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.match_result.matches.map((match) => (
                      <TableRow key={match.request_item_id}>
                        <TableCell className="font-medium">{match.request_item_name}</TableCell>
                        <TableCell>
                          {match.quotation_item_name ?? (
                            <span className="text-xs italic text-muted-foreground">No match</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <ConfidenceBadge level={match.confidence_level} score={match.score} />
                        </TableCell>
                        <TableCell className="text-sm capitalize text-muted-foreground">
                          {match.method}
                        </TableCell>
                        <TableCell className="max-w-sm text-xs text-muted-foreground">
                          {match.reasons.join(" ")}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* --- History --- */}
        <TabsContent value="history">
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <History className="h-4 w-4" />
                  Processing history
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="space-y-3">
                  {data.processing_history.map((event, index) => (
                    <li key={index} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <div className="mt-1.5 h-2 w-2 rounded-full bg-primary" />
                        {index < data.processing_history.length - 1 && (
                          <div className="mt-1 w-px flex-1 bg-border" />
                        )}
                      </div>
                      <div className="flex-1 pb-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={event.status} />
                          <span className="text-xs text-muted-foreground">
                            {formatDateTime(event.at)}
                          </span>
                        </div>
                        {event.message && <p className="mt-1 text-sm">{event.message}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>

            {data.user_corrections.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Correction log</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Every edit keeps its previous value, so the machine output remains auditable.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Field</TableHead>
                        <TableHead>Was</TableHead>
                        <TableHead>Now</TableHead>
                        <TableHead>When</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.user_corrections.map((correction, index) => (
                        <TableRow key={index}>
                          <TableCell>
                            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                              {correction.path}
                            </code>
                          </TableCell>
                          <TableCell className="tabular text-sm text-muted-foreground line-through">
                            {correction.previous_value == null
                              ? "empty"
                              : String(correction.previous_value)}
                          </TableCell>
                          <TableCell className="tabular text-sm font-medium">
                            {String(correction.new_value)}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {formatDateTime(correction.corrected_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>
      </Tabs>
      <AgentRuns filters={{ quotation_id: data.id, graph: "quotation_processing" }} title="Processing agents" />
    </div>
  )
}
