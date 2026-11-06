import * as React from "react"
import { useSearchParams } from "react-router-dom"
import { Mail, MessageCircle, RefreshCw, Unplug } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, ErrorState, LoadingState, Spinner } from "@/components/ui/feedback"
import { Input, Textarea } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useChannels, useGmailActions, useOrganizationProfile, useUpdateOrganization } from "@/hooks/automation"
import { relativeTime } from "@/lib/utils"

export function SettingsPage() {
  const { data, isLoading, error, refetch } = useOrganizationProfile()
  const update = useUpdateOrganization()
  const [message, setMessage] = React.useState<{ tone: "success" | "error"; text: string } | null>(null)

  if (isLoading) return <LoadingState />
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? "").trim() || null
    try {
      await update.mutateAsync({
        name: value("name") ?? data!.name, address: value("address"), gst_number: value("gst_number"),
        contact_email: value("contact_email"), contact_phone: value("contact_phone"),
      })
      setMessage({ tone: "success", text: "Saved." })
    } catch (e) {
      setMessage({ tone: "error", text: "Could not save. Please try again." })
    }
  }

  return (
    <div className="max-w-2xl">
      <PageHeader title="Settings" />
      <Card>
        <CardContent className="pt-6">
          <form onSubmit={save} className="space-y-4">
            {message && <Alert tone={message.tone}>{message.text}</Alert>}
            <div className="space-y-1.5">
              <Label htmlFor="name">Business name</Label>
              <Input id="name" name="name" defaultValue={data.name} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="address">Address</Label>
              <Textarea id="address" name="address" rows={2} defaultValue={data.address ?? ""} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="gst_number">GST number</Label>
                <Input id="gst_number" name="gst_number" defaultValue={data.gst_number ?? ""} placeholder="15 letters and numbers" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="contact_phone">Phone</Label>
                <Input id="contact_phone" name="contact_phone" defaultValue={data.contact_phone ?? ""} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="contact_email">Email</Label>
              <Input id="contact_email" name="contact_email" type="email" defaultValue={data.contact_email ?? ""} />
            </div>
            <Button type="submit" disabled={update.isPending}>{update.isPending && <Spinner />}Save</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export function IntegrationsPage() {
  const { data, isLoading, error, refetch } = useChannels()
  const { connect, sync, disconnect } = useGmailActions()
  const [params] = useSearchParams()
  const outcome = params.get("gmail")
  const actionError = [connect.error, sync.error, disconnect.error].find(Boolean) as Error | undefined

  if (isLoading) return <LoadingState />
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />
  const gmail = data.gmail
  const result = gmail.last_result

  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader title="Connections" />
      {outcome === "connected" && <Alert tone="success">Gmail connected.</Alert>}
      {outcome && outcome !== "connected" && <Alert tone="error">Gmail could not be connected. Please try again.</Alert>}
      {actionError && <Alert tone="error">Something went wrong, please try again.</Alert>}

      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0">
          <Mail className="mt-0.5 h-5 w-5 text-primary" />
          <div className="flex-1 space-y-1">
            <CardTitle className="text-base">Gmail</CardTitle>
          </div>
          <Badge variant={gmail.connected ? "success" : gmail.status === "reauthorization_required" ? "destructive" : "muted"}>
            {gmail.connected ? "Connected" : gmail.status === "reauthorization_required" ? "Reconnect needed" : "Not connected"}
          </Badge>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!gmail.configured ? (
            <Alert tone="warning">Connecting Gmail is not set up yet. Please contact support.</Alert>
          ) : (
            <>
              {gmail.account_email && <p>Connected email: <span className="font-medium">{gmail.account_email}</span></p>}
              {gmail.last_error && <Alert tone="error">Gmail had a problem. Please try again.</Alert>}
              {gmail.last_synced_at && (
                <p className="text-muted-foreground">
                  Last checked {relativeTime(gmail.last_synced_at)}.
                  {result && ` ${result.documents_imported} new quotations found.`}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                {gmail.connected ? (
                  <>
                    <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
                      {sync.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}Check now
                    </Button>
                    <Button variant="outline" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
                      <Unplug className="h-4 w-4" />Disconnect
                    </Button>
                  </>
                ) : (
                  <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
                    {connect.isPending && <Spinner />}{gmail.status === "reauthorization_required" ? "Reconnect Gmail" : "Connect Gmail"}
                  </Button>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start gap-3 space-y-0">
          <MessageCircle className="mt-0.5 h-5 w-5 text-muted-foreground" />
          <div className="flex-1 space-y-1">
            <CardTitle className="text-base">WhatsApp</CardTitle>
          </div>
          <Badge variant="muted">Coming soon</Badge>
        </CardHeader>
      </Card>
    </div>
  )
}
