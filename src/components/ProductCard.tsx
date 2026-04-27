import {
  AlertCircle,
  ExternalLink,
  ImageOff,
  RefreshCw,
  Trash2,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { hostname, formatPrice, formatRelativeTime, priceDelta } from "@/lib/format";
import type { Product, WatchlistItem } from "@/lib/api";

interface Props {
  product: Product | WatchlistItem;
  variant?: "preview" | "tracked";
  onSave?: () => void;
  onRemove?: () => void;
  onRefresh?: () => void;
  saving?: boolean;
  refreshing?: boolean;
  removing?: boolean;
}

export function ProductCard({
  product,
  variant = "preview",
  onSave,
  onRemove,
  onRefresh,
  saving,
  refreshing,
  removing,
}: Props) {
  const previous =
    "previous_price" in product && product.previous_price != null
      ? product.previous_price
      : "last_seen_price" in product && product.last_seen_price != null
        ? product.last_seen_price
        : product.was_price;
  const delta = priceDelta(product.current_price, previous);
  const onSale =
    product.was_price != null &&
    product.current_price != null &&
    product.was_price > product.current_price;

  return (
    <article className="animate-slide-up overflow-hidden rounded-2xl border border-border bg-card shadow-card">
      <div className="flex gap-4 p-4">
        <div className="relative h-28 w-28 shrink-0 overflow-hidden rounded-xl bg-secondary">
          {product.image_url ? (
            <img
              src={product.image_url}
              alt={product.name ?? "Product image"}
              loading="lazy"
              className="h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-muted-foreground">
              <ImageOff className="h-7 w-7" />
            </div>
          )}
          {onSale && (
            <Badge className="absolute left-1.5 top-1.5 bg-price-down text-price-down-foreground hover:bg-price-down">
              Sale
            </Badge>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          {product.brand && (
            <span className="truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {product.brand}
            </span>
          )}
          <h3 className="line-clamp-2 font-display text-[15px] font-semibold leading-snug text-foreground">
            {product.name ?? "Unnamed product"}
          </h3>

          <div className="mt-2 flex items-baseline gap-2">
            <span className="font-display text-2xl font-semibold tracking-tight">
              {formatPrice(product.current_price)}
            </span>
            {product.was_price != null &&
              product.was_price !== product.current_price && (
                <span className="text-sm text-muted-foreground line-through">
                  {formatPrice(product.was_price)}
                </span>
              )}
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {product.product_url && (
              <span className="inline-flex items-center gap-1">
                <ExternalLink className="h-3 w-3" />
                {hostname(product.product_url)}
              </span>
            )}
            {variant === "tracked" && (
              <span>{formatRelativeTime(product.last_checked_at)}</span>
            )}
            {product.cup_price && <span>{product.cup_price}</span>}
            {product.in_stock === false && (
              <span className="text-destructive">Out of stock</span>
            )}
          </div>

          {"status" in product &&
            product.status === "error" &&
            product.last_error && (
              <div className="mt-2 inline-flex items-start gap-1.5 rounded-xl bg-destructive/10 px-2.5 py-2 text-xs text-destructive">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span className="line-clamp-2">{product.last_error}</span>
              </div>
            )}

          {variant === "tracked" && delta && Math.abs(delta.diff) > 0.001 && (
            <div
              className={cn(
                "mt-2 inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                delta.diff < 0
                  ? "bg-price-down-soft text-price-down"
                  : "bg-price-up-soft text-price-up",
              )}
            >
              {delta.diff < 0 ? (
                <TrendingDown className="h-3 w-3" />
              ) : (
                <TrendingUp className="h-3 w-3" />
              )}
              {delta.diff < 0 ? "-" : "+"}
              {formatPrice(Math.abs(delta.diff))} ({delta.pct.toFixed(1)}%)
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 border-t border-border bg-surface/60 px-4 py-3">
        {variant === "preview" ? (
          <Button onClick={onSave} disabled={saving} className="flex-1" size="lg">
            {saving ? "Saving..." : "Save to Dashboard"}
          </Button>
        ) : (
          <>
            <Button
              onClick={onRefresh}
              disabled={refreshing}
              variant="secondary"
              size="sm"
              className="gap-1.5"
            >
              <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
              Refresh
            </Button>
            <a
              href={product.product_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <ExternalLink className="h-4 w-4" />
              Open
            </a>
            <div className="flex-1" />
            <Button
              onClick={onRemove}
              disabled={removing}
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
    </article>
  );
}
