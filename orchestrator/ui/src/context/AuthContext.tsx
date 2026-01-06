import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { authApi, type TokenResponse } from '../api/authApi';

const AUTH_TOKEN_KEY = 'dashboard_auth_token';
const AUTH_EXPIRES_KEY = 'dashboard_auth_expires';
const AUTH_USERNAME_KEY = 'dashboard_auth_username';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  token: string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => 
    localStorage.getItem(AUTH_TOKEN_KEY)
  );
  const [username, setUsername] = useState<string | null>(() =>
    localStorage.getItem(AUTH_USERNAME_KEY)
  );
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!token;

  // Check if token is expired
  const isTokenExpired = useCallback(() => {
    const expiresAt = localStorage.getItem(AUTH_EXPIRES_KEY);
    if (!expiresAt) return true;
    return new Date(expiresAt) <= new Date();
  }, []);

  // Verify token on mount
  useEffect(() => {
    const verifyAuth = async () => {
      if (!token) {
        setIsLoading(false);
        return;
      }

      if (isTokenExpired()) {
        // Token expired, clear auth state
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_EXPIRES_KEY);
        localStorage.removeItem(AUTH_USERNAME_KEY);
        setToken(null);
        setUsername(null);
        setIsLoading(false);
        return;
      }

      try {
        const response = await authApi.verify();
        setUsername(response.username);
        setIsLoading(false);
      } catch {
        // Token is invalid, clear auth state
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_EXPIRES_KEY);
        localStorage.removeItem(AUTH_USERNAME_KEY);
        setToken(null);
        setUsername(null);
        setIsLoading(false);
      }
    };

    verifyAuth();
  }, [token, isTokenExpired]);

  const login = useCallback(async (loginUsername: string, password: string) => {
    const response: TokenResponse = await authApi.login({ 
      username: loginUsername, 
      password 
    });
    
    localStorage.setItem(AUTH_TOKEN_KEY, response.access_token);
    localStorage.setItem(AUTH_EXPIRES_KEY, response.expires_at);
    localStorage.setItem(AUTH_USERNAME_KEY, loginUsername);
    
    setToken(response.access_token);
    setUsername(loginUsername);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_EXPIRES_KEY);
    localStorage.removeItem(AUTH_USERNAME_KEY);
    setToken(null);
    setUsername(null);
    
    // Best effort to call logout endpoint
    authApi.logout().catch(() => {});
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, username, login, logout, token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export { AUTH_TOKEN_KEY };
