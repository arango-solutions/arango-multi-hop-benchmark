// Wire types mirroring multihop_eval.web.schemas (the FastAPI contract).

export interface AmpInfo {
  detected: boolean;
  deployment_name: string | null;
  endpoint: string | null;
}

export interface ConnectionStatus {
  status: string;
  db: string | null;
  error: string | null;
  last_tested: string | null;
  amp: AmpInfo;
}

export interface ConnectRequest {
  mode: "amp" | "password";
  host?: string | null;
  db: string;
  username?: string;
  password?: string | null;
}

export interface CollectionItem {
  name: string;
  doc_count: number;
  kind: string;
  system: boolean;
}

export interface DatabasesResponse {
  databases: string[];
}

export interface CollectionsResponse {
  collections: CollectionItem[];
}

export interface ClustersResponse {
  clusters: string[];
}

export interface Persona {
  label: string;
  instruction: string;
}

export interface RubricField {
  name: string;
  description: string;
  scale_min: number;
  scale_max: number;
  weight: number;
}

export interface LLMConfig {
  api_url: string;
  api_key: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout_s: number;
  retries: number;
}

export interface EvalConfig {
  target_clusters: string[];
  n_questions: number;
  hop_dist: number[];
  hop_dist_weights: number[];
  max_verify_rounds: number;
  save_to_arango: boolean;
  score_with_rubric: boolean;
  personas: Persona[];
  rubric_fields: RubricField[];
}

export interface ConfigDefaults {
  project_name: string;
  collections: Record<string, string>;
  llm: LLMConfig;
  eval: Omit<EvalConfig, "personas" | "rubric_fields">;
  personas: Persona[];
  rubric_fields: RubricField[];
}

export interface ConfigSaveRequest {
  project_name: string;
  collections: Record<string, string>;
  llm: LLMConfig;
  eval: EvalConfig;
}

export interface ConfigResponse {
  saved: Record<string, unknown> | null;
  defaults: ConfigDefaults;
}

export interface RunStatus {
  status: string;
  accepted: number;
  target: number;
  summary: RunSummary | null;
  error: string | null;
  log: string[];
}

export interface RunSummary {
  accepted: number;
  rejected: number;
  accept_rate: number;
  duration_s: number;
  cluster_targets: Record<string, number>;
  cluster_achieved: Record<string, number>;
}

export interface RunStreamEvent {
  kind: string;
  ts?: string;
  line?: string;
  payload?: Record<string, unknown>;
  // terminal "status" event fields
  status?: string;
  summary?: RunSummary | null;
  error?: string | null;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export interface DashboardSummary {
  total_accepted: number;
  total_rejected: number;
  accept_rate: number;
  avg_hop_count: number | null;
  avg_weighted_rubric: number | null;
  hop_distribution: Record<string, number>;
  persona_distribution: Record<string, number>;
  cluster_coverage: Record<string, number>;
  rejection_breakdown: Record<string, number>;
  rubric_means: Record<string, number>;
  cluster_targets: Record<string, number>;
  cluster_achieved: Record<string, number>;
  duration_s: number | null;
}

export type DashboardSource = "session" | "arango";

export interface DashboardResponse {
  source: DashboardSource;
  available: boolean;
  summary: DashboardSummary | null;
  rows: Record<string, unknown>[];
  row_count: number;
}

// ---------------------------------------------------------------------------
// Ad-hoc evaluation
// ---------------------------------------------------------------------------

export interface AdhocProofPoint {
  point: string;
  source_id: string;
}

export interface AdhocRequest {
  question: string;
  answer: string;
  reasoning_chain: string;
  proof: AdhocProofPoint[];
  sources: Record<string, unknown>[];
  score_with_rubric: boolean;
}

export interface AdhocRubricScore {
  score: number;
  justification: string;
}

export interface AdhocResponse {
  multi_hop_pass: boolean;
  genuine_hop_count: number;
  multi_hop_reason: string;
  proof_verdict: string;
  corrected_proof: Record<string, unknown>[];
  rubric_scores: Record<string, AdhocRubricScore>;
  rubric_weighted_score: number | null;
}

// ---------------------------------------------------------------------------
// RAG evaluation
// ---------------------------------------------------------------------------

export type RagRelevanceMode = "binary" | "graded";
export type RagResponseSource = "jsonl" | "arango";

export interface RagEvalRequest {
  relevance_mode: RagRelevanceMode;
  k_values: number[];
  response_source: RagResponseSource;
  response_arango_collection: string;
  system_filter: string[];
  length_z_threshold: number;
  groundedness_fuzz_threshold: number;
  empty_retrieval_min_score: number | null;
  jsonl_text: string | null;
  golden_limit: number | null;
}

export interface RagMetricBundle {
  retrieval: Record<string, number>;
  generation: Record<string, number>;
  per_query: Record<string, unknown>[];
}

export interface RagEvalRun {
  system_name: string;
  n_responses: number;
  n_matched_goldens: number;
  metrics: RagMetricBundle;
  started_at: string;
  finished_at: string;
}

export interface RagEvalResponse {
  runs: RagEvalRun[];
  n_goldens: number;
  n_responses: number;
  n_systems: number;
  load_errors: string[];
}
