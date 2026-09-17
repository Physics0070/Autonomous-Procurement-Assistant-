import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { IN_PROGRESS_STATUSES } from "@/components/ui/badge"
import type {
  Capabilities,
  ComparisonResult,
  DashboardSummary,
  Paginated,
  ProcurementRequest,
  QuotationDetail,
  QuotationListItem,
  Supplier,
} from "@/types"

export const keys = {
  dashboard: ["dashboard"] as const,
  capabilities: ["capabilities"] as const,
  suppliers: (search?: string) => ["suppliers", search ?? ""] as const,
  supplier: (id: string) => ["supplier", id] as const,
  requests: (status?: string) => ["requests", status ?? ""] as const,
  request: (id: string) => ["request", id] as const,
  quotations: (filters?: Record<string, string | undefined>) => ["quotations", filters ?? {}] as const,
  quotation: (id: string) => ["quotation", id] as const,
  comparison: (requestId: string) => ["comparison", requestId] as const,
  weights: ["comparison-weights"] as const,
}

function queryString(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ""
}

// --- Dashboard -------------------------------------------------------------

export function useDashboard() {
  return useQuery({
    queryKey: keys.dashboard,
    queryFn: () => api.get<DashboardSummary>("/dashboard/summary"),
    refetchInterval: 15000,
  })
}

export function useCapabilities() {
  return useQuery({
    queryKey: keys.capabilities,
    queryFn: () => api.get<Capabilities>("/documents/capabilities"),
    staleTime: 60 * 1000,
  })
}

// --- Suppliers -------------------------------------------------------------

export function useSuppliers(search?: string) {
  return useQuery({
    queryKey: keys.suppliers(search),
    queryFn: () => api.get<Paginated<Supplier>>(`/suppliers${queryString({ search, page_size: 200 })}`),
  })
}

export function useSupplier(id: string | undefined) {
  return useQuery({
    queryKey: keys.supplier(id ?? ""),
    queryFn: () => api.get<Supplier>(`/suppliers/${id}`),
    enabled: Boolean(id),
  })
}

export function useCreateSupplier() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<Supplier>) => api.post<Supplier>("/suppliers", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suppliers"] })
      queryClient.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

// --- Procurement requests --------------------------------------------------

export function useRequests(status?: string) {
  return useQuery({
    queryKey: keys.requests(status),
    queryFn: () =>
      api.get<Paginated<ProcurementRequest>>(`/procurement-requests${queryString({ status, page_size: 200 })}`),
  })
}

export function useRequest(id: string | undefined) {
  return useQuery({
    queryKey: keys.request(id ?? ""),
    queryFn: () => api.get<ProcurementRequest>(`/procurement-requests/${id}`),
    enabled: Boolean(id),
  })
}

export function useCreateRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: unknown) => api.post<ProcurementRequest>("/procurement-requests", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requests"] })
      queryClient.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

export function useUpdateRequest(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: unknown) => api.put<ProcurementRequest>(`/procurement-requests/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requests"] })
      queryClient.invalidateQueries({ queryKey: keys.request(id) })
    },
  })
}

export function useDeleteRequest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/procurement-requests/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requests"] })
      queryClient.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

// --- Quotations ------------------------------------------------------------

export function useQuotations(filters: { status?: string; procurement_request_id?: string } = {}) {
  return useQuery({
    queryKey: keys.quotations(filters),
    queryFn: () =>
      api.get<Paginated<QuotationListItem>>(`/quotations${queryString({ ...filters, page_size: 200 })}`),
    // Poll while anything is still moving through the pipeline.
    refetchInterval: (query) => {
      const data = query.state.data as Paginated<QuotationListItem> | undefined
      const busy = data?.items?.some((q) => IN_PROGRESS_STATUSES.includes(q.processing_status))
      return busy ? 2500 : false
    },
  })
}

export function useQuotation(id: string | undefined) {
  return useQuery({
    queryKey: keys.quotation(id ?? ""),
    queryFn: () => api.get<QuotationDetail>(`/quotations/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const data = query.state.data as QuotationDetail | undefined
      return data && IN_PROGRESS_STATUSES.includes(data.processing_status) ? 2000 : false
    },
  })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { file: File; procurementRequestId?: string; supplierId?: string }) => {
      const form = new FormData()
      form.append("file", vars.file)
      if (vars.procurementRequestId) form.append("procurement_request_id", vars.procurementRequestId)
      if (vars.supplierId) form.append("supplier_id", vars.supplierId)
      return api.postForm<{ quotation_id: string; processing_status: string; original_filename: string }>(
        "/documents/upload",
        form,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quotations"] })
      queryClient.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

export function useApplyCorrections(quotationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { corrections: Record<string, unknown>; note?: string }) =>
      api.post<QuotationDetail>(`/quotations/${quotationId}/corrections`, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(keys.quotation(quotationId), data)
      queryClient.invalidateQueries({ queryKey: ["quotations"] })
      queryClient.invalidateQueries({ queryKey: ["comparison"] })
      queryClient.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

export function useReprocess(quotationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<QuotationDetail>(`/quotations/${quotationId}/reprocess`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.quotation(quotationId) })
      queryClient.invalidateQueries({ queryKey: ["quotations"] })
    },
  })
}

export function useLinkQuotation(quotationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { procurement_request_id?: string; supplier_id?: string }) =>
      api.patch<QuotationDetail>(`/quotations/${quotationId}/link`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.quotation(quotationId) })
      queryClient.invalidateQueries({ queryKey: ["quotations"] })
      queryClient.invalidateQueries({ queryKey: ["comparison"] })
    },
  })
}

// --- Comparison ------------------------------------------------------------

export function useComparison(requestId: string | undefined) {
  return useQuery({
    queryKey: keys.comparison(requestId ?? ""),
    queryFn: () => api.get<ComparisonResult>(`/comparisons/procurement-requests/${requestId}`),
    enabled: Boolean(requestId),
  })
}

export function useComputeComparison(requestId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { weights?: Record<string, number>; include_ai_explanation?: boolean } = {}) =>
      api.post<ComparisonResult>(`/comparisons/procurement-requests/${requestId}`, {
        include_ai_explanation: true,
        ...payload,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(keys.comparison(requestId), data)
    },
  })
}

export function useWeights() {
  return useQuery({
    queryKey: keys.weights,
    queryFn: () =>
      api.get<{ weights: Record<string, number>; thresholds: Record<string, number> }>("/comparisons/weights"),
    staleTime: 5 * 60 * 1000,
  })
}
