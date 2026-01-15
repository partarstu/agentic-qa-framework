import axios, { type AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';

const AUTH_TOKEN_KEY = 'dashboard_auth_token';

// Event emitter for connection status
type ConnectionStatusHandler = (isOnline: boolean) => void;
const handlers: Set<ConnectionStatusHandler> = new Set();

// Event emitter for auth status
type AuthStatusHandler = (isAuthenticated: boolean) => void;
const authHandlers: Set<AuthStatusHandler> = new Set();

export const onConnectionStatusChange = (handler: ConnectionStatusHandler) => {
  handlers.add(handler);
  return () => { handlers.delete(handler); };
};

export const onAuthStatusChange = (handler: AuthStatusHandler) => {
  authHandlers.add(handler);
  return () => { authHandlers.delete(handler); };
};

const notifyHandlers = (isOnline: boolean) => {
  handlers.forEach(handler => handler(isOnline));
};

const notifyAuthHandlers = (isAuthenticated: boolean) => {
  authHandlers.forEach(handler => handler(isAuthenticated));
};

// Create axios instance
export const apiClient = axios.create({
  baseURL: '/api/dashboard',
  timeout: 5000, // 5 seconds timeout
});

// Request interceptor to add auth token
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor to handle connection status and auth errors
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // If we get a response, the backend is arguably online
    notifyHandlers(true);
    return response;
  },
  (error: AxiosError) => {
    console.error('API Error intercepted:', error.code, error.message, error.response?.status);
    
    // Handle 401 Unauthorized - token expired or invalid
    if (error.response?.status === 401) {
      // Clear auth data and notify listeners
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem('dashboard_auth_expires');
      localStorage.removeItem('dashboard_auth_username');
      notifyAuthHandlers(false);
      return Promise.reject(error);
    }
    
    // Check for timeout explicitly
    if (error.code === 'ECONNABORTED') {
      console.log('Request timeout -> Offline');
      notifyHandlers(false);
      return Promise.reject(error);
    }

    if (!error.response) {
      // Network error (server likely down or unreachable)
      console.log('Network error detected -> Offline');
      notifyHandlers(false);
    } else if (error.response.status >= 500) {
      // Server error (server reachable but broken)
      // Including 500 because the Vite proxy often returns 500 when the target is unreachable (ECONNREFUSED)
      if ([500, 502, 503, 504].includes(error.response.status)) {
         console.log('Server/Gateway error detected -> Offline');
         notifyHandlers(false);
      } else {
         // Other errors (4xx, 500) mean backend is there but processing failed
         notifyHandlers(true);
      }
    } else {
      // Client error (4xx) means backend is online
      notifyHandlers(true);
    }
    return Promise.reject(error);
  }
);

