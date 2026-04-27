import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { auth, type User } from "@/lib/api";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (identifier: string, password: string) => Promise<void>;
  signup: (payload: {
    username: string;
    password: string;
    confirm_password: string;
    email?: string;
    first_name?: string;
    last_name?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { user } = await auth.me();
      setUser(user);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(async (identifier: string, password: string) => {
    const { user } = await auth.login({ identifier, password });
    setUser(user);
  }, []);

  const signup = useCallback(
    async (payload: {
      username: string;
      password: string;
      confirm_password: string;
      email?: string;
      first_name?: string;
      last_name?: string;
    }) => {
      const { user } = await auth.signup(payload);
      setUser(user);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, refresh, login, signup, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
