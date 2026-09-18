import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { BrainCircuit, LineChart } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/feedback"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useForecast, useModels, useRetrain, useSpend, type ModelsInfo } from "@/hooks/automation"
import { formatCompactCurrency, formatCurrency, formatNumber, percent } from "@/lib/utils"

const axis = { fontSize: 11, fill: "hsl(var(--muted-foreground))" }
const tooltip = { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }

function ModelCard({ models }: { models: ModelsInfo }) {
  const retrain = useRetrain()
  const r = models.reliability
  const rows = r.test && r.baselines
    ? [["This model", r.test], ["Always “on time”", r.baselines.always_on_time], ["Supplier's past on-time rate", r.baselines.prior_on_time_rate]] as const
    : []
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3 space-y-0">
        <BrainCircuit className="mt-0.5 h-5 w-5 text-primary" />
        <div className="flex-1 space-y-1">
          <CardTitle className="text-base">Late-delivery risk model</CardTitle>
          <CardDescription>
            {r.available ? `${r.model_name?.replace(/_/g, " ")} · ${r.trained_on}` : r.reason}
          </CardDescription>
        </div>
        {r.available && <Badge variant={r.own_data ? "success" : "secondary"}>{r.own_data ? "Trained on your data" : "USAID SCMS model"}</Badge>}
      </CardHeader>
      {r.available && (
        <CardContent className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            Tested on {formatNumber(r.test?.rows)} later shipments it never saw ({percent(r.test?.late_rate, 1)} were late).
            PR-AUC measures how well it ranks late orders; a random guess scores the late rate.
          </p>
          <Table>
            <TableHeader>
              <TableRow><TableHead>Scorer</TableHead><TableHead className="text-right">ROC-AUC</TableHead><TableHead className="text-right">PR-AUC</TableHead><TableHead className="text-right">Macro-F1</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(([label, m]) => (
                <TableRow key={label}>
                  <TableCell>{label}</TableCell>
                  <TableCell className="text-right">{m.roc_auc.toFixed(3)}</TableCell>
                  <TableCell className="text-right">{m.pr_auc.toFixed(3)}</TableCell>
                  <TableCell className="text-right">{m.macro_f1.toFixed(3)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">
            Price anomalies: {models.price_anomaly.method.replace(/_/g, " ")} once a product has {models.price_anomaly.min_samples}+ past prices,
            otherwise {models.price_anomaly.fallback}.
          </p>
          {retrain.error && <Alert tone="warning">{retrain.error.message}</Alert>}
          {retrain.isSuccess && <Alert tone="success">Retrained on your delivered purchase orders.</Alert>}
          <Button variant="outline" size="sm" onClick={() => retrain.mutate()} disabled={retrain.isPending}>
            {retrain.isPending && <Spinner />}Retrain on our deliveries (needs {r.min_retrain_orders}+)
          </Button>
        </CardContent>
      )}
    </Card>
  )
}

export function AnalyticsPage() {
  const spend = useSpend()
  const forecast = useForecast()
  const models = useModels()

  if (spend.isLoading) return <LoadingState />
  if (spend.error || !spend.data) return <ErrorState error={spend.error} onRetry={spend.refetch} />
  const s = spend.data
  const forecasts = forecast.data?.items.filter((i) => i.status === "ok") ?? []

  return (
    <div className="space-y-4">
      <PageHeader title="Analytics" description="Spend from issued and delivered purchase orders, supplier delivery performance, demand forecasts and the models behind them." />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Committed spend</p><p className="text-2xl font-semibold">{formatCompactCurrency(s.total_spend, s.currency)}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Purchase orders</p><p className="text-2xl font-semibold">{formatNumber(s.orders)}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Suppliers used</p><p className="text-2xl font-semibold">{s.by_supplier.length}</p></CardContent></Card>
      </div>

      {s.orders === 0 ? (
        <EmptyState icon={LineChart} title="No committed spend yet" description="Spend appears once a purchase order is issued." />
      ) : (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Spend by month</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={s.by_month} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={axis} axisLine={false} tickLine={false} minTickGap={16} />
                  <YAxis tick={axis} axisLine={false} tickLine={false} width={64} tickFormatter={(v: number) => formatCompactCurrency(v, s.currency)} />
                  <Tooltip contentStyle={tooltip} formatter={(v) => formatCurrency(Number(v), s.currency)} />
                  <Bar dataKey="spend" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Suppliers</CardTitle></CardHeader>
              <CardContent>
                <Table>
                  <TableHeader><TableRow><TableHead>Supplier</TableHead><TableHead className="text-right">Spend</TableHead><TableHead className="text-right">Orders</TableHead><TableHead className="text-right">On time</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {s.by_supplier.slice(0, 12).map((row) => (
                      <TableRow key={row.supplier}>
                        <TableCell className="max-w-48 truncate">{row.supplier}</TableCell>
                        <TableCell className="text-right">{formatCompactCurrency(row.spend, s.currency)}</TableCell>
                        <TableCell className="text-right">{formatNumber(row.orders)}</TableCell>
                        <TableCell className="text-right">{row.on_time_rate == null ? "—" : `${percent(row.on_time_rate)} of ${row.delivered}`}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">Items</CardTitle></CardHeader>
              <CardContent>
                <Table>
                  <TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Quantity</TableHead><TableHead className="text-right">Spend</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {s.by_item.slice(0, 12).map((row) => (
                      <TableRow key={row.item}>
                        <TableCell className="max-w-56 truncate">{row.item}</TableCell>
                        <TableCell className="text-right">{formatNumber(row.quantity)}</TableCell>
                        <TableCell className="text-right">{formatCompactCurrency(row.spend, s.currency)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {s.savings.length > 0 && (
                  <p className="mt-3 text-sm text-muted-foreground">
                    Awarding below the highest quote saved {formatCurrency(s.savings.reduce((a, b) => a + b.saving, 0), s.currency)} across {s.savings.length} order(s).
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Demand forecast</CardTitle>
          <CardDescription>
            Next 3 months per item. Linear trend and same-month-last-year are each back-tested on recent months; the one with the lower error is used.
            Items need {forecast.data?.min_months ?? 12}+ months of order history.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {forecast.isLoading ? <LoadingState /> : forecasts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No item has enough monthly history yet.</p>
          ) : (
            <Table>
              <TableHeader><TableRow><TableHead>Item</TableHead><TableHead>Method</TableHead><TableHead className="text-right">Back-test error (sMAPE)</TableHead><TableHead>Forecast</TableHead></TableRow></TableHeader>
              <TableBody>
                {forecasts.slice(0, 15).map((f) => (
                  <TableRow key={f.item}>
                    <TableCell className="max-w-48 truncate">{f.item}</TableCell>
                    <TableCell>{f.method?.replace(/_/g, " ")}</TableCell>
                    <TableCell className="text-right">{f.method && f.backtest_smape ? `${f.backtest_smape[f.method].toFixed(0)}%` : "—"}</TableCell>
                    <TableCell className="text-xs">{f.forecast?.map((p) => `${p.month}: ${formatNumber(p.quantity)}`).join(" · ")}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {models.data && <ModelCard models={models.data} />}
    </div>
  )
}
