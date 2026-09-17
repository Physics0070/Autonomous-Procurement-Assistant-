import * as React from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, ApiError, tokenStore } from "@/lib/api"
import type { AuthResponse, Organization, User } from "@/types"

interface AuthState {
  user: User | null
  organization: Organization | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => void
}

export interface RegisterPayload {
  name: string
  email: string
  password: string
  organization_name: string
  industry?: string
}

const AuthContext = React.createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const [hasToken, setHasToken] = React.useState(() => Boolean(tokenStore.get()))

  const { data, isLoading } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.get<{ user: User; organization: Organization }>("/auth/me"),
    enabled: hasToken,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  // A rejected token means the session is over; clear it rather than looping.
  const queryError = queryClient.getQueryState(["auth", "me"])?.error
  React.useEffect(() => {
    if (queryError instanceof ApiError && queryError.status === 401) {
      tokenStore.clear()
      setHasToken(false)
    }
  }, [queryError])

  const applySession = React.useCallback(
    (response: AuthResponse) => {
      tokenStore.set(response.access_token)
      setHasToken(true)
      queryClient.setQueryData(["auth", "me"], {
        user: response.user,
        organization: response.organization,
      })
    },
    [queryClient],
  )

  const loginMutation = useMutation({
    mutationFn: (vars: { email: string; password: string }) =>
      api.postPublic<AuthResponse>("/auth/login", vars),
    onSuccess: applySession,
  })

  const registerMutation = useMutation({
    mutationFn: (payload: RegisterPayload) => api.postPublic<AuthResponse>("/auth/register", payload),
    onSuccess: applySession,
  })

  const logout = React.useCallback(() => {
    tokenStore.clear()
    setHasToken(false)
    queryClient.clear()
  }, [queryClient])

  const value: AuthState = {
    user: data?.user ?? null,
    organization: data?.organization ?? null,
    isLoading: hasToken && isLoading,
    isAuthenticated: Boolean(data?.user),
    login: async (email, password) => {
      await loginMutation.mutateAsync({ email, password })
    },
    register: async (payload) => {
      await registerMutation.mutateAsync(payload)
    },
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = React.useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used inside AuthProvider")
  return context
}
