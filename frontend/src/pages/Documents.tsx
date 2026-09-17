import * as React from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CloudUpload, FileStack, Upload, X } from "lucide-react"
import { PageHeader } from "@/components/layout/AppShell"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Select } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge, StatusBadge } from "@/components/ui/badge"
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
import { Alert, EmptyState, ErrorState, LoadingState, Spinner, ValueOrMissing } from "@/components/ui/feedback"
import { useCapabilities, useQuotations, useRequests, useUploadDocument } from "@/hooks/queries"
import { cn, formatCurrency, relativeTime } from "@/lib/utils"
import type { ProcessingStatus, SourceType } from "@/types"

const STATUS_OPTIONS: ProcessingStatus[] = [
  "QUEUED",
  "EXTRACTING",
  "AI_EXTRACTING",
  "NORMALIZING",
  "COMPLETED",
  "REQUIRES_REVIEW",
  "FAILED",
]

const SOURCE_LABELS: Record<SourceType, string> = {
  manual_upload: "Upload",
  email: "Email",
  whatsapp: "WhatsApp",
  api: "API",
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
  const { data: capabilities } = useCapabilities()
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
          <DialogTitle>Upload supplier quotations</DialogTitle>
          <DialogDescription>
            PDFs, scans, photos and spreadsheets. Processing runs in the background — you can close
            this straight away.
          </DialogDescription>
        </DialogHeader>

        {capabilities && !capabilities.ocr.available && (
          <Alert tone="warning" title="No OCR engine installed">
            <p>Scanned PDFs and images cannot be read on this deployment. Digital PDFs and spreadsheets still work.</p>
          </Alert>
        )}

        {errors.length > 0 && (
          <Alert tone="error" title="Some files were rejected">
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
          <p className="text-sm font-medium">Drop files here, or click to browse</p>
          <p className="text-xs text-muted-foreground">
            PDF, Excel, CSV, PNG, JPG · up to 25 MB each
          </p>
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
                <span className="shrink-0 text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(0)} KB
                </span>
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
          <Label htmlFor="request">Link to procurement request</Label>
          <Select id="request" value={requestId} onChange={(e) => setRequestId(e.target.value)}>
            <option value="">Not linked</option>
            {requests?.items.map((request) => (
              <option key={request.id} value={request.id}>
                {request.title}
              </option>
            ))}
          </Select>
          <p className="text-xs text-muted-foreground">
            Linking enables item matching and supplier comparison. You can link it later too.
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleUpload} disabled={files.length === 0 || upload.isPending}>
            {upload.isPending && <Spinner />}
            Upload {files.length > 0 && `(${files.length})`}
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
        title="Documents"
        description="Every quotation received, from any channel, with its live processing state."
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
        <option value="">All statuses</option>
        {STATUS_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option.replace(/_/g, " ").toLowerCase()}
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
          title={status ? "No documents with that status" : "No documents yet"}
          description={
            status
              ? "Try clearing the filter."
              : "Upload a supplier quotation — PDF, scan, photo or spreadsheet — to start the pipeline."
          }
          action={!status ? <UploadDialog /> : undefined}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Document</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Uploaded</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((quotation) => (
                  <TableRow key={quotation.id}>
                    <TableCell>
                      <Link to={`/documents/${quotation.id}`} className="font-medium hover:underline">
                        {quotation.source.original_filename ?? "Untitled"}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {quotation.document_type.replace(/_/g, " ")}
                        {quotation.issue_count > 0 && ` · ${quotation.issue_count} issue(s)`}
                      </p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {SOURCE_LABELS[quotation.source.type] ?? quotation.source.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      <ValueOrMissing value={quotation.supplier_name} missingLabel="Not identified" />
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
                      {relativeTime(quotation.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Alert tone="info" title="One pipeline, every channel">
        <p>
          Manual uploads run through the same ingestion service that Gmail and WhatsApp will use once
          their credentials are provisioned — document processing is never duplicated per source.
        </p>
      </Alert>
    </div>
  )
}
