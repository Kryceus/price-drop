export function formatPrice(
  value: number | null | undefined,
  currency = "AUD",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }

  try {
    return new Intl.NumberFormat("en-AU", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `$${value.toFixed(2)}`;
  }
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) {
    return "Never checked";
  }

  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (Number.isNaN(diff)) {
    return "--";
  }

  const sec = Math.round(diff / 1000);
  if (sec < 60) {
    return "Just now";
  }

  const min = Math.round(sec / 60);
  if (min < 60) {
    return `${min}m ago`;
  }

  const hr = Math.round(min / 60);
  if (hr < 24) {
    return `${hr}h ago`;
  }

  const day = Math.round(hr / 24);
  if (day < 7) {
    return `${day}d ago`;
  }

  return d.toLocaleDateString();
}

export function priceDelta(
  current: number | null | undefined,
  previous: number | null | undefined,
) {
  if (current == null || previous == null || previous === 0) {
    return null;
  }

  const diff = current - previous;
  const pct = (diff / previous) * 100;
  return { diff, pct };
}

export function hostname(url: string | null | undefined): string {
  if (!url) {
    return "";
  }

  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
