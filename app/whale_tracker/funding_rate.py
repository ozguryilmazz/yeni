from app.whale_tracker.models import ModuleSignal


class FundingRateAnomalyModule:
    """Modül B — Funding Rate (Fonlama Oranı) Anomali Modülü.

    Binance Futures'ın GET /fapi/v1/premiumIndex ile alınan `lastFundingRate` değerini
    değerlendirir. Bu değer ondalık bir orandır (0.0001 = %0.01), yüzde değil.

    - Funding Rate çok negatifse (< short_squeeze_threshold, ör. -%0.03): piyasa aşırı
      short ağırlıklı demektir — short'lar fonlama ödüyor, bu da bir Long Squeeze
      (short'ların zorla kapanıp fiyatı yukarı itmesi) ihtimalini artırır → LONG sinyali.
    - Funding Rate çok pozitifse (> long_squeeze_threshold, ör. +%0.05): piyasa aşırı
      long ağırlıklı demektir → Short Squeeze ihtimali → SHORT sinyali.
    """

    def __init__(
        self,
        short_squeeze_threshold: float = -0.0003,  # -%0.03
        long_squeeze_threshold: float = 0.0005,  # +%0.05
    ) -> None:
        self.short_squeeze_threshold = short_squeeze_threshold
        self.long_squeeze_threshold = long_squeeze_threshold

    def evaluate(self, funding_rate: float) -> ModuleSignal:
        if funding_rate <= self.short_squeeze_threshold:
            return ModuleSignal(
                True,
                100,
                f"Funding Rate %{funding_rate * 100:+.4f} — aşırı short ağırlıklı (Long Squeeze ihtimali)",
                direction="LONG",
            )
        if funding_rate >= self.long_squeeze_threshold:
            return ModuleSignal(
                True,
                100,
                f"Funding Rate %{funding_rate * 100:+.4f} — aşırı long ağırlıklı (Short Squeeze ihtimali)",
                direction="SHORT",
            )
        return ModuleSignal(False, 0, f"Funding Rate %{funding_rate * 100:+.4f} normal aralıkta")
