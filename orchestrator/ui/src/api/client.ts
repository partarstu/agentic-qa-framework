import axios, { type AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';

// Event emitter for connection status
type ConnectionStatusHandler = (isOnline: boolean) => void;
const handlers: Set<ConnectionStatusHandler> = new Set();

export const onConnectionStatusChange = (handler: ConnectionStatusHandler) => {
  handlers.add(handler);
  return () => { handlers.delete(handler); };
};

const notifyHandlers = (isOnline: boolean) => {
  handlers.forEach(handler => handler(isOnline));
};

// Create axios instance
export const apiClient = axios.create({
  baseURL: '/api/dashboard',
  timeout: 5000, // 5 seconds timeout
});

// Request interceptor to clean up config if needed
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  return config;
});

// Response interceptor to handle connection status
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // If we get a response, the backend is arguably online
    notifyHandlers(true);
    return response;
  },
  (error: AxiosError) => {
    console.error('API Error intercepted:', error.code, error.message, error.response?.status);
    
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
