import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Search, Sparkles } from "lucide-react";
import { AppHeader } from "@/components/layout/AppHeader";
import { EmptyState } from "@/components/EmptyState";
import { ProductCard } from "@/components/ProductCard";
import { ProductCardSkeleton } from "@/components/ProductCardSkeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";
import { ApiError, products, type Product } from "@/lib/api";

export default function Home() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [product, setProduct] = useState<Product | null>(null);
  const { user } = useAuth();
  const navigate = useNavigate();

  async function handleCheck(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) {
      return;
    }

    setLoading(true);
    setProduct(null);
    try {
      const { product } = await products.preview(url.trim());
      setProduct(product);
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "Could not fetch product";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!product) {
      return;
    }

    if (!user) {
      toast.message("Sign in to save products", {
        action: { label: "Sign in", onClick: () => navigate("/account") },
      });
      return;
    }

    setSaving(true);
    try {
      await products.savePreview(product);
      toast.success("Saved to your dashboard");
      navigate("/dashboard");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <AppHeader title="Track a price" subtitle="Paste any product URL" />
      <div className="space-y-5 px-4 pt-4">
        <form
          onSubmit={handleCheck}
          className="space-y-3 rounded-2xl border border-border bg-card p-4 shadow-card"
        >
          <Label htmlFor="product-url" className="font-display text-sm">
            Product URL
          </Label>
          <div className="flex gap-2">
            <Input
              id="product-url"
              type="url"
              inputMode="url"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              placeholder="https://www.woolworths.com.au/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="h-12 text-base"
            />
          </div>
          <Button
            type="submit"
            disabled={loading || !url.trim()}
            size="lg"
            className="w-full gap-2"
          >
            <Search className="h-4 w-4" />
            {loading ? "Checking..." : "Check Price"}
          </Button>
        </form>

        <section className="space-y-3">
          {loading && <ProductCardSkeleton />}
          {!loading && product && (
            <ProductCard
              product={product}
              variant="preview"
              onSave={handleSave}
              saving={saving}
            />
          )}
          {!loading && !product && (
            <EmptyState
              icon={<Sparkles className="h-6 w-6" />}
              title="Find a deal"
              description="Paste a product link from Woolworths or another supported store to see its current price, then save it to track changes."
            />
          )}
        </section>
      </div>
    </>
  );
}
