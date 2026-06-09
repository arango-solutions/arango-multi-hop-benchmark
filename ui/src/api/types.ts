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
  collections: Record<string, string>;
  llm: LLMConfig;
  eval: Omit<EvalConfig, "personas" | "rubric_fields">;
  personas: Persona[];
  rubric_fields: RubricField[];
}

export interface ConfigSaveRequest {
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
