/** Hooks and types for Phases 3–6: channels, communications, purchase orders, agents, analytics. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

// --- Types -------------------------------------------------------------------

export interface HistoryEntry {
  action: string
  by: string
  at: string
  [key: string]: unknown
}

export interface GmailChannel {
  connected: boolean
  status: string
  configured: boolean
  account_email?: string | null
  connected_at?: string | null
  last_synced_at?: string | null
  last_result?: { messages_scanned: number; documents_imported: number; duplicates_skipped: number; attachments_ignored: number; errors: string[] } | null
  last_error?: string | null
  sync_interval_minutes: number
  query: string
}

export interface Channels {
  gmail: GmailChannel
  whatsapp: { status: string; message: string }
}

export type CommunicationStatus = "draft" | "approved" | "sent" | "cancelled"

export interface Communication {
  id: string
  kind: "rfq" | "negotiation" | "purchase_order"
  status: CommunicationStatus
  subject: string
  body: string
  to_email: string | null
  generated_by: "ai" | "template"
  provider: string | null
  model: string | null
  fallback_reason: string | null
  guardrail_findings: string[]
  target_price?: number | null
  procurement_request_id: string | null
  supplier_id: string | null
  quotation_id?: string | null
  purchase_order_id?: string | null
  history: HistoryEntry[]
  created_at: string
}

export type POStatus = "draft" | "approved" | "issued" | "delivered" | "closed" | "cancelled"

export interface PurchaseOrder {
  id: string
  po_number: string
  status: POStatus
  procurement_request_id: string | null
  quotation_id: string | null
  supplier_id: string | null
  supplier: { name: string | null; email?: string | null; gst_number?: string | null; address?: string | null }
  buyer: { name: string | null; gst_number?: string | null; address?: string | null }
  lines: Array<{ description: string; quantity: number; unit: string | null; unit_price: number; tax_percentage: number; line_total: number }>
  warnings: string[]
  pricing: { currency: string; subtotal: number; taxes: Array<{ name: string; rate: number; amount: number }>; freight: number; total: number }
  terms: { delivery_days: number | null; payment_terms: string | null }
  expected_delivery_date?: string | null
  delivered_at?: string | null
  on_time?: boolean | null
  delay_days?: number | null
  history: HistoryEntry[]
  created_at: string
}

export interface AgentStep {
  agent: string
  action: string
  summary: string
  started_at: string
  finished_at?: string
  error: string | null
}

export interface AgentRun {
  id: string
  graph: string
  status: string
  input: Record<string, string>
  steps: AgentStep[]
  output: Record<string, any> | null
  created_at: string
}

export interface ChatToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface ConversationMessage {
  role: "user" | "assistant" | "tool" | "system"
  content: string | null
  tool_calls: ChatToolCall[]
  tool_call_id: string | null
  name: string | null
  at: string
}

export interface Conversation {
  id: string
  title: string
  messages: ConversationMessage[]
}

export interface OrganizationProfile {
  id: string
  name: string
  industry: string | null
  address: string | null
  gst_number: string | null
  state: string | null
  state_code: string | null
  contact_email: string | null
  contact_phone: string | null
}

export interface SpendSummary {
  currency: string
  total_spend: number
  orders: number
  by_supplier: Array<{ supplier: string; spend: number; orders: number; delivered: number; on_time: number; on_time_rate: number | null }>
  by_month: Array<{ month: string; spend: number }>
  by_item: Array<{ item: string; spend: number; quantity: number }>
  savings: Array<{ po_number: string; highest_quote: number; awarded: number; saving: number }>
}

export interface ForecastItem {
  item: string
  status: "ok" | "insufficient_data"
  method?: string
  history_months: number
  backtest_smape?: Record<string, number>
  forecast?: Array<{ month: string; quantity: number }>
}

export interface ModelsInfo {
  reliability: {
    available: boolean
    reason?: string
    own_data?: boolean
    model_version?: string
    model_name?: string
    trained_on?: string
    test?: { rows: number; late_rate: number; roc_auc: number; pr_auc: number; macro_f1: number; brier: number }
    baselines?: Record<string, { roc_auc: number; pr_auc: number; macro_f1: number }>
    min_retrain_orders?: number
  }
  price_anomaly: { method: string; min_samples: number; fallback: string }
  forecast: { methods: string[]; min_months: number }
}

// --- Hooks -------------------------------------------------------------------

function useInvalidate() {
  const queryClient = useQueryClient()
  return (...roots: string[]) => roots.forEach((root) => queryClient.invalidateQueries({ queryKey: [root] }))
}

export const useChannels = () =>
  useQuery({ queryKey: ["channels"], queryFn: () => api.get<Channels>("/channels") })

export function useGmailActions() {
  const invalidate = useInvalidate()
  const done = { onSuccess: () => invalidate("channels", "quotations", "dashboard") }
  return {
    connect: useMutation({
      mutationFn: async () => {
        const { authorize_url } = await api.get<{ authorize_url: string }>("/channels/gmail/authorize")
        window.location.assign(authorize_url)
      },
    }),
    sync: useMutation({ mutationFn: () => api.post("/channels/gmail/sync"), ...done }),
    disconnect: useMutation({ mutationFn: () => api.delete("/channels/gmail"), ...done }),
  }
}

export const useCommunications = (filters: { kind?: string; status?: string } = {}) =>
  useQuery({
    queryKey: ["communications", filters],
    queryFn: () =>
      api.get<Communication[]>(`/communications?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][])}`),
  })

export function useCommunicationActions() {
  const invalidate = useInvalidate()
  const done = { onSuccess: () => invalidate("communications") }
  return {
    edit: useMutation({
      mutationFn: ({ id, ...changes }: { id: string; subject?: string; body?: string; to_email?: string }) =>
        api.patch<Communication>(`/communications/${id}`, changes),
      ...done,
    }),
    act: useMutation({
      mutationFn: ({ id, action }: { id: string; action: "approve" | "mark-sent" | "cancel" }) =>
        api.post<Communication>(`/communications/${id}/${action}`),
      ...done,
    }),
    draftRfqs: useMutation({
      mutationFn: ({ requestId, supplierIds }: { requestId: string; supplierIds: string[] }) =>
        api.post<Communication[]>(`/procurement-requests/${requestId}/rfqs`, { supplier_ids: supplierIds }),
      ...done,
    }),
    draftNegotiation: useMutation({
      mutationFn: ({ requestId, quotationId }: { requestId: string; quotationId: string }) =>
        api.post<Communication>(`/comparisons/procurement-requests/${requestId}/negotiations`, { quotation_id: quotationId }),
      ...done,
    }),
  }
}

export const usePurchaseOrders = () =>
  useQuery({ queryKey: ["purchase-orders"], queryFn: () => api.get<PurchaseOrder[]>("/purchase-orders") })

export function usePurchaseOrderActions() {
  const invalidate = useInvalidate()
  const done = { onSuccess: () => invalidate("purchase-orders", "communications", "requests", "request", "suppliers", "analytics") }
  return {
    award: useMutation({
      mutationFn: ({ requestId, quotationId }: { requestId: string; quotationId: string }) =>
        api.post<PurchaseOrder>(`/comparisons/procurement-requests/${requestId}/award`, { quotation_id: quotationId }),
      ...done,
    }),
    act: useMutation({
      mutationFn: ({ id, action, deliveredAt }: { id: string; action: string; deliveredAt?: string }) =>
        api.post<PurchaseOrder>(`/purchase-orders/${id}/${action}`, deliveredAt ? { delivered_at: deliveredAt } : undefined),
      ...done,
    }),
  }
}

export const useOrganizationProfile = () =>
  useQuery({ queryKey: ["organization"], queryFn: () => api.get<OrganizationProfile>("/organizations/me") })

export function useUpdateOrganization() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (payload: Partial<OrganizationProfile>) => api.put<OrganizationProfile>("/organizations/me", payload),
    onSuccess: () => invalidate("organization", "auth"),
  })
}

export const useAgentRuns = (filters: Record<string, string | undefined>) =>
  useQuery({
    queryKey: ["agent-runs", filters],
    queryFn: () =>
      api.get<AgentRun[]>(`/agents/runs?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][])}`),
  })

export function useRunSourcing() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (requestId: string) => api.post<AgentRun>(`/agents/sourcing/${requestId}`),
    onSuccess: () => invalidate("agent-runs", "communications", "comparison"),
  })
}

export const useConversations = () =>
  useQuery({ queryKey: ["conversations"], queryFn: () => api.get<Array<{ id: string; title: string; updated_at: string }>>("/assistant/conversations") })

export const useConversation = (id: string | null) =>
  useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api.get<Conversation>(`/assistant/conversations/${id}`),
    enabled: Boolean(id),
  })

export function useSendMessage() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (payload: { message: string; conversation_id: string | null }) =>
      api.post<{ conversation_id: string; answer: string }>("/assistant/messages", payload),
    onSuccess: () => invalidate("conversations", "conversation", "communications"),
  })
}

export const useSpend = () => useQuery({ queryKey: ["analytics", "spend"], queryFn: () => api.get<SpendSummary>("/analytics/spend") })
export const useForecast = () =>
  useQuery({ queryKey: ["analytics", "forecast"], queryFn: () => api.get<{ min_months: number; items: ForecastItem[] }>("/analytics/forecast") })
export const useModels = () => useQuery({ queryKey: ["analytics", "models"], queryFn: () => api.get<ModelsInfo>("/analytics/models") })

export function useRetrain() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: () => api.post("/analytics/models/reliability/retrain"), onSuccess: () => invalidate("analytics", "suppliers") })
}
