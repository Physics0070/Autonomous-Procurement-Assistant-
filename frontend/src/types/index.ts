export type UserRole = "admin" | "procurement_manager" | "member"

export type ProcessingStatus =
  | "UPLOADED"
  | "QUEUED"
  | "EXTRACTING"
  | "AI_EXTRACTING"
  | "NORMALIZING"
  | "COMPLETED"
  | "REQUIRES_REVIEW"
  | "FAILED"

export type ProcurementStatus =
  | "draft"
  | "open"
  | "comparing"
  | "awarded"
  | "closed"
  | "cancelled"

export type SourceType = "manual_upload" | "email" | "whatsapp" | "api"

export type DocumentType =
  | "pdf_digital"
  | "pdf_scanned"
  | "image"
  | "excel"
  | "csv"
  | "text"
  | "unknown"

export type MatchConfidenceLevel = "high" | "medium" | "low" | "none"

export interface Organization {
  id: string
  name: string
  industry: string | null
  created_at: string
}

export interface User {
  id: string
  name: string
  email: string
  role: UserRole
  organization_id: string
  created_at: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
  organization: Organization
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// --- Suppliers -------------------------------------------------------------

export interface SupplierReliability {
  score: number
  method: string
  sample_size: number
  factors: Record<string, any>
  notes: string[]
}

export interface Supplier {
  id: string
  organization_id: string
  name: string
  email: string | null
  phone: string | null
  gst_number: string | null
  address: string | null
  metadata: Record<string, unknown>
  reliability: SupplierReliability
  quotation_count: number
  created_at: string
  updated_at: string | null
}

// --- Procurement requests --------------------------------------------------

export interface ProcurementItem {
  item_id: string
  name: string
  quantity: number | null
  unit: string | null
  specifications: string | null
  target_unit_price: number | null
  attributes: Record<string, unknown>
  normalized_name: string | null
  normalized_tokens: string[]
  normalized_unit: string | null
  normalized_quantity: number | null
}

export interface ProcurementRequest {
  id: string
  organization_id: string
  title: string
  description: string | null
  department: string | null
  required_by: string | null
  currency: string
  status: ProcurementStatus
  items: ProcurementItem[]
  attributes: Record<string, unknown>
  quotation_count: number
  created_by: string | null
  created_at: string
  updated_at: string | null
}

// --- Documents / quotations ------------------------------------------------

export interface QuotationSource {
  type: SourceType
  original_filename: string | null
  mime_type: string | null
  size_bytes: number | null
  storage_key: string | null
  external_reference: string | null
  metadata: Record<string, unknown>
}

export interface ExtractedTable {
  name: string | null
  page: number | null
  headers: string[]
  rows: unknown[][]
  row_count: number
  column_count: number
  source: string
}

export interface PageText {
  page: number
  text: string
  char_count: number
  method: string
  ocr_confidence: number | null
}

export interface ProcessedDocument {
  quotation_id: string | null
  source_type: SourceType
  document_type: DocumentType
  raw_text: string
  pages: PageText[]
  tables: ExtractedTable[]
  detected_language: string | null
  ocr_used: boolean
  ocr_engine: string | null
  ocr_confidence: number | null
  extraction_errors: string[]
  metadata: Record<string, any>
  extracted_at: string
}

export interface ExtractedItem {
  original_name: string | null
  quantity: number | null
  unit: string | null
  unit_price: number | null
  gst_percentage: number | null
  total_price: number | null
  attributes: Record<string, unknown>
}

export interface AIExtraction {
  supplier: {
    name: string | null
    email: string | null
    phone: string | null
    gst_number: string | null
    address: string | null
  }
  quotation: {
    reference: string | null
    date: string | null
    validity: string | null
    currency: string | null
  }
  items: ExtractedItem[]
  commercials: {
    subtotal: number | null
    tax_amount: number | null
    tax_percentage: number | null
    total_amount: number | null
    transportation_cost: number | null
    delivery_days: number | null
    delivery_terms: string | null
    payment_terms: string | null
    payment_days: number | null
    warranty: string | null
  }
  additional_attributes: Record<string, unknown>
  provider: string | null
  model: string | null
  extracted_at: string | null
  raw_response: string | null
  notes: string[]
}

export interface ValidationIssue {
  field: string
  severity: "info" | "warning" | "error"
  code: string
  message: string
  observed: unknown
  expected: unknown
  item_index: number | null
}

export interface ValidationReport {
  issues: ValidationIssue[]
  requires_review: boolean
  checked_at: string | null
  error_count: number
  warning_count: number
}

export interface NormalizedItem {
  line_id: string
  original_name: string | null
  normalized_name: string | null
  normalized_tokens: string[]
  quantity: number | null
  unit: string | null
  normalized_unit: string | null
  normalized_quantity: number | null
  unit_price: number | null
  tax_percentage: number | null
  total_price: number | null
  computed_total: number | null
  attributes: Record<string, any>
  trace: {
    original_value: string | null
    normalized_value: string | null
    method: string
    confidence: number
    notes: string[]
  }
}

export interface NormalizedQuotation {
  supplier: {
    name: string | null
    normalized_name: string | null
    email: string | null
    phone: string | null
    gst_number: string | null
    address: string | null
    supplier_id: string | null
  }
  items: NormalizedItem[]
  pricing: {
    currency: string
    subtotal: number | null
    tax_amount: number | null
    tax_percentage: number | null
    transportation_cost: number | null
    total_amount: number | null
    computed_subtotal: number | null
    landed_total: number | null
  }
  delivery: {
    delivery_days: number | null
    delivery_terms: string | null
    incoterm: string | null
  }
  payment_terms: {
    payment_days: number | null
    advance_percentage: number | null
    raw_terms: string | null
  }
  quotation_reference: string | null
  quotation_date: string | null
  validity_days: number | null
  warranty: string | null
  additional_attributes: Record<string, unknown>
  missing_fields: string[]
  normalized_at: string | null
}

export interface ItemMatch {
  request_item_id: string
  request_item_name: string
  quotation_line_id: string | null
  quotation_item_name: string | null
  score: number
  confidence_level: MatchConfidenceLevel
  method: string
  requires_review: boolean
  matched: boolean
  unit_price: number | null
  quantity: number | null
  unit_compatible: boolean | null
  reasons: string[]
}

export interface MatchResult {
  quotation_id: string
  procurement_request_id: string
  matches: ItemMatch[]
  matched_count: number
  review_count: number
  unmatched_count: number
  coverage: number
  ai_assisted: boolean
}

export interface UserCorrection {
  path: string
  previous_value: unknown
  new_value: unknown
  corrected_by: string | null
  corrected_at: string | null
  note: string | null
}

export interface ProcessingEvent {
  status: ProcessingStatus
  message: string
  at: string
  details: Record<string, unknown>
}

export interface QuotationListItem {
  id: string
  organization_id: string
  source: QuotationSource
  document_type: DocumentType
  supplier_id: string | null
  supplier_name: string | null
  procurement_request_id: string | null
  processing_status: ProcessingStatus
  total_amount: number | null
  currency: string
  item_count: number
  requires_review: boolean
  issue_count: number
  created_at: string
  updated_at: string | null
}

export interface QuotationDetail extends QuotationListItem {
  raw_content: ProcessedDocument | null
  ai_extraction: AIExtraction | null
  validation: ValidationReport | null
  normalized_data: NormalizedQuotation | null
  effective_data: NormalizedQuotation | null
  match_result: MatchResult | null
  confidence: {
    extraction: number | null
    ocr: number | null
    normalization: number | null
    overall: number | null
  }
  user_corrections: UserCorrection[]
  processing_history: ProcessingEvent[]
  error: string | null
}

// --- Comparison ------------------------------------------------------------

export interface CriterionScore {
  criterion: string
  score: number
  weight: number
  weighted_score: number
  raw_value: number | null
  unit: string | null
  data_available: boolean
  deductions: string[]
}

export interface SupplierScore {
  quotation_id: string
  supplier_id: string | null
  supplier_name: string
  rank: number
  overall_score: number
  criteria: CriterionScore[]
  total_cost: number | null
  landed_cost: number | null
  currency: string
  delivery_days: number | null
  payment_days: number | null
  reliability_score: number | null
  coverage: number
  matched_items: number
  requested_items: number
  missing_data: string[]
  warnings: string[]
  price_anomaly: string | null
  data_completeness: number
}

export interface AIExplanation {
  available: boolean
  provider: string | null
  model: string | null
  summary: string | null
  reasoning: string[]
  risks: string[]
  unavailable_reason: string | null
  generated_at: string | null
}

export interface ComparisonResult {
  id: string | null
  organization_id: string | null
  procurement_request_id: string
  procurement_request_title: string | null
  currency: string
  weights: Record<string, number>
  suppliers: SupplierScore[]
  recommended_quotation_id: string | null
  recommended_supplier_name: string | null
  ai_explanation: AIExplanation
  warnings: string[]
  excluded: Array<{ quotation_id: string; supplier_name: string | null; reason: string }>
  computed_at: string
  method: string
}

// --- Dashboard -------------------------------------------------------------

export interface DashboardSummary {
  procurement_requests: { total: number; active: number; by_status: Record<string, number> }
  quotations: {
    total: number
    processed: number
    completed: number
    requires_review: number
    in_progress: number
    failed: number
    by_status: Record<string, number>
  }
  suppliers: { total: number }
  value: { quoted_total: number; currency: string }
  queue: { depth: number; in_flight: number }
  trend: Array<{ date: string; quotations: number }>
  recent_activity: Array<{
    quotation_id: string
    filename: string | null
    supplier_name: string | null
    status: ProcessingStatus
    created_at: string
    total_amount: number | null
  }>
}

export interface Capabilities {
  ocr: {
    available: boolean
    engine: string | null
    engines_installed: string[]
    message: string | null
  }
  ai: {
    configured: boolean
    provider: string
    model: string | null
    message: string | null
  }
  supported_formats: string[]
  queue: { depth: number; in_flight: number }
}
