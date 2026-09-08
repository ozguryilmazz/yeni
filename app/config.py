import os
import platform
from pathlib import Path

APP_NAME = "BinanceWalletManager"


def get_app_data_dir() -> Path:
    """İşletim sistemine uygun kullanıcı veri dizinini döner ve gerekirse oluşturur.

    Testlerde izolasyon için BINANCE_APP_DATA_DIR ortam değişkeni ile geçersiz kılınabilir.
    """
    override = os.environ.get("BINANCE_APP_DATA_DIR")
    if override:
        data_dir = Path(override)
    else:
        system = platform.system()
        if system == "Windows":
            base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        elif system == "Darwin":
            base = str(Path.home() / "Library" / "Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        data_dir = Path(base) / APP_NAME

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_database_path() -> Path:
    return get_app_data_dir() / "app.db"
