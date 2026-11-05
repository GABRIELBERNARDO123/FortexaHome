const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  details: { field: string; message: string }[];

  constructor(message: string, status: number, details: { field: string; message: string }[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

const AUTH_PATHS = ["/auth/login", "/auth/activate", "/auth/forgot-password", "/auth/reset-password"];

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  const random = Math.random().toString(36).slice(2);
  return `fh-${Date.now().toString(36)}-${random}`;
}

export function idempotencyHeaders(key: string): Record<string, string> {
  return { "Idempotency-Key": key };
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("X-Requested-With", "FortexaHome");

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    if (response.status === 401 && !AUTH_PATHS.some((item) => path.startsWith(item))) {
      if (path.startsWith("/support/") && !path.startsWith("/support/auth/login")) {
        window.dispatchEvent(new Event("fh:support-unauthorized"));
      } else {
        window.dispatchEvent(new Event("fh:unauthorized"));
      }
    }
    const message =
      typeof payload === "object" && payload && "detail" in payload
        ? String(payload.detail)
        : "Não foi possível concluir a operação.";
    const details =
      typeof payload === "object" && payload && "errors" in payload
        ? (payload.errors as { field: string; message: string }[])
        : [];
    throw new ApiError(message, response.status, details);
  }

  return payload as T;
}

export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "X-Requested-With": "FortexaHome" },
  });
  if (!response.ok) {
    throw new ApiError("Não foi possível gerar o arquivo.", response.status);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const name = match?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.details.length > 0) {
      return error.details.map((item) => item.message).join(" ");
    }
    return error.message;
  }
  if (error instanceof TypeError) {
    return "Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.";
  }
  if (error instanceof Error) return error.message;
  return "Ocorreu um erro inesperado.";
}
