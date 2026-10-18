"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  api,
  clearAccessToken,
  setAccessToken,
  type ServiceResponse,
} from "@/lib/api-client";


// ============================================================
// TYPES
// ============================================================

export interface AuthUser {
  id: string;
  full_name: string;
  email: string;
  account_status: string;
  created_at?: string;
  updated_at?: string;
}

interface LoginData {
  user: AuthUser;
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  refresh_expires_at?: string;
  session_id?: string;
}

interface UserData {
  user: AuthUser;
}

interface RegisterInput {
  full_name: string;
  email: string;
  password: string;
}

interface LoginInput {
  email: string;
  password: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;

  login: (input: LoginInput) => Promise<AuthUser>;
  register: (input: RegisterInput) => Promise<AuthUser>;
  logout: () => Promise<void>;
  reloadUser: () => Promise<AuthUser>;
  updateUser: (user: AuthUser) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
);


// ============================================================
// AUTH PROVIDER
// ============================================================

export function AuthProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // ----------------------------------------------------------
  // RESTORE SESSION ON PAGE LOAD
  // ----------------------------------------------------------

  useEffect(() => {
    let cancelled = false;

    async function initializeSession() {
      try {
        const restored = await api.restoreSession();

        if (!restored) {
          clearAccessToken();

          if (!cancelled) {
            setUser(null);
          }

          return;
        }

        const response =
          await api.get<UserData>("accounts/me");

        const currentUser = response.outputs.data?.user;

        if (!currentUser) {
          throw new Error(
            "The API did not return the authenticated user.",
          );
        }

        if (!cancelled) {
          setUser(currentUser);
        }
      } catch {
        clearAccessToken();

        if (!cancelled) {
          setUser(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void initializeSession();

    return () => {
      cancelled = true;
    };
  }, []);

  // ----------------------------------------------------------
  // LOGIN
  // ----------------------------------------------------------

  const login = useCallback(
    async (input: LoginInput): Promise<AuthUser> => {
      const response =
        await api.post<LoginData>("auth/login", input);

      const data = response.outputs.data;

      if (!data?.user || !data.access_token) {
        clearAccessToken();

        throw new Error(
          "Login succeeded without returning the required session data.",
        );
      }

      setAccessToken(data.access_token);
      setUser(data.user);

      return data.user;
    },
    [],
  );

  // ----------------------------------------------------------
  // REGISTER
  // ----------------------------------------------------------

  const register = useCallback(
    async (input: RegisterInput): Promise<AuthUser> => {
      const response =
        await api.post<UserData>("auth/register", input);

      const registeredUser = response.outputs.data?.user;

      if (!registeredUser) {
        throw new Error(
          "Registration did not return the created account.",
        );
      }

      // Registration does not automatically authenticate
      // the new user. The user must log in separately.
      return registeredUser;
    },
    [],
  );

  // ----------------------------------------------------------
  // LOGOUT
  // ----------------------------------------------------------

  const logout = useCallback(async (): Promise<void> => {
    try {
      await api.post("auth/logout");
    } finally {
      // Clear local authentication state even when the
      // server cannot be reached.
      clearAccessToken();
      setUser(null);
    }
  }, []);

  // ----------------------------------------------------------
  // RELOAD CURRENT USER
  // ----------------------------------------------------------

  const reloadUser = useCallback(
    async (): Promise<AuthUser> => {
      const response =
        await api.get<UserData>("accounts/me");

      const currentUser = response.outputs.data?.user;

      if (!currentUser) {
        throw new Error(
          "Unable to retrieve the current user profile.",
        );
      }

      setUser(currentUser);

      return currentUser;
    },
    [],
  );

  // ----------------------------------------------------------
  // UPDATE LOCAL USER AFTER PROFILE EDITS
  // ----------------------------------------------------------

  const updateUser = useCallback((updatedUser: AuthUser) => {
    setUser(updatedUser);
  }, []);

  // ----------------------------------------------------------
  // CONTEXT VALUE
  // ----------------------------------------------------------

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: user !== null,
      login,
      register,
      logout,
      reloadUser,
      updateUser,
    }),
    [
      user,
      isLoading,
      login,
      register,
      logout,
      reloadUser,
      updateUser,
    ],
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}


// ============================================================
// AUTH HOOK
// ============================================================

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error(
      "useAuth must be used inside an AuthProvider.",
    );
  }

  return context;
}