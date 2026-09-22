from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def make_info_label(text: str = "") -> QLabel:
    """Bilgi içerikli (ipucu/özet/durum) metinler için ortak QLabel kurucusu:
    fare ile seçilip Ctrl+C veya sağ tık menüsüyle kopyalanabilsin diye
    TextSelectableByMouse bayrağı açıktır (normal bir QLabel varsayılan
    olarak seçilemez/kopyalanamaz)."""
    label = QLabel(text)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
