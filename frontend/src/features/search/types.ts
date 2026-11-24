export type SearchItem = {
  id: string;
  title: string;
  caption: string;
  width: number | null;
  height: number | null;
  source_url: string | null;
  source_name: string | null;
};
export type SearchGroup = {
  id: string;
  label: string;
  approximate: boolean;
  items: SearchItem[];
};
export type SearchResponse = {
  query: string;
  question: string | null;
  planned: boolean;
  plan_cached: boolean;
  groups: SearchGroup[];
  took_ms: number;
};
