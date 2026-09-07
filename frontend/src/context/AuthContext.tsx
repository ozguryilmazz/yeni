import { createContext, ReactNode, useContext, useEffect, useState } from "react";

import { apiClient, tokenStorage } from "../api/client";

interface AuthUser {
  id: string;
  email: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCurrentUser = async () => {
    try {
      const { data } = await apiClient.get<AuthUser>("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (tokenStorage.getAccessToken()) {
      fetchCurrentUser();
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const { data } = await apiClient.post("/auth/login", { email, password });
    tokenStorage.setTokens(data.access_token, data.refresh_token);
    await fetchCurrentUser();
  };

  const register = async (email: string, password: string) => {
    const { data } = await apiClient.post("/auth/register", { email, password });
    tokenStorage.setTokens(data.access_token, data.refresh_token);
    await fetchCurrentUser();
  };

  const logout = () => {
    tokenStorage.clear();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth, AuthProvider içinde kullanılmalı");
  }
  return context;
}
