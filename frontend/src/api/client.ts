import axios from "axios";

const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";

export const tokenStorage = {
  getAccessToken: () => localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefreshToken: () => localStorage.getItem(REFRESH_TOKEN_KEY),
  setTokens: (accessToken: string, refreshToken: string) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};

export const apiClient = axios.create({ baseURL: "/api" });

apiClient.interceptors.request.use((config) => {
  const token = tokenStorage.getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let pendingRequests: Array<() => void> = [];

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) {
      tokenStorage.clear();
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    if (isRefreshing) {
      return new Promise((resolve) => {
        pendingRequests.push(() => resolve(apiClient(originalRequest)));
      });
    }

    isRefreshing = true;
    try {
      const { data } = await axios.post("/api/auth/refresh", { refresh_token: refreshToken });
      tokenStorage.setTokens(data.access_token, data.refresh_token);
      pendingRequests.forEach((cb) => cb());
      pendingRequests = [];
      return apiClient(originalRequest);
    } catch (refreshError) {
      tokenStorage.clear();
      pendingRequests = [];
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  },
);
