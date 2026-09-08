from dataclasses import dataclass, field


@dataclass
class ModuleSignal:
    """Tek bir modülün (OI, funding rate, likidasyon, emir defteri, hacim) ürettiği sinyal.

    direction: "LONG" | "SHORT" | None. None, modülün yön belirtmediği ama birikim/anomaliye
    işaret ettiği durumlar içindir (ör. Open Interest artışı — kendi başına yönsüzdür,
    diğer modüllerin belirlediği yönü güçlendirir).
    """

    triggered: bool
    score: float  # 0-100, bu modülün tetiklendiğindeki katkı gücü
    message: str
    direction: str | None = None


@dataclass
class TrapScoreResult:
    score: float  # 0-100, nihai Tuzak Skoru
    direction: str | None  # "LONG" | "SHORT" | None (hiçbir modül tetiklenmediyse)
    signals: dict[str, ModuleSignal] = field(default_factory=dict)
    regime: str = "normal"  # "normal" | "crisis" — TrapScorer'ın hangi ağırlık setini kullandığı
