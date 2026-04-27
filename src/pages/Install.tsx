import { Link } from "react-router-dom";
import { Apple, ArrowLeft, Smartphone } from "lucide-react";
import { AppHeader } from "@/components/layout/AppHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function Install() {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader
        title="Install PriceCompare"
        action={
          <Button asChild variant="ghost" size="sm">
            <Link to="/" className="gap-1">
              <ArrowLeft className="h-4 w-4" /> Back
            </Link>
          </Button>
        }
      />
      <div className="mx-auto max-w-xl space-y-4 px-4 py-4">
        <p className="text-sm text-muted-foreground">
          Add PriceCompare to your home screen for an app-like experience with
          no app store required.
        </p>

        <Card className="shadow-card">
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-soft text-primary">
                <Apple className="h-5 w-5" />
              </div>
              <h2 className="font-display text-lg font-semibold">
                iPhone &amp; iPad
              </h2>
            </div>
            <ol className="ml-1 list-decimal space-y-1.5 pl-5 text-sm text-foreground">
              <li>
                Open this site in <strong>Safari</strong>.
              </li>
              <li>
                Tap the <strong>Share</strong> button.
              </li>
              <li>
                Scroll and tap <strong>Add to Home Screen</strong>.
              </li>
              <li>
                Tap <strong>Add</strong> in the top-right corner.
              </li>
            </ol>
          </CardContent>
        </Card>

        <Card className="shadow-card">
          <CardContent className="space-y-3 p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-soft text-primary">
                <Smartphone className="h-5 w-5" />
              </div>
              <h2 className="font-display text-lg font-semibold">Android</h2>
            </div>
            <ol className="ml-1 list-decimal space-y-1.5 pl-5 text-sm text-foreground">
              <li>
                Open this site in <strong>Chrome</strong>.
              </li>
              <li>
                Tap the browser menu in the top-right.
              </li>
              <li>
                Tap <strong>Install app</strong> or{" "}
                <strong>Add to Home screen</strong>.
              </li>
              <li>
                Confirm with <strong>Install</strong>.
              </li>
            </ol>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
