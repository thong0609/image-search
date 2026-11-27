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

let accessToken: string | null = null;
let searchOwner: string | null = null;
export function getSearchOwner() {
  return (searchOwner ??= crypto.randomUUID().replaceAll("-", ""));
}
export function resetSearchOwner() {
  searchOwner = null;
}
export function setAccessToken(value: string | null) {
  accessToken = value;
}

type ApiPath = `/v1/${string}` | `/health/${string}`;
type RequestOptions = Omit<RequestInit, "body"> & {
  json?: unknown;
};

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
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
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
  if (!response.ok) {
    const code = (body as { error?: { code?: string } })?.error?.code;
    if (code === "ACCESS_TOKEN_EXPIRED" && !path.startsWith("/v1/auth/")) {
      const { refreshAccess } = await import("@/features/auth/auth-provider");
      await refreshAccess();
      const retried = await fetch(path, {
        ...init,
        headers: {
          ...Object.fromEntries(headers),
          Authorization: `Bearer ${accessToken}`,
        },
        body: json === undefined ? undefined : JSON.stringify(json),
        credentials: "same-origin",
        cache: "no-store",
      });
      const result = await retried.json();
      if (!retried.ok) throw new ApiError(retried.status, result);
      return result as T;
    }
    throw new ApiError(response.status, body);
  }
  return body as T;
}

export async function mediaRequest(
  path: `/v1/${string}`,
  method = "GET",
): Promise<Blob> {
  const response = await fetch(path, {
    method,
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json();
    if (body?.error?.code === "ACCESS_TOKEN_EXPIRED") {
      const { refreshAccess } = await import("@/features/auth/auth-provider");
      await refreshAccess();
      const retried = await fetch(path, {
        method,
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      });
      if (!retried.ok) throw new ApiError(retried.status, await retried.json());
      return retried.blob();
    }
    throw new ApiError(response.status, body);
  }
  return response.blob();
}
