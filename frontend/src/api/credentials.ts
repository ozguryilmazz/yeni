import { apiClient } from "./client";

export interface Credential {
  id: string;
  label: string;
  can_withdraw: boolean;
  permissions_verified_at: string | null;
  created_at: string;
}

export async function listCredentials(): Promise<Credential[]> {
  const { data } = await apiClient.get<Credential[]>("/credentials");
  return data;
}

export async function connectCredential(params: {
  label: string;
  api_key: string;
  api_secret: string;
}): Promise<Credential> {
  const { data } = await apiClient.post<Credential>("/credentials", params);
  return data;
}

export async function deleteCredential(id: string): Promise<void> {
  await apiClient.delete(`/credentials/${id}`);
}
