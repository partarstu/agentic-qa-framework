import { apiClient } from './client';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface VerifyResponse {
  valid: boolean;
  username: string;
}

/**
 * Authentication API client.
 */
export const authApi = {
  /**
   * Login with username and password.
   */
  async login(credentials: LoginRequest): Promise<TokenResponse> {
    // Use axios directly without baseURL since auth endpoints are at /api/auth
    const response = await apiClient.post<TokenResponse>('/auth/login', credentials, {
      baseURL: '/api',
    });
    return response.data;
  },

  /**
   * Logout (client-side token removal).
   */
  async logout(): Promise<void> {
    await apiClient.post('/auth/logout', {}, {
      baseURL: '/api',
    });
  },

  /**
   * Verify if the current token is valid.
   */
  async verify(): Promise<VerifyResponse> {
    const response = await apiClient.get<VerifyResponse>('/auth/verify', {
      baseURL: '/api',
    });
    return response.data;
  },
};
