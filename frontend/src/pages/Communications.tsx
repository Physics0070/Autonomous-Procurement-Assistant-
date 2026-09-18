import * as React from "react"
import { Check, Copy, Download, Mail, Send, X } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/feedback"
import { Input, Select, Textarea } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useNavigate } from "react-router-dom"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { useCommunicationActions, useCommunications, type Communication } from "@/hooks/automation"
import { useSuppliers } from "@/hooks/queries"
import { downloadFile } from "@/lib/api"
import { cn, formatDateTime, relativeTime } from "@/lib/utils"

const KIND_LABEL = { rfq: "RFQ", negotiation: "Negotiation", purchase_order: "Purchase order" } as const
const STATUS_TONE = { draft: "muted", approved: "default", sent: "success", cancelled: "destructive" } as const

export function CommunicationStatusBadge({ status }: { status: Communication["status"] }) {
  return <Badge variant={STATUS_TONE[status]}>{status}</Badge>
}

function Detail({ item }: { item: Communication }) {
  const { edit, act } = useCommunicationActions()
  const [subject, setSubject] = React.useState(item.subject)
  const [body, setBody] = React.useState(item.body)
  const [to, setTo] = React.useState(item.to_email ?? "")
  const [error, setError] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState(false)
  React.useEffect(() => {
    setSubject(item.subject)
    setBody(item.body)
    setTo(item.to_email ?? "")
    setError(null)
  }, [item.id, item.subject, item.body, item.to_email])

  const editable = item.status === "draft"
  const dirty = subject !== item.subject || body !== item.body || to !== (item.to_email ?? "")
  const run = (promise: Promise<unknown>) => promise.then(() => setError(null)).catch((e) => setError(e.message))

  return (
    <Card>
      <CardHeader className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{KIND_LABEL[item.kind]}</Badge>
          <CommunicationStatusBadge status={item.status} />
          <Badge variant={item.generated_by === "ai" ? "default" : "outline"}>
            {item.generated_by === "ai" ? `AI · ${item.model ?? item.provider}` : "Template"}
          </Badge>
        </div>
        <CardTitle className="text-base">{item.subject}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {item.fallback_reason && item.generated_by === "template" && (
          <Alert tone="info" title="Template used">{item.fallback_reason}</Alert>
        )}
        {item.guardrail_findings.length > 0 && (
          <Alert tone="warning" title="The AI draft was rejected by the competitor guardrail">
            <ul className="list-inside list-disc">{item.guardrail_findings.map((f) => <li key={f}>{f}</li>)}</ul>
          </Alert>
        )}
        {error && <Alert tone="error">{error}</Alert>}

        <div className="space-y-1.5">
          <Label htmlFor="to">To</Label>
          <Input id="to" type="email" value={to} disabled={!editable} onChange={(e) => setTo(e.target.value)} placeholder="Supplier email not known" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="subject">Subject</Label>
          <Input id="subject" value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="body">Message</Label>
          <Textarea id="body" rows={14} value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} className="font-mono text-xs" />
        </div>

        <div className="flex flex-wrap gap-2">
          {editable && (
            <Button variant="outline" disabled={!dirty || edit.isPending}
                    onClick={() => run(edit.mutateAsync({ id: item.id, subject, body, ...(to ? { to_email: to } : {}) }))}>
              {edit.isPending && <Spinner />}Save draft
            </Button>
          )}
          {editable && (
            <Button disabled={dirty || act.isPending} onClick={() => run(act.mutateAsync({ id: item.id, action: "approve" }))}>
              <Check className="h-4 w-4" />Approve
            </Button>
          )}
          {item.status === "approved" && (
            <Button onClick={() => run(act.mutateAsync({ id: item.id, action: "mark-sent" }))} disabled={act.isPending}>
              <Send className="h-4 w-4" />Mark as sent
            </Button>
          )}
          <Button variant="outline" onClick={() => run(downloadFile(`/communications/${item.id}/eml`, `${item.kind}-${item.id}.eml`))}>
            <Download className="h-4 w-4" />Export .eml
          </Button>
          <Button variant="outline" onClick={() => navigator.clipboard.writeText(`Subject: ${item.subject}\n\n${item.body}`).then(() => setCopied(true))}>
            <Copy className="h-4 w-4" />{copied ? "Copied" : "Copy"}
          </Button>
          {(item.status === "draft" || item.status === "approved") && (
            <Button variant="ghost" className="text-destructive" onClick={() => run(act.mutateAsync({ id: item.id, action: "cancel" }))}>
              <X className="h-4 w-4" />Cancel
            </Button>
          )}
        </div>
        {editable && dirty && <p className="text-xs text-muted-foreground">Save your changes before approving.</p>}
        <p className="text-xs text-muted-foreground">
          The app never sends email. Approve the draft, send it from your own mail client (open the .eml or copy it), then mark it as sent.
        </p>

        <div className="border-t pt-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">History</p>
          <ul className="space-y-1 text-xs">
            {item.history.map((h, i) => (
              <li key={i} className="flex justify-between gap-2">
                <span>{h.action.replace(/_/g, " ")}</span>
                <span className="text-muted-foreground">{formatDateTime(h.at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}

export function CommunicationsPage() {
  const [kind, setKind] = React.useState("")
  const [status, setStatus] = React.useState("")
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  const { data, isLoading, error, refetch } = useCommunications({ kind, status })
  const selected = data?.find((c) => c.id === selectedId) ?? data?.[0]

  return (
    <div>
      <PageHeader title="Communications" description="RFQ, negotiation and purchase-order emails. Drafts are reviewed and approved here; nothing is sent automatically." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select value={kind} onChange={(e) => setKind(e.target.value)} className="w-44" aria-label="Kind">
          <option value="">All kinds</option>
          <option value="rfq">RFQ</option>
          <option value="negotiation">Negotiation</option>
          <option value="purchase_order">Purchase order</option>
        </Select>
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-40" aria-label="Status">
          <option value="">All statuses</option>
          {Object.keys(STATUS_TONE).map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data?.length ? (
        <EmptyState icon={Mail} title="No communications yet"
                    description="Draft RFQs from a procurement request, or negotiation emails and purchase orders from a comparison." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <Card className="h-fit">
            <ul className="divide-y">
              {data.map((c) => (
                <li key={c.id}>
                  <button onClick={() => setSelectedId(c.id)}
                          className={cn("w-full px-4 py-3 text-left hover:bg-accent", selected?.id === c.id && "bg-primary/5")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{c.subject}</span>
                      <CommunicationStatusBadge status={c.status} />
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {KIND_LABEL[c.kind]} · {c.to_email ?? "no recipient"} · {relativeTime(c.created_at)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {selected && <Detail item={selected} />}
        </div>
      )}
    </div>
  )
}

/** Pick suppliers and create one RFQ draft each (used on the request page). */
export function DraftRfqDialog({ requestId }: { requestId: string }) {
  const [open, setOpen] = React.useState(false)
  const [chosen, setChosen] = React.useState<string[]>([])
  const suppliers = useSuppliers()
  const { draftRfqs } = useCommunicationActions()
  const navigate = useNavigate()
  const toggle = (id: string) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]))

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline"><Mail className="h-4 w-4" />Draft RFQs</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Draft requests for quotation</DialogTitle>
          <DialogDescription>One draft per supplier, listing every item. You review and approve them before anything is sent.</DialogDescription>
        </DialogHeader>
        {draftRfqs.error && <Alert tone="error">{draftRfqs.error.message}</Alert>}
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {suppliers.data?.items.map((s) => (
            <label key={s.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent">
              <input type="checkbox" checked={chosen.includes(s.id)} onChange={() => toggle(s.id)} />
              <span className="flex-1">{s.name}</span>
              <span className="text-xs text-muted-foreground">{s.email ?? "no email"}</span>
            </label>
          ))}
          {suppliers.data?.items.length === 0 && <p className="text-sm text-muted-foreground">Add suppliers first.</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button disabled={!chosen.length || draftRfqs.isPending}
                  onClick={() => draftRfqs.mutateAsync({ requestId, supplierIds: chosen }).then(() => navigate("/communications"))}>
            {draftRfqs.isPending && <Spinner />}Create {chosen.length || ""} draft{chosen.length === 1 ? "" : "s"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
