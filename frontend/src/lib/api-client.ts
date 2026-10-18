/**
 * OpsPilot API Client
 *
 * All browser-side API requests must go through this module.
 *
 * Responsibilities:
 * - Route requests to the configured FastAPI base URL.
 * - Attach the current access token.
 * - Restore sessions and refresh expired access tokens.
 * - Include refresh cookies using credentials: "include".
 * - Generate idempotency keys for write requests.
 * - Preserve ServiceResponse envelopes.
 * - Normalize API errors into ApiError.
 *
 * Business authorization and workflow rules remain in the backend.
 */

export type HttpMethod =
  | "GET"
  | "POST"
  | "PATCH"
  | "PUT"
  | "DELETE";

export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined;

export type QueryParams = Record<string, QueryValue>;

export interface ServiceInfo {
  name: string;
  category: string;
  subcategory: string;
  description: string;
}

export interface ServiceError {
  code: string;
  message: string;
  details?: unknown;
  retryable?: boolean;
}

export interface ServiceResponse<T> {
  success: boolean;
  http_status: number;
  contract_version: string;
  service: ServiceInfo;
  timestamp: string;
  request_id?: string | null;
  inputs?: unknown;
  outputs: {
    data: T | null;
    pagination?: unknown | null;
  };
  error: ServiceError | null;
}

export interface ApiRequestOptions {
  method?: HttpMethod;
  body?: unknown;
  query?: QueryParams;
  headers?: HeadersInit;
  signal?: AbortSignal;

  /**
   * true/string: use the supplied key or generate one.
   * false: do not send an idempotency key.
   * Omitted: automatically generate a key for write requests,
   * excluding authentication endpoints.
   */
  idempotencyKey?: string | boolean;

  /**
   * Override the default authentication requirement.
   * Normally leave this unset; authentication endpoints are
   * recognized automatically.
   */
  auth?: boolean;
}

type RecordValue = Record<string, unknown>;

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000/api/v1"
).replace(/\/+$/, "");

const PUBLIC_AUTH_PATHS = new Set([
  "auth/register",
  "auth/login",
  "auth/refresh",
]);

const AUTH_PATHS = new Set([
  ...PUBLIC_AUTH_PATHS,
  "auth/logout",
]);

const MUTATING_METHODS = new Set<HttpMethod>([
  "POST",
  "PATCH",
  "PUT",
  "DELETE",
]);

/**
 * Access tokens remain in memory rather than localStorage.
 * The browser manages the refresh token through an HttpOnly cookie.
 */
let accessToken: string | null = null;

/**
 * Concurrent 401 responses share a single refresh operation.
 */
let refreshInFlight: Promise<boolean> | null = null;


// ============================================================
// API ERROR
// ============================================================

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly response: ServiceResponse<unknown> | null;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      details?: unknown;
      retryable?: boolean;
      requestId?: string | null;
      response?: ServiceResponse<unknown> | null;
    },
  ) {
    super(message);

    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? "API_REQUEST_FAILED";
    this.details = options.details;
    this.retryable = options.retryable ?? false;
    this.requestId = options.requestId ?? null;
    this.response = options.response ?? null;
  }
}


// ============================================================
// SMALL INTERNAL HELPERS
// ============================================================

function requireBrowser(): void {
  if (typeof window === "undefined") {
    throw new Error(
      "api-client.ts is intended for browser-side requests. " +
      "Call it from a client component, not during server rendering.",
    );
  }
}

function isRecord(value: unknown): value is RecordValue {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function normalizePath(path: string): string {
  const normalized = path.trim().replace(/^\/+|\/+$/g, "");

  if (!normalized) {
    throw new Error("An API request path is required.");
  }

  if (/^https?:\/\//i.test(path)) {
    throw new Error(
      "Absolute URLs are not allowed. Supply a path relative to the API base URL.",
    );
  }

  return normalized;
}

function buildUrl(
  path: string,
  query?: QueryParams,
): string {
  const normalizedPath = normalizePath(path);
  const url = new URL(
    `${API_BASE_URL}/${normalizedPath}`,
  );

  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === null || value === undefined) {
      continue;
    }

    url.searchParams.set(key, String(value));
  }

  return url.toString();
}

function createIdempotencyKey(): string {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }

  return [
    Date.now().toString(36),
    Math.random().toString(36).slice(2),
    Math.random().toString(36).slice(2),
  ].join("-");
}

function shouldUseIdempotencyKey(
  method: HttpMethod,
  path: string,
): boolean {
  return (
    MUTATING_METHODS.has(method) &&
    !AUTH_PATHS.has(normalizePath(path))
  );
}

function isAuthenticationRequired(
  path: string,
  configuredValue?: boolean,
): boolean {
  if (configuredValue !== undefined) {
    return configuredValue;
  }

  return !PUBLIC_AUTH_PATHS.has(normalizePath(path));
}

async function readResponseBody(
  response: Response,
): Promise<unknown> {
  const text = await response.text();

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { message: text };
  }
}

function getAccessTokenFromResponse(
  payload: unknown,
): string | null {
  if (!isRecord(payload)) {
    return null;
  }

  const outputs = payload.outputs;
  if (!isRecord(outputs)) {
    return null;
  }

  const data = outputs.data;
  if (!isRecord(data)) {
    return null;
  }

  const token = data.access_token;

  return typeof token === "string" && token.length > 0
    ? token
    : null;
}

function makeApiError(
  payload: unknown,
  status: number,
): ApiError {
  const root = isRecord(payload) ? payload : {};
  const error = isRecord(root.error) ? root.error : {};

  const message =
    typeof error.message === "string"
      ? error.message
      : typeof root.message === "string"
        ? root.message
        : `API request failed with HTTP ${status}.`;

  const code =
    typeof error.code === "string"
      ? error.code
      : "API_REQUEST_FAILED";

  const requestId =
    typeof root.request_id === "string"
      ? root.request_id
      : null;

  const serviceResponse =
    typeof root.success === "boolean"
      ? (payload as ServiceResponse<unknown>)
      : null;

  return new ApiError(message, {
    status,
    code,
    details: error.details,
    retryable: error.retryable === true,
    requestId,
    response: serviceResponse,
  });
}


// ============================================================
// ACCESS TOKEN MANAGEMENT
// ============================================================

export function setAccessToken(token: string): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}


// ============================================================
// SESSION REFRESH
// ============================================================

async function refreshAccessToken(): Promise<boolean> {
  requireBrowser();

  if (refreshInFlight) {
    return refreshInFlight;
  }

  const pending = (async (): Promise<boolean> => {
    try {
      const response = await fetch(
        buildUrl("auth/refresh"),
        {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: {
            Accept: "application/json",
          },
        },
      );

      const payload = await readResponseBody(response);

      if (!response.ok || !isRecord(payload)) {
        accessToken = null;
        return false;
      }

      if (payload.success !== true) {
        accessToken = null;
        return false;
      }

      const token = getAccessTokenFromResponse(payload);

      if (!token) {
        accessToken = null;
        return false;
      }

      accessToken = token;
      return true;
    } catch {
      return false;
    }
  })();

  refreshInFlight = pending;

  try {
    return await pending;
  } finally {
    if (refreshInFlight === pending) {
      refreshInFlight = null;
    }
  }
}

/**
 * Restore an existing session after a page reload.
 * Returns false if no valid refresh session exists.
 */
export async function restoreSession(): Promise<boolean> {
  return refreshAccessToken();
}


// ============================================================
// REQUEST EXECUTION
// ============================================================

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ServiceResponse<T>> {
  requireBrowser();

  const normalizedPath = normalizePath(path);
  const method = options.method ?? "GET";

  const requiresAuth = isAuthenticationRequired(
    normalizedPath,
    options.auth,
  );

  let idempotencyKey: string | null = null;

  if (options.idempotencyKey === false) {
    idempotencyKey = null;
  } else if (typeof options.idempotencyKey === "string") {
    if (!options.idempotencyKey.trim()) {
      throw new Error("Idempotency key cannot be empty.");
    }

    idempotencyKey = options.idempotencyKey;
  } else if (shouldUseIdempotencyKey(method, normalizedPath)) {
    idempotencyKey = createIdempotencyKey();
  }

  const url = buildUrl(normalizedPath, options.query);

  /**
   * Restore authentication automatically if the user refreshed
   * the page and the in-memory access token was lost.
   */
  let refreshAttempted = false;

  if (requiresAuth && !accessToken) {
    refreshAttempted = true;
    await refreshAccessToken();
  }

  const execute = async (): Promise<Response> => {
    const headers = new Headers(options.headers);

    headers.set("Accept", "application/json");

    if (options.body !== undefined) {
      if (!headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
    }

    if (requiresAuth && accessToken) {
      headers.set(
        "Authorization",
        `Bearer ${accessToken}`,
      );
    } else {
      headers.delete("Authorization");
    }

    if (idempotencyKey) {
      headers.set("Idempotency-Key", idempotencyKey);
    }

    const init: RequestInit = {
      method,
      headers,
      credentials: "include",
      cache: "no-store",
      signal: options.signal,
    };

    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body);
    }

    return fetch(url, init);
  };

  let response: Response;

  try {
    response = await execute();
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }

    throw new ApiError(
      "Unable to reach the OpsPilot API. Check the backend connection.",
      {
        status: 0,
        code: "NETWORK_ERROR",
        retryable: true,
      },
    );
  }

  /**
   * An expired access token may be renewed once.
   * The original idempotency key is preserved on the retry.
   */
  if (
    response.status === 401 &&
    requiresAuth &&
    !refreshAttempted
  ) {
    refreshAttempted = true;

    const refreshed = await refreshAccessToken();

    if (refreshed) {
      try {
        response = await execute();
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          throw error;
        }

        throw new ApiError(
          "Unable to reach the OpsPilot API after refreshing the session.",
          {
            status: 0,
            code: "NETWORK_ERROR",
            retryable: true,
          },
        );
      }
    } else {
      accessToken = null;
    }
  }

  const payload = await readResponseBody(response);

  if (!response.ok) {
    if (response.status === 401 && requiresAuth) {
      accessToken = null;
    }

    throw makeApiError(payload, response.status);
  }

  if (!isRecord(payload)) {
    throw new ApiError(
      "The API returned an invalid response.",
      {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        retryable: false,
      },
    );
  }

  if (payload.success === false) {
    throw makeApiError(payload, response.status);
  }

  /**
   * Authentication responses update in-memory access-token state.
   */
  if (normalizedPath === "auth/login" ||
      normalizedPath === "auth/refresh") {
    const token = getAccessTokenFromResponse(payload);

    if (token) {
      accessToken = token;
    }
  }

  if (
    normalizedPath === "auth/logout" &&
    payload.success === true
  ) {
    accessToken = null;
  }

  return payload as unknown as ServiceResponse<T>;
}


// ============================================================
// CONVENIENCE METHODS
// ============================================================

type OptionsWithoutMethodOrBody = Omit<
  ApiRequestOptions,
  "method" | "body"
>;

export const api = {
  request: apiRequest,

  get<T>(
    path: string,
    options: OptionsWithoutMethodOrBody = {},
  ): Promise<ServiceResponse<T>> {
    return apiRequest<T>(path, {
      ...options,
      method: "GET",
    });
  },

  post<T>(
    path: string,
    body?: unknown,
    options: OptionsWithoutMethodOrBody = {},
  ): Promise<ServiceResponse<T>> {
    return apiRequest<T>(path, {
      ...options,
      method: "POST",
      body,
    });
  },

  patch<T>(
    path: string,
    body?: unknown,
    options: OptionsWithoutMethodOrBody = {},
  ): Promise<ServiceResponse<T>> {
    return apiRequest<T>(path, {
      ...options,
      method: "PATCH",
      body,
    });
  },

  put<T>(
    path: string,
    body?: unknown,
    options: OptionsWithoutMethodOrBody = {},
  ): Promise<ServiceResponse<T>> {
    return apiRequest<T>(path, {
      ...options,
      method: "PUT",
      body,
    });
  },

  delete<T>(
    path: string,
    options: OptionsWithoutMethodOrBody = {},
  ): Promise<ServiceResponse<T>> {
    return apiRequest<T>(path, {
      ...options,
      method: "DELETE",
    });
  },

  restoreSession,
  clearAccessToken,
  setAccessToken,
  createIdempotencyKey,
};