"use client";

import { useState, type FormEvent } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  ArrowDown,
  ArrowUpRight,
  ChevronDown,
  Images,
  LoaderCircle,
  Search,
  Workflow,
} from "lucide-react";
import { apiRequest, ApiError } from "@/lib/api/client";
import type { RunResult, Step } from "./types";

const examples = [
  {
    label: "Một mục tiêu",
    text: "Tìm ảnh về Công viên Thảo Cầm Viên Sài Gòn (Q.1).",
  },
  {
    label: "Nhiều mục tiêu",
    text: "Tìm 2 ảnh về Công viên Thảo Cầm Viên Sài Gòn (Q.1) và 2 ảnh về Chợ Hàn Hải Châu Đà Nẵng.",
  },
  {
    label: "Qua cảnh nhận diện",
    text: "Tìm ảnh quầy bán mũ bên trong khu chợ ở Đà Nẵng có mặt tiền vàng nhạt, mái tam giác viền đỏ và cửa vòm lớn.",
  },
];
const statuses: Record<string, string> = {
  candidate_results: "Đã có ứng viên ảnh",
  execution_error: "Retrieval gặp lỗi",
  candidates: "Có ứng viên",
  partial_results: "Có kết quả một phần",
  unsupported_graph_relation: "Chưa hỗ trợ bước nhận diện hoặc quan hệ này",
  unresolved: "Chưa xác định được kết quả",
  no_graph_match: "Không tìm thấy entity thỏa điều kiện graph",
  no_candidates: "Không có ảnh phù hợp trong phạm vi tìm kiếm",
  entity_not_found: "Không tìm thấy entity",
  ambiguous_entity: "Entity chưa xác định duy nhất",
  insufficient_candidates: "Chưa đủ số ảnh yêu cầu",
  needs_clarification: "Cần làm rõ yêu cầu",
};
function statusLabel(status: string) {
  return statuses[status] ?? status;
}
function seconds(ms: number) {
  return `${(ms / 1000).toFixed(2)} s`;
}
function plannerError(code: string | null) {
  if (code === "api_http_429")
    return "OpenAI đang giới hạn lượt gọi hoặc hết quota. Kiểm tra tài khoản API.";
  if (code === "api_http_401" || code === "api_http_403")
    return "OpenAI không chấp nhận API key hoặc quyền truy cập model.";
  if (code === "api_timeout")
    return "OpenAI phản hồi quá thời gian chờ. Bạn có thể chủ động thử lại.";
  return `Planner chưa tạo được kế hoạch (${code ?? "không rõ lỗi"}).`;
}
function StepCard({ step, index }: { step: Step; index: number }) {
  return (
    <article className="step-card">
      <div className="step-heading">
        <span className="step-number">{index + 1}</span>
        <strong>
          {step.action === "resolve_entity" ? "Xác định thực thể" : "Tìm ảnh"}
        </strong>
        <span className="step-id">
          {step.id} · {step.target_id}
        </span>
      </div>
      <p className="step-text">{step.search_text}</p>
      <dl className="step-facts">
        <div>
          <dt>Thực thể</dt>
          <dd>{step.entity_mention ?? "Chưa nêu tên cụ thể"}</dd>
        </div>
        <div>
          <dt>Phụ thuộc</dt>
          <dd>
            {step.depends_on.length ? step.depends_on.join(", ") : "Không có"}
          </dd>
        </div>
        {step.action === "retrieve_images" && (
          <div>
            <dt>Số ảnh</dt>
            <dd>{step.count ?? "Không yêu cầu cụ thể"}</dd>
          </div>
        )}
      </dl>
      {step.conditions.length > 0 && (
        <div className="condition-list">
          {step.conditions.map((c, i) => (
            <span key={i}>{c}</span>
          ))}
        </div>
      )}
      {step.graph && (
        <details className="graph-details">
          <summary>
            Điều kiện graph <ChevronDown size={13} />
          </summary>
          <pre>{JSON.stringify(step.graph, null, 2)}</pre>
        </details>
      )}
    </article>
  );
}

export function Playground() {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"planner" | "search">("planner");
  const [method, setMethod] = useState("hybrid");
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || pending) return;
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const response = await apiRequest<RunResult>("/v1/playground/run", {
        method: "POST",
        json: { text: text.trim(), mode, method },
      });
      setResult(response);
    } catch (err) {
      if (
        err instanceof ApiError &&
        typeof err.body === "object" &&
        err.body !== null &&
        "detail" in err.body &&
        typeof err.body.detail === "string"
      )
        setError(err.body.detail);
      else
        setError(
          "Không kết nối được backend. Kiểm tra backend đang chạy rồi thử lại.",
        );
    } finally {
      setPending(false);
    }
  }
  const plan = result?.planner.plan;
  const groups = result?.execution?.groups ?? [];
  const imageCount = groups.reduce(
    (sum, group) => sum + group.results.length,
    0,
  );

  return (
    <div className="playground">
      <header className="topbar">
        <Link href="/" className="brand">
          <span className="brand-icon">
            <Images size={20} />
          </span>
          Image Search<span className="lab-tag">LAB</span>
        </Link>
        <span className="local-label">
          <i /> Thử nghiệm local
        </span>
      </header>
      <main className="workspace">
        <section className="intro">
          <span className="eyebrow">SEARCH PLAYGROUND</span>
          <h1>Tìm ảnh. Hiểu từng bước.</h1>
          <p>
            Nhập yêu cầu để xem planner hiểu câu hỏi và pipeline tìm ảnh như thế
            nào.
          </p>
        </section>
        <section className="query-panel" aria-label="Truy vấn thử nghiệm">
          <form onSubmit={submit}>
            <label htmlFor="query" className="query-label">
              Bạn muốn tìm ảnh gì?
            </label>
            <textarea
              id="query"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={4000}
              required
              disabled={pending}
              placeholder="Ví dụ: Tìm ảnh bên trong khu chợ có mặt tiền vàng nhạt ở Đà Nẵng…"
              rows={3}
            />
            <div className="query-controls">
              <fieldset className="mode-picker" disabled={pending}>
                <legend className="sr-only">Chế độ chạy</legend>
                <button
                  type="button"
                  aria-pressed={mode === "planner"}
                  onClick={() => setMode("planner")}
                >
                  <Workflow size={15} />
                  Chỉ planner
                </button>
                <button
                  type="button"
                  aria-pressed={mode === "search"}
                  onClick={() => setMode("search")}
                >
                  <Images size={15} />
                  Planner + tìm ảnh
                </button>
              </fieldset>
              <div className="run-controls">
                {mode === "search" && (
                  <label className="method-label">
                    <span className="sr-only">Phương pháp tìm kiếm</span>
                    <select
                      value={method}
                      onChange={(e) => setMethod(e.target.value)}
                      disabled={pending}
                    >
                      <option value="hybrid">Hybrid · RRF 1:1</option>
                      <option value="vector">Vector</option>
                      <option value="keyword">Keyword · BM25</option>
                    </select>
                  </label>
                )}
                <button
                  className="run-button"
                  disabled={pending || !text.trim()}
                  type="submit"
                >
                  {pending ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <Search size={17} />
                  )}
                  {pending ? "Đang xử lý…" : "Chạy thử"}
                </button>
              </div>
            </div>
          </form>
          <div className="query-note">
            Mỗi lần chạy gọi OpenAI API. Ảnh được tìm trong dataset hiện có.
          </div>
        </section>
        <div className="examples">
          <span>Thử nhanh</span>
          {examples.map((example) => (
            <button
              key={example.label}
              disabled={pending}
              onClick={() => setText(example.text)}
            >
              {example.label}
              <ArrowUpRight size={13} />
            </button>
          ))}
        </div>
        {error && (
          <div role="alert" className="error-banner">
            {error}
          </div>
        )}
        <div aria-live="polite" aria-busy={pending}>
          {pending && (
            <section className="loading-panel">
              <LoaderCircle className="spin" size={23} />
              <div>
                <strong>Đang lập kế hoạch và xử lý yêu cầu</strong>
                <p>
                  OpenAI có thể cần vài chục giây. Lần tìm ảnh đầu tiên còn cần
                  nạp model.
                </p>
              </div>
            </section>
          )}
          {result && (
            <>
              <section className="run-summary">
                <div>
                  <span className="result-label">PLANNER PHÂN LOẠI</span>
                  <h2>{plan?.query_type ?? "Lỗi planner"}</h2>
                </div>
                <div className="summary-stat">
                  <span>Tổng thời gian</span>
                  <strong>{seconds(result.timing_ms.total)}</strong>
                </div>
                <div className="summary-stat">
                  <span>Token vào / ra</span>
                  <strong>
                    {result.planner.input_tokens ?? "—"} /{" "}
                    {result.planner.output_tokens ?? "—"}
                  </strong>
                </div>
                <div className="summary-stat">
                  <span>Ảnh trả về</span>
                  <strong>
                    {result.mode === "search" ? imageCount : "Chưa tìm ảnh"}
                  </strong>
                </div>
              </section>
              <div className="run-meta">
                <span>{result.planner.model_requested}</span>
                <span>
                  Chế độ:{" "}
                  {result.mode === "planner"
                    ? "Chỉ planner"
                    : `Tìm ảnh · ${result.method}`}
                </span>
              </div>
              <p className="submitted-query">“{result.text}”</p>
              {result.planner.status !== "ok" && (
                <div role="alert" className="error-banner">
                  {plannerError(result.planner.error_code)}
                </div>
              )}
              {plan?.needs_clarification && (
                <div className="notice">
                  <strong>Planner cần bạn làm rõ</strong>
                  <p>{plan.clarification_question}</p>
                </div>
              )}
              {plan && !plan.needs_clarification && (
                <div className="result-layout">
                  <section className="plan-section">
                    <div className="section-heading">
                      <h2>
                        <Workflow size={18} />
                        Kế hoạch
                      </h2>
                      <span>{plan.steps.length} bước</span>
                    </div>
                    <div className="step-list">
                      {plan.steps.map((step, index) => (
                        <div key={step.id}>
                          {index > 0 && (
                            <div className="step-arrow">
                              <ArrowDown size={15} />
                            </div>
                          )}
                          <StepCard step={step} index={index} />
                        </div>
                      ))}
                    </div>
                    <p className="plan-note">
                      Loại câu hỏi và các bước ở trên do planner dự đoán, có thể
                      chưa chính xác.
                    </p>
                  </section>
                  <section className="images-section">
                    <div className="section-heading">
                      <h2>
                        <Images size={18} />
                        Kết quả ảnh
                      </h2>
                      {result.execution && <span>{imageCount} ảnh</span>}
                    </div>
                    {!result.execution && (
                      <div className="empty-results">
                        <Images size={30} />
                        <h3>Đang xem riêng planner</h3>
                        <p>
                          Chọn “Planner + tìm ảnh” rồi chạy lại để xem kết quả
                          theo kế hoạch.
                        </p>
                      </div>
                    )}
                    {result.execution && (
                      <div className="execution-status">
                        {statusLabel(result.execution.status)}
                      </div>
                    )}
                    {result.execution?.message && (
                      <div className="error-banner" role="alert">
                        {result.execution.message}
                      </div>
                    )}
                    {groups.map((group) => (
                      <article className="image-group" key={group.target_id}>
                        <div className="group-title">
                          <span>{group.target_id}</span>
                          <h3>{group.search_text}</h3>
                        </div>
                        <p className="group-status">
                          {statusLabel(group.status)}
                          {group.verification_status ===
                            "visual_bridge_unverified" &&
                            " · Nơi chứa được suy đoán từ ảnh tương tự, chưa xác minh"}
                        </p>
                        {!group.results.length && (
                          <div className="no-images">
                            {group.status === "unsupported_graph_relation"
                              ? "Bước nhận diện qua cảnh khác hoặc quan hệ này chưa được pipeline hỗ trợ. Có kế hoạch không đồng nghĩa đã tìm được ảnh."
                              : "Chưa có ảnh trả về cho mục tiêu này. Xem kế hoạch và chi tiết thực thi bên dưới."}
                          </div>
                        )}
                        <div className="image-grid">
                          {group.results.map((row) => (
                            <figure key={row.image_id}>
                              <a
                                href={row.image_url}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={`Mở ảnh ${row.entity_names.join(", ")}`}
                              >
                                <Image
                                  src={row.image_url}
                                  alt={
                                    row.caption || row.entity_names.join(", ")
                                  }
                                  width={480}
                                  height={340}
                                  unoptimized
                                />
                              </a>
                              <figcaption>
                                <strong>
                                  {row.entity_names.join(" · ") ||
                                    "Ảnh trong dataset"}
                                </strong>
                                <p>{row.caption}</p>
                                <span>
                                  Điểm xếp hạng: {row.score.toFixed(4)}
                                </span>
                              </figcaption>
                            </figure>
                          ))}
                        </div>
                      </article>
                    ))}
                  </section>
                </div>
              )}
              <section className="diagnostics">
                <details>
                  <summary>
                    Thời gian & chi tiết thực thi <ChevronDown size={15} />
                  </summary>
                  <div className="timing-grid">
                    {Object.entries(result.timing_ms).map(([name, value]) => (
                      <div key={name}>
                        <span>
                          {
                            (
                              {
                                planner: "Planner",
                                startup: "Nạp dữ liệu / model",
                                embedding: "Embedding",
                                retrieval: "Retrieval",
                                total: "Tổng",
                              } as Record<string, string>
                            )[name]
                          }
                        </span>
                        <strong>{seconds(value)}</strong>
                      </div>
                    ))}
                  </div>
                  <p>
                    Thời gian tổng có tính cả nạp model ở lần tìm ảnh đầu tiên.
                    Điểm xếp hạng không phải xác suất đúng.
                  </p>
                  <details>
                    <summary>JSON phản hồi</summary>
                    <pre>{JSON.stringify(result, null, 2)}</pre>
                  </details>
                </details>
              </section>
            </>
          )}
          {!pending && !result && !error && (
            <section className="start-panel">
              <span className="start-icon">
                <Workflow size={28} />
              </span>
              <h2>Từ câu hỏi đến kế hoạch tìm ảnh</h2>
              <p>
                Xem planner tách mục tiêu, xác định thực thể
                <br className="desktop-break" /> và nối các bước phụ thuộc trước
                khi tìm kiếm.
              </p>
              <div className="flow-labels">
                <span>Câu hỏi</span>
                <span>→</span>
                <span>Kế hoạch</span>
                <span>→</span>
                <span>Ảnh kết quả</span>
              </div>
            </section>
          )}
        </div>
        <footer>Playground thử nghiệm · SigLIP2 + BM25 + Qdrant + Neo4j</footer>
      </main>
    </div>
  );
}
