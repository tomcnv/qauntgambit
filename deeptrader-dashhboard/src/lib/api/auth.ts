import { apiRequest } from "./http";

export type ViewerScope = {
  botId: string;
  botName?: string | null;
  exchangeAccountId: string;
  exchangeAccountName?: string | null;
  allowedBotIds?: string[];
};

export type AuthUser = {
  id: string;
  tenantId?: string;
  parentUserId?: string | null;
  email: string;
  username: string;
  firstName?: string | null;
  lastName?: string | null;
  role?: string | null;
  viewerScope?: ViewerScope | null;
  createdAt?: string;
  lastLogin?: string | null;
};

type AuthResponse = {
  message?: string;
  user: AuthUser;
  token: string;
};

export const login = (payload: { email: string; password: string }) =>
  apiRequest<AuthResponse>("/auth/login", { method: "POST", data: payload });

export const register = (payload: {
  email: string;
  username: string;
  password: string;
  firstName?: string;
  lastName?: string;
}) => apiRequest<AuthResponse>("/auth/register", { method: "POST", data: payload });

export const getProfile = (token: string) =>
  apiRequest<{ user: AuthUser }>("/auth/me", { token });

export const logout = (token: string) =>
  apiRequest<{ message: string }>("/auth/logout", { method: "POST", token });






