/** Browser-side transport. Authentication and endpoint schemas are added with their features. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`API request failed (${status})`);
    this.name = "ApiError";
  }
}

type ApiPath = `/v1/${string}` | `/health/${string}`;
type RequestOptions = Omit<RequestInit, "body"> & { json?: unknown };

export async function apiRequest<T>(
  path: ApiPath,
  options: RequestOptions = {},
): Promise<T> {
  // Also reject traversal that URL normalization could redirect outside the API namespace.
  const parsed = new URL(path, "http://local.invalid");
  if (
    parsed.origin !== "http://local.invalid" ||
    !/^\/(v1|health)\//.test(parsed.pathname) ||
    parsed.pathname !== path.split(/[?#]/)[0]
  ) {
    throw new Error("Invalid API path");
  }
  const { json, ...init } = options;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (json !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...init,
    headers,
    body: json === undefined ? undefined : JSON.stringify(json),
    credentials: "same-origin",
    cache: "no-store",
  });
  const contentType = response.headers.get("content-type") ?? "";
  const body: unknown =
    response.status === 204
      ? undefined
      : contentType.includes("application/json")
        ? await response.json()
        : undefined;
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}
