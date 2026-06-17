// Thin wrapper around fetch that adds a request timeout and turns non-OK
// responses (and timeouts) into thrown errors, so callers can surface a clear
// message instead of hanging or silently swallowing failures.

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const DEFAULT_TIMEOUT = 10_000;

type ApiInit = RequestInit & { timeout?: number };

export async function apiFetch(input: string, init: ApiInit = {}): Promise<Response> {
  const { timeout = DEFAULT_TIMEOUT, signal, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  // Respect a caller-supplied signal in addition to the timeout.
  if (signal) signal.addEventListener("abort", () => controller.abort());
  try {
    const res = await fetch(input, { ...rest, signal: controller.signal });
    if (!res.ok) {
      throw new ApiError(`Request failed (${res.status})`, res.status);
    }
    return res;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("Request timed out", 0);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function apiJson<T>(input: string, init?: ApiInit): Promise<T> {
  const res = await apiFetch(input, init);
  return (await res.json()) as T;
}

// Convenience for JSON POST/PUT bodies — sets the content-type header.
export function jsonBody(method: "POST" | "PUT", body: unknown): ApiInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
