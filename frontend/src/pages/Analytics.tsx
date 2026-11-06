import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { LineChart } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/feedback"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useForecast, useSpend } from "@/hooks/automation"
import { formatCompactCurrency, formatCurrency, formatNumber, percent } from "@/lib/utils"

/** "2026-12" -> "Dec 2026" */
const monthName = (value: string) => {
  const [year, month] = value.split("-").map(Number)
  return year && month ? new Date(year, month - 1, 1).toLocaleString("en-IN", { month: "short", year: "numeric" }) : value
}

const axis = { fontSize: 11, fill: "hsl(var(--muted-foreground))" }
const tooltip = { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }

export function AnalyticsPage() {
  const spend = useSpend()
  const forecast = useForecast()

  if (spend.isLoading) return <LoadingState />
  if (spend.error || !spend.data) return <ErrorState error={spend.error} onRetry={spend.refetch} />
  const s = spend.data
  const forecasts = forecast.data?.items.filter((i) => i.status === "ok") ?? []

  return (
    <div className="space-y-4">
      <PageHeader title="Reports" />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Total spent</p><p className="text-2xl font-semibold">{formatCompactCurrency(s.total_spend, s.currency)}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Purchase orders</p><p className="text-2xl font-semibold">{formatNumber(s.orders)}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Suppliers used</p><p className="text-2xl font-semibold">{s.by_supplier.length}</p></CardContent></Card>
      </div>

      {s.orders === 0 ? (
        <EmptyState icon={LineChart} title="Nothing spent yet" description="Your reports appear after you send a purchase order." />
      ) : (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Money spent each month</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={s.by_month} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tickFormatter={monthName} tick={axis} axisLine={false} tickLine={false} minTickGap={16} />
                  <YAxis tick={axis} axisLine={false} tickLine={false} width={64} tickFormatter={(v: number) => formatCompactCurrency(v, s.currency)} />
                  <Tooltip contentStyle={tooltip} formatter={(v) => formatCurrency(Number(v), s.currency)} />
                  <Bar dataKey="spend" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="text-base">Spend by supplier</CardTitle></CardHeader>
              <CardContent>
                <Table>
                  <TableHeader><TableRow><TableHead>Supplier</TableHead><TableHead className="text-right">Spent</TableHead><TableHead className="text-right">Orders</TableHead><TableHead className="text-right">On time</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {s.by_supplier.slice(0, 12).map((row) => (
                      <TableRow key={row.supplier}>
                        <TableCell className="max-w-48 truncate">{row.supplier}</TableCell>
                        <TableCell className="text-right">{formatCompactCurrency(row.spend, s.currency)}</TableCell>
                        <TableCell className="text-right">{formatNumber(row.orders)}</TableCell>
                        <TableCell className="text-right">{row.on_time_rate == null ? "—" : percent(row.on_time_rate)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="text-base">What you buy most</CardTitle></CardHeader>
              <CardContent>
                <Table>
                  <TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Quantity</TableHead><TableHead className="text-right">Spent</TableHead></TableRow></TableHeader>
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
                    You saved {formatCurrency(s.savings.reduce((a, b) => a + b.saving, 0), s.currency)} by picking lower prices.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">What you may need next</CardTitle>
        </CardHeader>
        <CardContent>
          {forecast.isLoading ? <LoadingState /> : forecasts.length === 0 ? (
            <p className="text-sm text-muted-foreground">Not enough past orders yet to guess what you may need.</p>
          ) : (
            <Table>
              <TableHeader><TableRow><TableHead>Item</TableHead><TableHead>Next 3 months</TableHead></TableRow></TableHeader>
              <TableBody>
                {forecasts.slice(0, 15).map((f) => (
                  <TableRow key={f.item}>
                    <TableCell className="max-w-48 truncate">{f.item}</TableCell>
                    <TableCell className="text-sm">{f.forecast?.map((p) => `${monthName(p.month)}: ${formatNumber(p.quantity)}`).join(" · ")}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
