import * as React from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CloudUpload, FileStack, Upload, X } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StatusBadge } from "@/components/ui/badge"
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
import { Alert, EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/feedback"
import { useQuotations, useRequests, useUploadDocument } from "@/hooks/queries"
import { cn, formatCurrency, formatDate } from "@/lib/utils"
import type { ProcessingStatus } from "@/types"

const STATUS_OPTIONS: ProcessingStatus[] = [
  "QUEUED",
  "EXTRACTING",
  "AI_EXTRACTING",
  "NORMALIZING",
  "COMPLETED",
  "REQUIRES_REVIEW",
  "FAILED",
]

const STATUS_LABELS: Record<string, string> = {
  QUEUED: "Waiting",
  EXTRACTING: "Reading",
  AI_EXTRACTING: "Reading",
  NORMALIZING: "Reading",
  COMPLETED: "Ready",
  REQUIRES_REVIEW: "Needs checking",
  FAILED: "Could not read",
}

const ACCEPT = ".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg"

export function UploadDialog({ defaultRequestId }: { defaultRequestId?: string }) {
  const [open, setOpen] = React.useState(false)
  const [files, setFiles] = React.useState<File[]>([])
  const [requestId, setRequestId] = React.useState(defaultRequestId ?? "")
  const [dragging, setDragging] = React.useState(false)
  const [errors, setErrors] = React.useState<string[]>([])
  const inputRef = React.useRef<HTMLInputElement>(null)

  const { data: requests } = useRequests()
  const upload = useUploadDocument()

  function addFiles(list: FileList | null) {
    if (!list) return
    setFiles((current) => [...current, ...Array.from(list)])
  }

  async function handleUpload() {
    setErrors([])
    const failures: string[] = []
    for (const file of files) {
      try {
        await upload.mutateAsync({ file, procurementRequestId: requestId || undefined })
      } catch (err) {
        failures.push(`${file.name}: ${err instanceof Error ? err.message : "upload failed"}`)
      }
    }
    if (failures.length > 0) {
      setErrors(failures)
      setFiles([])
      return
    }
    setFiles([])
    setOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Upload className="h-4 w-4" />
          Upload quotation
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload quotation</DialogTitle>
          <DialogDescription>PDF, photo or spreadsheet.</DialogDescription>
        </DialogHeader>

        {errors.length > 0 && (
          <Alert tone="error" title="Some files could not be uploaded">
            <ul className="list-inside list-disc space-y-0.5">
              {errors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Alert>
        )}

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            addFiles(e.dataTransfer.files)
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-9 text-center transition-colors",
            dragging ? "border-primary bg-primary/5" : "hover:border-primary/50 hover:bg-accent/50",
          )}
        >
          <div className="rounded-full bg-muted p-3">
            <CloudUpload className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="font-medium">Drop files here, or click to choose</p>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files)
              e.target.value = ""
            }}
          />
        </div>

        {files.length > 0 && (
          <ul className="max-h-40 space-y-1.5 overflow-y-auto scrollbar-thin">
            {files.map((file, index) => (
              <li
                key={`${file.name}-${index}`}
                className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <FileStack className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{file.name}</span>
                                <button
                  className="rounded p-0.5 text-muted-foreground hover:bg-accent"
                  onClick={() => setFiles((c) => c.filter((_, i) => i !== index))}
                  aria-label={`Remove ${file.name}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="request">Purchase request</Label>
          <Select id="request" value={requestId} onChange={(e) => setRequestId(e.target.value)}>
            <option value="">Not linked</option>
            {requests?.items.map((request) => (
              <option key={request.id} value={request.id}>
                {request.title}
              </option>
            ))}
          </Select>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleUpload} disabled={files.length === 0 || upload.isPending}>
            {upload.isPending && <Spinner />}
            Upload{files.length > 0 && ` (${files.length})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function DocumentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const status = searchParams.get("status") ?? ""
  const { data, isLoading, error, refetch } = useQuotations({ status: status || undefined })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quotations"
        actions={<UploadDialog />}
      />

      <Select
        value={status}
        onChange={(e) => {
          const next = new URLSearchParams(searchParams)
          if (e.target.value) next.set("status", e.target.value)
          else next.delete("status")
          setSearchParams(next)
        }}
        className="max-w-[220px]"
      >
        <option value="">All quotations</option>
        {STATUS_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {STATUS_LABELS[option]}
          </option>
        ))}
      </Select>

      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={FileStack}
          title={status ? "No quotations with that status" : "No quotations yet"}
          description={status ? "Try another status." : "Upload your first quotation."}
          action={!status ? <UploadDialog /> : undefined}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Supplier</TableHead>
                  <TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((quotation) => (
                  <TableRow key={quotation.id}>
                    <TableCell>
                      <Link to={`/documents/${quotation.id}`} className="font-medium hover:underline">
                        {quotation.supplier_name ?? quotation.source.original_filename ?? "Untitled"}
                      </Link>
                      {quotation.issue_count > 0 && (
                        <p className="text-sm text-muted-foreground">
                          {quotation.issue_count} {quotation.issue_count === 1 ? "thing" : "things"} to check
                        </p>
                      )}
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
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(quotation.created_at)}
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
