import { Skeleton } from "@/components/ui/skeleton";

export function ProductCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card">
      <div className="flex gap-4 p-4">
        <Skeleton className="h-28 w-28 rounded-xl" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="mt-2 h-7 w-24" />
          <Skeleton className="h-3 w-32" />
        </div>
      </div>
      <div className="border-t border-border px-4 py-3">
        <Skeleton className="h-10 w-full" />
      </div>
    </div>
  );
}
