export type Step = {
  id: string;
  target_id: string;
  action: "resolve_entity" | "retrieve_images";
  search_text: string;
  entity_mention: string | null;
  conditions: string[];
  count: number | null;
  depends_on: string[];
  graph: Record<string, unknown> | null;
};
export type Plan = {
  query_type: "single" | "multi-target" | "multi-hop" | "unclear";
  needs_clarification: boolean;
  clarification_question: string | null;
  steps: Step[];
};
export type ImageResult = {
  image_id: string;
  image_url: string;
  score: number;
  caption: string;
  entity_names: string[];
};
export type Group = {
  target_id: string;
  search_text: string;
  status: string;
  results: ImageResult[];
  entity_scope: string[] | null;
};
export type RunResult = {
  text: string;
  mode: "planner" | "search";
  method: string;
  planner: {
    status: string;
    plan: Plan | null;
    error_code: string | null;
    model_requested: string;
    prompt_version: string;
    input_tokens: number | null;
    output_tokens: number | null;
    cached_input_tokens: number | null;
  };
  execution: {
    status: string;
    question?: string;
    message?: string;
    groups: Group[];
    trace: unknown[];
  } | null;
  timing_ms: {
    planner: number;
    startup: number;
    embedding: number;
    retrieval: number;
    total: number;
  };
};
