export interface Meta {
  catalog_quotes?: {
    enabled: boolean;
    running: boolean;
    total: number;
    covered: number;
    source_time: string | null;
    error: string | null;
  };
  request_id: string;
  mode: "EMPTY" | "DEMO" | "IMPORTED" | "MIXED" | "LIVE" | "LIVE_HISTORY";
  source: string;
  as_of: string | null;
  stale: boolean;
}
export interface Envelope<T> {
  data: T;
  meta: Meta;
}
export interface Quote {
  open?: string | null;
  high?: string | null;
  low?: string | null;
  change?: string | null;
  turnover_rate?: string | null;
  amplitude?: string | null;
  volume_ratio?: string | null;
  float_market_cap?: string | null;
  total_market_cap?: string | null;
  pe_dynamic?: string | null;
  pe_ttm?: string | null;
  pe_static?: string | null;
  float_shares?: string | null;
  total_shares?: string | null;
  buy_volume?: string | null;
  sell_volume?: string | null;
  pb?: string | null;
  limit_up?: string | null;
  limit_down?: string | null;
  order_book?: {
    bids: { level: number; price: string | null; volume: number | null }[];
    asks: { level: number; price: string | null; volume: number | null }[];
    volume_unit: 'LOT';
  } | null;
  price: string | null;
  previous_close: string | null;
  change_pct: string | null;
  volume: number | null;
  amount: string | null;
  as_of: string | null;
  source: string;
  mode: string;
  source_time?: string | null;
  fetched_at?: string | null;
  raw_hash?: string;
  stale?: boolean;
  is_realtime?: boolean;
}
export interface Security {
  id: string;
  code: string;
  name: string;
  exchange: string;
  sector: string;
  status: string;
  quote: Quote | null;
}
export interface Bar {
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number | null;
  amount: string | null;
}
export interface Bars {
  security_id: string;
  timeframe: string;
  adjustment?: 'NONE' | 'QFQ' | 'HFQ';
  history_updated_at?: string | null;
  history_source?: string | null;
  history_refresh_due?: boolean;
  bars_coverage?: { from_date: string | null; to_date: string | null; count: number };
  bars: Bar[];
  indicators: Record<string, (string | null)[]>;
  limitations: string[];
  current_bar?: {
    time: string;
    trade_date: string;
    source_time: string;
    fetched_at: string | null;
    stale: boolean;
  } | null;
}
export interface Profile {
  corporate_actions?: {
    items?: { period:string | null; published_at:string | null; record_date:string | null; ex_date:string | null; plan:string; status:string }[];
    source?:string; source_url?:string; received_at?:string; error?:string | null;
  } | null;
  security_id: string;
  business: string | null;
  facts: { label: string; value: string; period: string; source: string }[];
  events: {
    id: string;
    title: string;
    available_at: string;
    source: string;
    url: string | null;
    summary: string;
    received_at?: string | null;
    raw_hash?: string;
    publication_precision?: "DATE" | "TIME" | "UNKNOWN" | string;
    published_at?: string | null;
  }[];
  limitations: string[];
  research?: ResearchStatus;
  financials?: FinancialRecord[];
  evidence?: ResearchEvidence[];
}
export interface ResearchStatus {
  auto_refresh?: { enabled: boolean; pending: boolean };
  supported: boolean;
  provider_id: "eastmoney-research" | string;
  status: "AVAILABLE" | "SYNCED" | "PARTIAL" | "ERROR" | string;
  last_synced_at: string | null;
  error: string | null;
  sections: string[];
  section_status?: Partial<Record<ResearchSection, ResearchSectionStatus>>;
  limitations: string[];
}
export type ResearchSection = "company" | "financials" | "announcements";
export interface ResearchSectionStatus {
  status: "AVAILABLE" | "SYNCED" | "STALE" | "ERROR" | string;
  last_attempt_at: string | null;
  last_updated_at: string | null;
  source: string | null;
  error: string | null;
}
export interface FinancialRecord {
  revenue_yoy?: string | null;
  profit_yoy?: string | null;
  period: string;
  published_at: string | null;
  publication_precision: "DATE" | "TIME" | "UNKNOWN" | string;
  total_revenue: string | null;
  parent_net_profit: string | null;
  currency: "CNY" | string;
  unit: "元" | string;
  source: string;
  received_at: string;
  available_at: string;
  raw_hash: string;
}
export interface ChartEvent {
  date: string;
  kind: 'financial' | 'ex_dividend';
  title: string;
  url?: string;
}
export interface ResearchEvidence {
  id: string;
  section: "company" | "financials" | "announcements" | string;
  source: string;
  source_url: string | null;
  received_at: string;
  available_at: string;
  raw_hash: string;
}
export interface ResearchSyncResult {
  id: string;
  security_id: string;
  provider_id: string;
  status: "SUCCEEDED" | "PARTIAL" | "FAILED" | string;
  started_at: string;
  finished_at: string;
  updated_sections: string[];
  errors: string[];
  limitations: string[];
}
export interface WatchItem {
  id: string;
  security_id: string;
  group_name: string;
  tag: string;
  monitor_enabled: boolean;
  security: Security;
}
export interface Algorithm {
  id: string;
  name: string;
  kind: string;
  version: string;
  description: string;
  timeframe: string;
  status: string;
  parameters: Record<string, unknown>;
  limitations: string[];
}
export interface ResearchEvidenceManifest {
  id: string;
  section: "company" | "financials" | "announcements";
  source: string;
  source_url: string | null;
  available_at: string;
  received_at: string;
  raw_hash: string;
  included: boolean;
  exclusion_reason: string | null;
}
export interface Review {
  id: string;
  signal_id: string;
  verdict: "SUPPORT" | "CONDITIONAL" | "WAIT" | "REJECT";
  summary: string;
  supporting_evidence: string[];
  opposing_evidence: string[];
  unknowns: string[];
  conditions: string[];
  limitations: string[];
  model: string;
  mode: "UNAVAILABLE" | "RULE_DEMO" | "LLM";
  research_revision_hash?: string | null;
  research_context_snapshot?: {
    as_of: string;
    evidence: ResearchEvidenceManifest[];
    company: Record<string, unknown> | null;
    financials: Record<string, unknown>[];
    announcements: Record<string, unknown>[];
  } | null;
  research_evidence_snapshot?: ResearchEvidenceManifest[];
  model_request_attempted?: boolean;
  model_latency_ms?: number | null;
  model_error_code?: string | null;
  cited_evidence_ids?: string[];
  research_binding_status?: "CURRENT" | "STALE" | "UNBOUND" | string;
  research_binding_label?: string;
  created_at: string;
  valid_until: string;
}
export interface Recommendation {
  id: string;
  security: Security;
  algorithm_id: string;
  score: string;
  reasons: string[];
  risks: string[];
  horizon: string;
  created_at: string;
  review: Review | null;
}
export interface SignalDecision {
  agent_mode: "OFF" | "EXPLAIN" | "FILTER";
  status: string;
  label: string;
  gate_passed: boolean | null;
  reasons: string[];
  checks: {
    id: string;
    label: string;
    passed: boolean | null;
    detail: string;
  }[];
  execution_permission: "NOT_EVALUATED";
  execution_label: string;
  evaluated_at: string;
}
export interface Signal {
  decision?: SignalDecision;
  id: string;
  security: Security;
  algorithm_id: string;
  kind: "BUY" | "SELL" | "T_BUY" | "T_SELL" | "WATCH";
  status: string;
  confirmed_at: string;
  valid_until: string;
  price: string;
  conditions: {
    label: string;
    value: string;
    operator: string;
    threshold: string;
    passed: boolean | null;
  }[];
  reasons: string[];
  review: Review | null;
}
export interface Monitor {
  id: string;
  security_id: string;
  algorithm_id: string;
  enabled: boolean;
  parameters: Record<string, unknown>;
  agent_mode: "OFF" | "EXPLAIN" | "FILTER";
  updated_at: string;
}
export interface Notice {
  id: string;
  signal_id: string | null;
  title: string;
  message: string;
  created_at: string;
  read: boolean;
}
export interface Account {
  id: string;
  name: string;
  initial_cash: string;
  cash: string;
  equity: string;
  market_value: string;
  total_pnl: string;
  today_pnl: string;
  environment: "SIM";
  mode: string;
  trade_date: string;
  created_at: string;
}
export interface Position {
  security: Security;
  quantity: number;
  sellable: number;
  today_bought: number;
  average_cost: string;
  market_value: string;
  unrealized_pnl: string;
}
export interface Order {
  id: string;
  account_id: string;
  security_id: string;
  side: "BUY" | "SELL";
  quantity: number;
  filled_quantity: number;
  price: string;
  fee: string;
  purpose: "BASE" | "T";
  status: string;
  reject_reason: string | null;
  trade_date: string;
  created_at: string;
  idempotency_key: string;
}
export interface Comparison {
  today_actual_pnl?: string;
  today_baseline_pnl?: string;
  today_t_increment?: string;
  actual_equity: string;
  baseline_equity: string;
  t_increment: string;
  status: string;
  fees: string;
  open_t_quantity: number;
  explanation: string;
}
export interface AccountDetail {
  account: Account;
  positions: Position[];
  orders: Order[];
  comparison: Comparison;
}
export interface Provider {
  id: string;
  name: string;
  status: string;
  capabilities: string[];
  source: string;
  limitations: string[];
  connected?: boolean | null;
  data_mode?:
    | "SYNTHETIC"
    | "HISTORICAL"
    | "LIVE"
    | "UNAVAILABLE"
    | "DEMO"
    | "NOT_CONFIGURED"
    | "RESEARCH"
    | string;
  latest_data_at?: string | null;
  last_updated_at?: string | null;
  error?: string | null;
  warning?: string | null;
}
export interface ProviderSyncResult {
  provider_id: string;
  status: string;
  quotes_updated: number;
  daily_rows_saved: number;
  securities_processed: number;
  errors: string[];
  limitations: string[];
}
export interface ProviderSyncRun extends ProviderSyncResult {
  id: string;
  started_at: string;
  finished_at: string | null;
}
export interface ImportPreview {
  id: string;
  filename: string;
  valid_rows: number;
  invalid_rows: number;
  errors: { row: number; message: string }[];
  securities: string[];
  columns: string[];
  sample: Record<string, unknown>[];
  can_commit: boolean;
}
export interface Evaluation {
  id: string;
  name: string;
  type: string;
  sample_size: number;
  status: string;
  metrics: { label: string; value: string; description: string }[];
  limitations: string[];
}
export interface Settings {
  agent_configured: boolean;
  agent_model: string | null;
  mode: string;
  version: string;
  limitations: string[];
}
export interface Dashboard {
  security_count: number;
  watchlist_count: number;
  signal_count: number;
  pending_review_count: number;
  latest_data_at: string | null;
  indices: Record<string, unknown>[];
  notices: string[];
}

export type AutomationStatus =
  | "IDLE"
  | "RUNNING"
  | "SUCCEEDED"
  | "PARTIAL"
  | "FAILED"
  | "CANCELLED"
  | "INTERRUPTED";

export interface Automation {
  enabled: boolean;
  interval_seconds: number;
  auto_review: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_error: string | null;
  active_monitor_count: number;
  worker_running: boolean;
  limitations: string[];
}

export interface AutomationRun {
  id: string;
  status: AutomationStatus;
  trigger: "MANUAL" | "SCHEDULED";
  started_at: string;
  finished_at: string | null;
  generated: number;
  reviewed: number;
  skipped: number;
  error: string | null;
  details: string[];
}
