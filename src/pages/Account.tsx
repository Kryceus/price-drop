import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AppHeader } from "@/components/layout/AppHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/lib/api";
import { Bell, LogOut, Smartphone, User as UserIcon } from "lucide-react";

export default function Account() {
  const { user, loading, login, signup, logout } = useAuth();
  const [authBusy, setAuthBusy] = useState(false);
  const [emailNotify, setEmailNotify] = useState(true);
  const [pushNotify, setPushNotify] = useState(false);

  const [li, setLi] = useState({ identifier: "", password: "" });
  const [su, setSu] = useState({
    username: "",
    email: "",
    password: "",
    first_name: "",
    last_name: "",
  });

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setAuthBusy(true);
    try {
      await login(li.identifier.trim(), li.password);
      toast.success("Welcome back");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not sign in");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setAuthBusy(true);
    try {
      await signup({
        username: su.username.trim(),
        password: su.password,
        confirm_password: su.password,
        email: su.email.trim() || undefined,
        first_name: su.first_name.trim() || undefined,
        last_name: su.last_name.trim() || undefined,
      });
      toast.success("Account created");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not sign up");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleLogout() {
    await logout();
    toast.success("Signed out");
  }

  if (loading) {
    return (
      <>
        <AppHeader title="Account" />
        <div className="px-4 pt-4 text-sm text-muted-foreground">Loading...</div>
      </>
    );
  }

  if (user) {
    const fullName =
      [user.first_name, user.last_name].filter(Boolean).join(" ") ||
      user.username;

    return (
      <>
        <AppHeader title="Account" />
        <div className="space-y-4 px-4 pt-4">
          <Card className="shadow-card">
            <CardContent className="flex items-center gap-4 p-5">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary-soft text-primary">
                <UserIcon className="h-6 w-6" />
              </div>
              <div className="min-w-0">
                <p className="truncate font-display text-lg font-semibold">
                  {fullName}
                </p>
                <p className="truncate text-sm text-muted-foreground">
                  {user.email ?? `@${user.username}`}
                </p>
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-card">
            <CardContent className="divide-y divide-border p-0">
              <div className="flex items-center justify-between gap-4 p-4">
                <div className="flex items-center gap-3">
                  <Bell className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">Email price drops</p>
                    <p className="text-xs text-muted-foreground">Coming soon</p>
                  </div>
                </div>
                <Switch
                  checked={emailNotify}
                  onCheckedChange={setEmailNotify}
                  disabled
                />
              </div>
              <div className="flex items-center justify-between gap-4 p-4">
                <div className="flex items-center gap-3">
                  <Smartphone className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">Push notifications</p>
                    <p className="text-xs text-muted-foreground">Coming soon</p>
                  </div>
                </div>
                <Switch
                  checked={pushNotify}
                  onCheckedChange={setPushNotify}
                  disabled
                />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-card">
            <CardContent className="space-y-2 p-4">
              <Link to="/install" className="block text-sm font-medium text-primary">
                Install on your phone
              </Link>
              <p className="text-xs text-muted-foreground">App version 1.0.0</p>
            </CardContent>
          </Card>

          <Button
            variant="outline"
            onClick={handleLogout}
            className="w-full gap-2"
            size="lg"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <AppHeader title="Account" subtitle="Sign in to sync your dashboard" />
      <div className="px-4 pt-4">
        <Tabs defaultValue="login" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login">Sign in</TabsTrigger>
            <TabsTrigger value="signup">Create account</TabsTrigger>
          </TabsList>

          <TabsContent value="login">
            <form
              onSubmit={handleLogin}
              className="space-y-4 rounded-2xl border border-border bg-card p-4 shadow-card"
            >
              <div className="space-y-1.5">
                <Label htmlFor="li-username">Username or email</Label>
                <Input
                  id="li-username"
                  autoComplete="username"
                  value={li.identifier}
                  onChange={(e) =>
                    setLi({ ...li, identifier: e.target.value })
                  }
                  className="h-12"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="li-password">Password</Label>
                <Input
                  id="li-password"
                  type="password"
                  autoComplete="current-password"
                  value={li.password}
                  onChange={(e) => setLi({ ...li, password: e.target.value })}
                  className="h-12"
                  required
                />
              </div>
              <Button
                type="submit"
                disabled={authBusy}
                size="lg"
                className="w-full"
              >
                {authBusy ? "Signing in..." : "Sign in"}
              </Button>
            </form>
          </TabsContent>

          <TabsContent value="signup">
            <form
              onSubmit={handleSignup}
              className="space-y-4 rounded-2xl border border-border bg-card p-4 shadow-card"
            >
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="su-first">First name</Label>
                  <Input
                    id="su-first"
                    value={su.first_name}
                    onChange={(e) =>
                      setSu({ ...su, first_name: e.target.value })
                    }
                    className="h-12"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="su-last">Last name</Label>
                  <Input
                    id="su-last"
                    value={su.last_name}
                    onChange={(e) =>
                      setSu({ ...su, last_name: e.target.value })
                    }
                    className="h-12"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="su-username">Username</Label>
                <Input
                  id="su-username"
                  autoComplete="username"
                  value={su.username}
                  onChange={(e) => setSu({ ...su, username: e.target.value })}
                  className="h-12"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="su-email">Email (optional)</Label>
                <Input
                  id="su-email"
                  type="email"
                  autoComplete="email"
                  value={su.email}
                  onChange={(e) => setSu({ ...su, email: e.target.value })}
                  className="h-12"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="su-password">Password</Label>
                <Input
                  id="su-password"
                  type="password"
                  autoComplete="new-password"
                  value={su.password}
                  onChange={(e) => setSu({ ...su, password: e.target.value })}
                  className="h-12"
                  required
                  minLength={6}
                />
              </div>
              <Button
                type="submit"
                disabled={authBusy}
                size="lg"
                className="w-full"
              >
                {authBusy ? "Creating account..." : "Create account"}
              </Button>
            </form>
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
