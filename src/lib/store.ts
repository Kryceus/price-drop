// Frontend-only helper to derive a store from a product URL hostname.
// Add new stores here as the backend grows.

export type StoreId =
  | "woolworths"
  | "coles"
  | "aldi"
  | "iga"
  | "amazon"
  | "other";

export interface StoreMeta {
  id: StoreId;
  label: string;
  hostMatchers: string[];
}

export const STORES: StoreMeta[] = [
  { id: "woolworths", label: "Woolworths", hostMatchers: ["woolworths"] },
  { id: "coles", label: "Coles", hostMatchers: ["coles"] },
  { id: "aldi", label: "ALDI", hostMatchers: ["aldi"] },
  { id: "iga", label: "IGA", hostMatchers: ["iga"] },
  { id: "amazon", label: "Amazon", hostMatchers: ["amazon."] },
];

export function getStoreFromUrl(url: string | null | undefined): StoreId {
  if (!url) {
    return "other";
  }

  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    host = String(url).toLowerCase();
  }

  for (const store of STORES) {
    if (store.hostMatchers.some((matcher) => host.includes(matcher))) {
      return store.id;
    }
  }

  return "other";
}

export function getStoreLabel(id: StoreId): string {
  return STORES.find((store) => store.id === id)?.label ?? "Other";
}
