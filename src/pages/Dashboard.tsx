import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  LayoutGrid,
  LogIn,
  RefreshCw,
  Store as StoreIcon,
} from "lucide-react";
import { AppHeader } from "@/components/layout/AppHeader";
import { Button } from "@/components/ui/button";
import { ProductCard } from "@/components/ProductCard";
import { ProductCardSkeleton } from "@/components/ProductCardSkeleton";
import { EmptyState } from "@/components/EmptyState";
import {
  ApiError,
  products,
  type RefreshSummary,
  type WatchlistItem,
} from "@/lib/api";
import { getStoreFromUrl, STORES, type StoreId } from "@/lib/store";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

type StoreFilter = "all" | StoreId;

export default function Dashboard() {
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<WatchlistItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [storeFilter, setStoreFilter] = useState<StoreFilter>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { items } = await products.watchlist();
      setItems(items);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Could not load dashboard",
      );
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authLoading) {
      load();
    }
  }, [authLoading, load]);

  const counts = useMemo(() => {
    const map = new Map<StoreId, number>();
    for (const item of items ?? []) {
      const store = getStoreFromUrl(item.product_url);
      map.set(store, (map.get(store) ?? 0) + 1);
    }
    return map;
  }, [items]);

  const availableStores = useMemo(
    () => STORES.filter((store) => (counts.get(store.id) ?? 0) > 0),
    [counts],
  );

  const filteredItems = useMemo(() => {
    if (!items) {
      return items;
    }
    if (storeFilter === "all") {
      return items;
    }
    return items.filter(
      (item) => getStoreFromUrl(item.product_url) === storeFilter,
    );
  }, [items, storeFilter]);

  function summariseRefresh(result: RefreshSummary) {
    if (result.drops.length) {
      toast.success(
        `${result.drops.length} price drop${
          result.drops.length === 1 ? "" : "s"
        } found`,
      );
      return;
    }

    if (result.increases.length) {
      toast.success(
        `${result.increases.length} price increase${
          result.increases.length === 1 ? "" : "s"
        } detected`,
      );
      return;
    }

    toast.success("Prices refreshed");
  }

  async function handleRefreshAll() {
    setRefreshing(true);
    try {
      const result = await products.refreshAll();
      await load();
      summariseRefresh(result);
      if (result.errors.length) {
        toast.error(
          `${result.errors.length} product${
            result.errors.length === 1 ? "" : "s"
          } could not be refreshed`,
        );
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleRefreshOne(item: WatchlistItem) {
    setBusyId(item.id);
    try {
      const { product } = await products.refresh(item.id);
      setItems((prev) =>
        prev
          ? prev.map((existing) =>
              existing.id === item.id ? { ...existing, ...product } : existing,
            )
          : prev,
      );
      toast.success("Updated");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not refresh");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemove(item: WatchlistItem) {
    setBusyId(item.id);
    try {
      await products.remove(item.id);
      setItems((prev) => (prev ? prev.filter((p) => p.id !== item.id) : prev));
      toast.success("Removed from dashboard");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <AppHeader
        title="Dashboard"
        subtitle={
          items
            ? `${items.length} tracked ${
                items.length === 1 ? "product" : "products"
              }`
            : undefined
        }
        action={
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefreshAll}
            disabled={refreshing || loading || !items?.length}
            className="gap-1.5"
          >
            <RefreshCw
              className={cn("h-4 w-4", refreshing && "animate-spin")}
            />
            <span className="hidden sm:inline">Refresh all</span>
          </Button>
        }
      />

      <div className="space-y-3 px-4 pt-4">
        {!user && !authLoading && (
          <EmptyState
            icon={<LogIn className="h-6 w-6" />}
            title="Sign in to sync"
            description="You can browse a temporary watchlist, but signing in keeps your tracked products saved across devices."
            action={
              <Button asChild>
                <Link to="/account">Sign in</Link>
              </Button>
            }
          />
        )}

        {loading && (
          <>
            <ProductCardSkeleton />
            <ProductCardSkeleton />
          </>
        )}

        {!loading && items && items.length === 0 && (
          <EmptyState
            icon={<LayoutGrid className="h-6 w-6" />}
            title="No tracked products yet"
            description="Paste a URL on Home to start tracking prices."
            action={
              <Button asChild>
                <Link to="/">Track your first product</Link>
              </Button>
            }
          />
        )}

        {!loading && items && items.length > 0 && (
          <div className="-mx-4 overflow-x-auto px-4 pb-1">
            <div className="flex w-max gap-2">
              <FilterChip
                active={storeFilter === "all"}
                onClick={() => setStoreFilter("all")}
                label="All"
                count={items.length}
                icon={<StoreIcon className="h-3.5 w-3.5" />}
              />
              {availableStores.map((store) => (
                <FilterChip
                  key={store.id}
                  active={storeFilter === store.id}
                  onClick={() => setStoreFilter(store.id)}
                  label={store.label}
                  count={counts.get(store.id) ?? 0}
                />
              ))}
              {(counts.get("other") ?? 0) > 0 && (
                <FilterChip
                  active={storeFilter === "other"}
                  onClick={() => setStoreFilter("other")}
                  label="Other"
                  count={counts.get("other") ?? 0}
                />
              )}
            </div>
          </div>
        )}

        {!loading &&
          items &&
          items.length > 0 &&
          filteredItems?.length === 0 && (
            <EmptyState
              icon={<StoreIcon className="h-6 w-6" />}
              title="No products from this store"
              description="Try a different store, or track a new product from Home."
            />
          )}

        {!loading &&
          filteredItems?.map((item) => (
            <ProductCard
              key={item.id}
              product={item}
              variant="tracked"
              onRefresh={() => handleRefreshOne(item)}
              onRemove={() => handleRemove(item)}
              refreshing={busyId === item.id && !refreshing}
              removing={busyId === item.id}
            />
          ))}
      </div>
    </>
  );
}

interface FilterChipProps {
  active: boolean;
  label: string;
  count: number;
  icon?: ReactNode;
  onClick: () => void;
}

function FilterChip({
  active,
  label,
  count,
  icon,
  onClick,
}: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-card text-foreground hover:bg-secondary",
      )}
    >
      {icon}
      {label}
      <span
        className={cn(
          "rounded-full px-1.5 text-xs",
          active
            ? "bg-primary-foreground/20"
            : "bg-secondary text-muted-foreground",
        )}
      >
        {count}
      </span>
    </button>
  );
}
