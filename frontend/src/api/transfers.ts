import { apiClient } from "./client";

export type WalletType = "SPOT" | "USDM_FUTURES" | "FUNDING";

export interface Transfer {
  id: string;
  asset: string;
  amount: string;
  from_wallet: WalletType;
  to_wallet: WalletType;
  binance_tran_id: string | null;
  status: "PENDING" | "SUCCESS" | "FAILED";
  error_message: string | null;
  created_at: string;
}

export async function listTransfers(): Promise<Transfer[]> {
  const { data } = await apiClient.get<Transfer[]>("/transfers");
  return data;
}

export async function createTransfer(params: {
  credential_id?: string;
  asset: string;
  amount: string;
  from_wallet: WalletType;
  to_wallet: WalletType;
}): Promise<Transfer> {
  const { data } = await apiClient.post<Transfer>("/transfers", params);
  return data;
}
