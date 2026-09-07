import { apiClient } from "./client";

export interface AssetBalance {
  asset: string;
  free: number;
  locked: number;
}

export interface FuturesBalance {
  asset: string;
  wallet_balance: number;
  available_balance: number;
  unrealized_profit: number;
}

export interface WalletSummary {
  credential_id: string;
  credential_label: string;
  spot: AssetBalance[];
  futures: FuturesBalance[];
  funding: AssetBalance[];
}

export async function fetchBalances(credentialId?: string): Promise<WalletSummary> {
  const { data } = await apiClient.get<WalletSummary>("/wallet/balances", {
    params: credentialId ? { credential_id: credentialId } : undefined,
  });
  return data;
}
