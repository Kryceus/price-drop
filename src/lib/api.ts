// Thin wrapper around the Python backend (server.py).
// Configure VITE_API_BASE in a `.env` file at the project root, e.g.
//   VITE_API_BASE=http://127.0.0.1:8080
// The backend must allow the frontend origin via FRONTEND_ORIGINS / CORS.

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8080";

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

type Json = Record<string, unknown> | unknown[] | null;
type ApiRecord = Record<string, unknown>;

async function request<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers,
      credentials: "include",
    });
  } catch {
    throw new ApiError(
      "Cannot reach the server. Check your connection.",
      0,
      null,
    );
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const msg =
      (data &&
        typeof data === "object" &&
        "error" in (data as ApiRecord) &&
        String((data as ApiRecord).error)) ||
      `Request failed (${res.status})`;
    throw new ApiError(msg, res.status, data);
  }

  return data as T;
}

export interface User {
  id: number;
  username: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
}

export interface Product {
  id: string;
  external_product_id: string;
  original_url?: string | null;
  product_url: string;
  domain?: string | null;
  merchant_name?: string | null;
  status?: string | null;
  last_error?: string | null;
  last_error_at?: string | null;
  last_seen_at?: string | null;
  extraction_source?: string | null;
  extraction_confidence?: number | null;
  name: string | null;
  brand: string | null;
  current_price: number | null;
  currency?: string | null;
  original_price: number | null;
  was_price: number | null;
  cup_price: string | null;
  in_stock: boolean | null;
  image_url: string | null;
  last_checked_at: string | null;
}

export interface WatchlistItem extends Product {
  watchlist_id?: number;
  last_seen_price?: number | null;
  previous_price?: number | null;
  notify_on_drop?: boolean | null;
  notify_on_increase?: boolean | null;
  last_notified_price?: number | null;
  active?: boolean;
}

export interface PriceHistoryPoint {
  price: number | null;
  was_price?: number | null;
  in_stock?: boolean | null;
  recorded_at: string;
}

export interface RefreshSummaryItem {
  product_id: string;
  name: string | null;
  old_price: number | null;
  new_price: number | null;
  has_drop: boolean;
  has_increase: boolean;
  notifications?: Array<{
    id?: number;
    status?: string;
    error?: string | null;
  }>;
}

export interface RefreshSummary {
  updated: RefreshSummaryItem[];
  drops: RefreshSummaryItem[];
  increases: RefreshSummaryItem[];
  errors: Array<{ product_id: string; error: string }>;
}

function asRecord(value: unknown): ApiRecord {
  return (value ?? {}) as ApiRecord;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function asNullableBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function normaliseProduct(raw: unknown): Product {
  const row = asRecord(raw);
  const externalProductId =
    asNullableString(row.external_product_id) ??
    asNullableString(row.product_id) ??
    "";
  const productUrl =
    asNullableString(row.product_url) ??
    asNullableString(row.canonical_url) ??
    "";
  const currentPrice =
    asNullableNumber(row.current_price) ?? asNullableNumber(row.price);
  const originalPrice =
    asNullableNumber(row.original_price) ?? asNullableNumber(row.was_price);

  return {
    id: externalProductId,
    external_product_id: externalProductId,
    original_url: asNullableString(row.original_url),
    product_url: productUrl,
    domain: asNullableString(row.domain),
    merchant_name: asNullableString(row.merchant_name),
    status: asNullableString(row.status),
    last_error: asNullableString(row.last_error),
    last_error_at: asNullableString(row.last_error_at),
    last_seen_at: asNullableString(row.last_seen_at),
    extraction_source: asNullableString(row.extraction_source),
    extraction_confidence: asNullableNumber(row.extraction_confidence),
    name: asNullableString(row.name),
    brand: asNullableString(row.brand),
    current_price: currentPrice,
    currency: asNullableString(row.currency),
    original_price: originalPrice,
    was_price: asNullableNumber(row.was_price),
    cup_price: asNullableString(row.cup_price),
    in_stock: asNullableBoolean(row.in_stock),
    image_url: asNullableString(row.image_url),
    last_checked_at: asNullableString(row.last_checked_at),
  };
}

function normaliseWatchlistItem(raw: unknown): WatchlistItem {
  const row = asRecord(raw);
  const product = normaliseProduct(raw);

  return {
    ...product,
    watchlist_id:
      typeof row.watchlist_id === "number" ? row.watchlist_id : undefined,
    last_seen_price: asNullableNumber(row.last_seen_price),
    previous_price: asNullableNumber(row.previous_price),
    notify_on_drop: asNullableBoolean(row.notify_on_drop),
    notify_on_increase: asNullableBoolean(row.notify_on_increase),
    last_notified_price: asNullableNumber(row.last_notified_price),
    active: typeof row.active === "boolean" ? row.active : undefined,
  };
}

export const auth = {
  me: () => request<{ user: User | null }>("/auth/me"),
  signup: (payload: {
    username: string;
    password: string;
    confirm_password: string;
    email?: string;
    first_name?: string;
    last_name?: string;
  }) =>
    request<{ user: User }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  login: (payload: { identifier: string; password: string }) =>
    request<{ user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  logout: () => request<Json>("/auth/logout", { method: "POST" }),
};

export const products = {
  async preview(url: string): Promise<{ product: Product }> {
    const raw = await request<unknown>(
      `/product?target=${encodeURIComponent(url)}`,
    );
    return { product: normaliseProduct(raw) };
  },

  async save(url: string): Promise<{ product: Product }> {
    const raw = await request<unknown>(`/save?target=${encodeURIComponent(url)}`);
    return { product: normaliseProduct(raw) };
  },

  async savePreview(product: Product): Promise<{ product: Product }> {
    const raw = await request<unknown>("/save-preview", {
      method: "POST",
      body: JSON.stringify({
        product_id: product.external_product_id,
        original_url: product.original_url,
        product_url: product.product_url,
        canonical_url: product.product_url,
        domain: product.domain,
        merchant_name: product.merchant_name,
        name: product.name,
        brand: product.brand,
        price: product.current_price,
        currency: product.currency,
        was_price: product.was_price,
        cup_price: product.cup_price,
        in_stock: product.in_stock,
        availability: null,
        image_url: product.image_url,
        extraction_source: product.extraction_source,
        extraction_confidence: product.extraction_confidence,
      }),
    });
    return { product: normaliseProduct(raw) };
  },

  async watchlist(): Promise<{ items: WatchlistItem[] }> {
    const data = await request<{ products?: unknown[] }>("/watchlist");
    return {
      items: Array.isArray(data.products)
        ? data.products.map(normaliseWatchlistItem)
        : [],
    };
  },

  refreshAll: () => request<RefreshSummary>("/refresh-all"),

  async refresh(productId: string): Promise<{ product: Product }> {
    const raw = await request<unknown>(
      `/refresh?product_id=${encodeURIComponent(productId)}`,
    );
    return { product: normaliseProduct(raw) };
  },

  remove: (productId: string) =>
    request<Json>(`/remove?product_id=${encodeURIComponent(productId)}`),

  async updateNotificationSettings(
    productId: string,
    payload: { notify_on_drop: boolean },
  ): Promise<{ product: WatchlistItem }> {
    const raw = await request<unknown>("/notification-settings", {
      method: "POST",
      body: JSON.stringify({
        product_id: productId,
        notify_on_drop: payload.notify_on_drop,
      }),
    });
    return { product: normaliseWatchlistItem(raw) };
  },

  history: (productId: string) =>
    request<{ history: PriceHistoryPoint[] }>(
      `/history?product_id=${encodeURIComponent(productId)}`,
    ),
};

export const notifications = {
  status: () =>
    request<{ configured: boolean; error: string | null }>(
      "/notifications/status",
    ),

  registerToken: (payload: {
    token: string;
    platform?: "android" | "ios" | "web" | "other";
    device_label?: string;
  }) =>
    request<Json>("/notification-token", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  removeToken: (token: string) =>
    request<Json>("/notification-token/remove", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  sendTest: () =>
    request<{
      ok: boolean;
      notifications: Array<{
        id?: number;
        status?: string;
        error?: string | null;
      }>;
    }>("/notifications/test", { method: "POST" }),
};
