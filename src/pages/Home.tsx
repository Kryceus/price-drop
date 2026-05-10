import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ExternalLink, Search, Sparkles } from "lucide-react";
import { AppHeader } from "@/components/layout/AppHeader";
import { ProductCard } from "@/components/ProductCard";
import { ProductCardSkeleton } from "@/components/ProductCardSkeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";
import { ApiError, products, type Product } from "@/lib/api";

const retailerLinks = [
  { name: "Woolworths", href: "https://www.woolworths.com.au/" },
  { name: "Coles", href: "https://www.coles.com.au/" },
  { name: "ALDI", href: "https://www.aldi.com.au/" },
  { name: "IGA", href: "https://www.igashop.com.au/" },
];

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
      if (!user) {
        toast.error(msg);
      } else {
        toast.message("Live check failed", {
          description: "Save this product and Price Drop will check it on the next scheduled run.",
          action: {
            label: "Save",
            onClick: async () => {
              try {
                await products.save(url.trim());
                toast.success("Saved for the next scheduled price check");
                navigate("/dashboard");
              } catch (saveErr) {
                toast.error(
                  saveErr instanceof ApiError ? saveErr.message : "Could not save",
                );
              }
            },
          },
        });
      }
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
            <div className="rounded-2xl border border-dashed border-border bg-card/50 px-5 py-8 text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary-soft text-primary">
                <Sparkles className="h-6 w-6" />
              </div>
              <h3 className="font-display text-lg font-semibold">Find a deal</h3>
              <ol className="mx-auto mt-3 max-w-sm space-y-1 text-left text-sm text-muted-foreground">
                <li>1. Open a supported store below.</li>
                <li>2. Copy the product page link.</li>
                <li>3. Paste it above and check the price.</li>
                <li>4. Save it to your dashboard to track changes.</li>
              </ol>
              <div className="mt-5 grid grid-cols-2 gap-2">
                {retailerLinks.map((retailer) => (
                  <Button
                    key={retailer.name}
                    asChild
                    variant="secondary"
                    size="sm"
                    className="gap-1.5"
                  >
                    <a href={retailer.href} target="_blank" rel="noreferrer">
                      {retailer.name}
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  </Button>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
