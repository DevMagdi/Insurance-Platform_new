/** Auth state: short-lived access token in memory + refresh cookie rotation (spec §6.2). */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, onUnauthorized, setAccessToken } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeOut"];
export type LoginIn = components["schemas"]["LoginIn"];

interface AuthValue {
  user: Me | null;
  ready: boolean;
  can: (permission: string) => boolean;
  canAny: (...permissions: string[]) => boolean;
  isManager: boolean;
  isPortal: boolean;
  login: (payload: LoginIn) => Promise<Me>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const queryClient = useQueryClient();

  const loadMe = useCallback(async () => {
    try {
      const refreshed = await api.post<components["schemas"]["RefreshOut"]>("/auth/refresh");
      setAccessToken(refreshed.access_token);
      const me = await api.get<Me>("/auth/me");
      setUser(me);
    } catch {
      setUser(null);
      setAccessToken(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

  useEffect(
    () =>
      onUnauthorized(() => {
        // A dead access token is normal mid-session: refresh once, otherwise sign out.
        void api
          .post<{ access_token: string }>("/auth/refresh")
          .then((refreshed) => setAccessToken(refreshed.access_token))
          .catch(() => {
            setUser(null);
            setAccessToken(null);
            queryClient.clear();
          });
      }),
    [queryClient],
  );

  const login = useCallback(
    async (payload: LoginIn) => {
      const result = await api.post<components["schemas"]["LoginOut"]>("/auth/login", payload);
      setAccessToken(result.access_token);
      setUser(result.user);
      setReady(true);
      return result.user;
    },
    [setUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setAccessToken(null);
      setUser(null);
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      ready,
      can: (permission: string) => Boolean(user?.permissions?.includes(permission)),
      canAny: (...permissions: string[]) => permissions.some((permission) => Boolean(user?.permissions?.includes(permission))),
      get isManager() {
        return Boolean(user?.permissions?.includes("leads.view_all"));
      },
      get isPortal() {
        return user?.role === "client_owner" || user?.role === "client_contact";
      },
      login,
      logout,
    }),
    [user, ready, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
