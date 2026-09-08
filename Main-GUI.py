"""
MiniLens - Visor de kubeconfig con hotbar, SQLite y vista grafica de Pods/Services.

Layout:
  [Hotbar] | [Top: drag&drop + metadatos + import panel]
           | [Splitter: Clusters+Contexts | Detalle/Mapa]
           | [Users]

Incluye:
- Hotbar con clusters anclados (estilo OpenLens)
- Base de datos SQLite para guardar kubeconfigs y clusters
- Drag & drop de archivos kubeconfig
- Vista de Lista y Mapa grafico
- Tema negro/amarillo

Uso:
    python verificar_config_kubeconfig-GUI.py
"""

import os
import sys
import shutil
import socket
import ssl
import traceback
import tempfile
import warnings
from datetime import datetime, timezone
from urllib.parse import urlparse

import yaml
import json
import queue
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

# 1 - SILENCIO LOS WARNINGS DE urllib3 PARA CLUSTERS CON insecure-skip-tls:
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# 1b - SILENCIO EL LOGGER DE KUBERNETES (evita ERROR:root:'NoneType'...):
import logging
logging.getLogger("kubernetes").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

# 1c - LOG A ARCHIVO (minilens.log junto al script): aca quedan los errores
#      de Python Y los crashes duros, para poder diagnosticar despues:
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minilens.log")
_log = logging.getLogger("minilens")
_log.setLevel(logging.INFO)
try:
    _log_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _log_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _log.addHandler(_log_fh)
    _log.info("=== MiniLens arranco ===")
except Exception:
    pass

# 1d - FAULTHANDLER: si la app muere a nivel C++ (segfault de Qt/PySide),
#      deja el traceback en el mismo archivo ANTES de morir:
try:
    import faulthandler
    faulthandler.enable(open(LOG_FILE, "a", encoding="utf-8"))
except Exception:
    pass

# 1e - EXCEPTHOOK: cualquier excepcion no capturada queda en el archivo:
def _sys_excepthook(t, v, tb):
    try:
        _log.error("EXCEPCION NO CAPTURADA:\n%s", "".join(traceback.format_exception(t, v, tb)))
    except Exception:
        pass
    try:
        sys.__stderr__.write("".join(traceback.format_exception(t, v, tb)))
    except Exception:
        pass
sys.excepthook = _sys_excepthook

from database import db as dbmod
from PySide6.QtWidgets import (
    QApplication,
    QAbstractScrollArea,
    QAbstractItemView,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QGroupBox,
    QFormLayout,
    QSplitter,
    QFrame,
    QSizePolicy,
    QTabWidget,
    QScrollArea,
    QTextEdit,
    QDialog,
    QGridLayout,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QColorDialog,
    QButtonGroup,
    QComboBox,
    QRadioButton,
    QCheckBox,
)
from PySide6.QtCore import Qt, QPoint, QRect, QSize, QMimeData, QObject, QRunnable, QThreadPool, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QDrag, QDragEnterEvent, QDropEvent, QColor, QPalette, QGuiApplication, QPainter, QBrush, QPen, QFontMetrics
import random
import colorsys


# 1 - RUTA AL KUBECONFIG DEL USUARIO (~/.kube/config):
USER_KUBECONFIG = os.path.join(os.path.expanduser("~"), ".kube", "config")

# 3 - TEMA NEGRO/AMARILLO (QSS):
STYLESHEET = """
QMainWindow {
    background-color: #1a1a1a;
}
QWidget {
    color: #e0e0e0;
    font-size: 14px;
}
QGroupBox {
    border: 2px solid #f5c518;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    font-size: 13px;
    font-weight: bold;
    color: #f5c518;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    background-color: #f5c518;
    color: #1a1a1a;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #ffd633;
}
QPushButton:pressed {
    background-color: #cc9900;
}
QListWidget {
    background-color: #232323;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    font-size: 14px;
    padding: 4px;
}
QListWidget::item {
    padding: 2px;
    border-radius: 6px;
    margin: 1px 2px;
}
QListWidget::item:hover {
    background-color: #333333;
}
QListWidget::item:selected {
    background-color: #3d3320;
    border-left: 3px solid #f5c518;
    color: #f5f5f5;
    font-weight: bold;
}
QTableWidget {
    background-color: #2a2a2a;
    border: 1px solid #444;
    border-radius: 4px;
    font-size: 14px;
    gridline-color: #444;
}
QTableWidget::item {
    padding: 4px;
}
QHeaderView::section {
    background-color: #f5c518;
    color: #1a1a1a;
    font-weight: bold;
    border: none;
    padding: 6px;
}
QLabel {
    color: #e0e0e0;
    font-size: 14px;
}
QLabel#dropzone {
    border: 3px dashed #f5c518;
    border-radius: 8px;
    background-color: #2a2a2a;
    color: #f5c518;
    font-size: 18px;
    font-weight: bold;
    padding: 30px;
    qproperty-alignment: AlignCenter;
}
QLabel#dropzone:hover {
    border-color: #ffd633;
    background-color: #333;
}
QLabel#status {
    color: #f5c518;
    font-size: 15px;
    font-weight: bold;
    padding: 8px;
}
QLabel#help {
    color: #aaa;
    font-size: 13px;
    font-style: italic;
    padding: 4px 8px;
}
QLabel#detail_value {
    color: #f5c518;
    font-size: 15px;
    font-weight: bold;
}
QFrame#service_card {
    background-color: #2a2a2a;
    border: 2px solid #f5c518;
    border-radius: 10px;
    padding: 8px;
}
QFrame#service_card:hover {
    border-color: #ffd633;
    background-color: #333;
}
QFrame#pod_row {
    background-color: #222;
    border: 1px solid #555;
    border-radius: 6px;
    padding: 4px;
}
QLabel#status_dot {
    font-size: 16px;
    min-width: 18px;
}
QTabWidget::pane {
    border: 1px solid #444;
    background-color: #1a1a1a;
}
QTabBar::tab {
    background-color: #2a2a2a;
    color: #e0e0e0;
    padding: 8px 16px;
    border: 1px solid #444;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #f5c518;
    color: #1a1a1a;
    font-weight: bold;
}
QFrame#hotbar {
    background-color: #1e2126;
    border-right: 1px solid #333;
}
QFrame#hotbar_item {
    border-radius: 10px;
    max-width: 44px;
    min-width: 44px;
    max-height: 44px;
    min-height: 44px;
}
QFrame#hotbar_item:hover {
    border: 2px solid rgba(255,255,255,0.4);
}
QFrame#hotbar_item_selected {
    border: 2px solid #ffffff;
    border-radius: 10px;
    max-width: 44px;
    min-width: 44px;
    max-height: 44px;
    min-height: 44px;
}
QFrame#hotbar_slot_empty {
    background-color: #2a2d33;
    border-radius: 10px;
    max-width: 44px;
    min-width: 44px;
    max-height: 44px;
    min-height: 44px;
}
QFrame#import_cluster_row {
    background-color: #2a2a2a;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 4px;
}
"""


# 4 - ICONOS (usando emojis como texto, compatibles con Windows):
ICON_CLUSTER = "\U0001F310"   # 🌐
ICON_CONTEXT = "\U0001F511"   # 🔑
ICON_USER    = "\U0001F464"   # 👤
ICON_DETAIL  = "\U0001F4CB"   # 📋
ICON_POD     = "\U0001F4E6"   # 📦
ICON_FILE    = "\U0001F4C1"   # 📁
ICON_WARN    = "\u26A0\uFE0F" # ⚠️
ICON_OK      = "\u2705"       # ✅
ICON_INFO    = "\u2139\uFE0F" # ℹ️
ICON_SERVER  = "\U0001F5A5"   # 🖥
ICON_DOCKER  = "\U0001F433"   # 🐳
ICON_PORT    = "\U0001F50C"   # 🔌
ICON_PIN     = "\U0001F4CC"   # 📌
ICON_GEAR    = "\u2699\uFE0F"  # ⚙️
ICON_TRASH   = "\U0001F5D1"   # 🗑
ICON_DOT_OK   = "\U0001F7E2"  # 🟢 (cluster alcanzable)
ICON_DOT_FAIL = "\u26AB"      # ⚫ (cluster NO alcanzable)
ICON_DOT_WAIT = "\u26AA"      # ⚪ (verificando)
ICON_SEARCH   = "\U0001F50D"  # 🔍 (busqueda)
ICON_DISCOVERY = "\U0001F6F0" # 🛰 (discovery: escaneo del cluster)
ICON_REFRESH  = "\U0001F504"  # 🔄 (refrescar recursos)
ICON_PING     = "\U0001F3D3"  # 🏓 (ping TCP)
ICON_PLUS     = "\u2795"      # ➕ (agregar)
ICON_LOGS     = "\U0001F4DC"  # 📜 (logs del pod)

# 5b - PALETA DE COLORES PARA HOTBAR ITEMS:
HOTBAR_COLORS = [
    "#3b8ad4",  # azul
    "#1a8a6a",  # verde teal
    "#c77a1f",  # naranja
    "#6a1b9a",  # purpura
    "#1e3a8a",  # azul oscuro
    "#b91c1c",  # rojo
    "#0e7490",  # cyan oscuro
    "#9d174d",  # magenta oscuro
]

# 5c - ICONOS DISPONIBLES PARA HOTBAR ITEMS:
HOTBAR_ICONS = [
    "\U0001F310",  # 🌐 mundo
    "\U0001F5A5",  # 🖥 servidor
    "\U0001F4E6",  # 📦 pod
    "\U0001F433",  # 🐳 docker
    "\U0001F680",  # 🚀 cohete
    "\U0001F3D7",  # 🏗 construccion
    "\U0001F4A1",  # 💡 idea
    "\U0001F525",  # 🔥 fuego
    "\u2728",      # ✨ brillos
    "\U0001F4DA",  # 📚 libros
    "\U0001F3AF",  # 🎯 diana
    "\U0001F47E",  # 👾 alien
    "\U0001F578",  # 🕸 web
    "\u2699\uFE0F",# ⚙️ engranaje
    "\U0001F50C",  # 🔌 enchufe
    "\U0001F4BB",  # 💻 laptop
]

# 5d - GENERADOR DE COLOR PASTEL RANDOM:
def random_pastel_color():
    # 1 - GENERO UN HUE ALEATORIO Y LO CONVIERTO A HEX PASTEL:
    h = random.random()
    s = 0.45
    v = 0.85
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

# 5 - COLORES DE ESTADO (bolitas):
STATUS_COLORS = {
    "Running": "#2ecc71",      # verde
    "Pending": "#f39c12",      # naranja
    "Failed": "#e74c3c",       # rojo
    "Succeeded": "#3498db",    # azul
    "Unknown": "#95a5a6",      # gris
    "Terminating": "#e67e22",  # naranja oscuro
}


class FlowLayout(QLayout):
    """Layout que acomoda widgets en filas como un flow/wrap (tipo diagrama de red)."""

    def __init__(self, parent=None, margin=8, hspacing=12, vspacing=12):
        super().__init__(parent)
        self._items = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        m = self.contentsMargins()
        effective_rect = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective_rect.x()
        y = effective_rect.y()

        for item in self._items:
            space_x = self._hspace
            space_y = self._vspace
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + m.bottom()


class StatusDot(QLabel):
    """Bolita de color que representa el estado de un pod/service."""

    def __init__(self, status="Unknown", parent=None):
        super().__init__(parent)
        self.setObjectName("status_dot")
        self.setFixedSize(16, 16)
        self._status = status or "Unknown"
        self.setToolTip(self._status)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(STATUS_COLORS.get(self._status, STATUS_COLORS["Unknown"]))
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawEllipse(1, 1, 14, 14)


class ElideLabel(QLabel):
    """QLabel que muestra el texto recortado con '...' si no entra.

    El texto completo siempre esta disponible en el tooltip y se copia
    al portapapeles con un clic. No agranda el layout (evita que el
    splitter aplaste paneles cuando el texto es muy largo).
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = str(text)
        self._prefix = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(50)
        self.setCursor(Qt.PointingHandCursor)
        if text:
            self.setToolTip(str(text))
        self._update_elide()

    def set_prefix(self, prefix):
        # 1 - GUARDO UN PREFIJO PARA EL TOOLTIP (ej: "Ctx"):
        self._prefix = prefix
        self._update_elide()

    def setText(self, text):
        # 1 - GUARDO EL TEXTO COMPLETO Y MUESTRO LA VERSION RECORTADA:
        self._full_text = str(text)
        self._update_elide()

    def full_text(self):
        return self._full_text

    def mousePressEvent(self, event):
        # 1 - CLIC = COPIO EL TEXTO COMPLETO AL PORTAPAPELES:
        if self._full_text and self._full_text != "-":
            QGuiApplication.clipboard().setText(self._full_text)

    def resizeEvent(self, event):
        self._update_elide()

    def _update_elide(self):
        # 1 - CORTO EL TEXTO CON '...' SEGUN EL ANCHO DISPONIBLE:
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full_text, Qt.ElideRight, max(40, self.width() - 2))
        tooltip = f"{self._prefix}: {self._full_text}" if self._prefix else self._full_text
        if self._full_text and self._full_text != "-":
            self.setToolTip(f"{tooltip}  (clic para copiar)")
        else:
            self.setToolTip("")
        super().setText(elided)


def _pod_matches_selector(pod, selector):
    """True si el pod tiene TODOS los labels del selector del Service."""
    if not selector:
        return False
    labels = pod.metadata.labels or {}
    return all(labels.get(k) == v for k, v in selector.items())


def _get_pod_images(pod):
    """Lista de imagenes docker de los containers del pod."""
    if not pod.spec or not pod.spec.containers:
        return []
    return [c.image for c in pod.spec.containers if c.image]


def _get_pod_ports(pod):
    """Lista de puertos expuestos por los containers del pod."""
    ports = []
    if not pod.spec or not pod.spec.containers:
        return ports
    for c in pod.spec.containers:
        if c.ports:
            for p in c.ports:
                ports.append(f"{p.container_port}/{p.protocol or 'TCP'}")
    return ports


def _format_age(creation_timestamp):
    """Tiempo transcurrido desde creation_timestamp, estilo kubectl (ej: '3d 4h', '19m')."""
    if not creation_timestamp:
        return "-"
    total = int((datetime.now(timezone.utc) - creation_timestamp).total_seconds())
    if total < 0:
        return "-"
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    if minutes > 0:
        return f"{hours}h {minutes}m"
    return f"{total}s"


def _split_log_line(line):
    """Separa el timestamp RFC3339 que la API antepone con timestamps=True.

    Retorna (timestamp_local_formateado, mensaje). Si la linea no tiene un
    timestamp reconocible retorna ("", la linea completa).
    """
    parts = str(line).split(" ", 1)
    if len(parts) == 2 and len(parts[0]) >= 20 and parts[0][4] == "-" and "T" in parts[0]:
        raw_ts = parts[0]
        try:
            # 1 - CONVIERTO EL UTC DE K8S A HORA LOCAL (corto a microsegundos):
            dt = datetime.fromisoformat(raw_ts[:26]).replace(tzinfo=timezone.utc)
            local = dt.astimezone()
            return local.strftime("%d/%m %H:%M:%S"), parts[1]
        except Exception:
            return raw_ts[:19].replace("T", " "), parts[1]
    return "", line


def _expand_json_strings(obj, depth=0):
    """Recorre el objeto: si un valor string es JSON valido, lo convierte.

    Aplica en cualquier campo y de forma recursiva (con limite de
    profundidad para no colgarse con estructuras raras).
    """
    if depth > 3:
        return obj
    if isinstance(obj, dict):
        return {k: _expand_json_strings(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_json_strings(v, depth + 1) for v in obj]
    if isinstance(obj, str):
        t = obj.strip()
        if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
            try:
                return _expand_json_strings(json.loads(t), depth + 1)
            except Exception:
                return obj
    return obj


def _pretty_json(text):
    """Si el texto es JSON valido (dict/list) retorna el pretty-print, sino None.

    Si algun campo del JSON es un string con JSON anidado (patron comun de
    logs estructurados, ej: 'message'), lo expande tambien, en cualquier
    nivel de profundidad.
    """
    t = str(text).strip()
    if not (t.startswith("{") or t.startswith("[")):
        return None
    try:
        obj = json.loads(t)
    except Exception:
        return None
    if not isinstance(obj, (dict, list)):
        return None

    # 1 - EXPANDO CUALQUIER CAMPO QUE SEA UN STRING CON JSON ADENTRO:
    obj = _expand_json_strings(obj, 0)

    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return None


def _parse_line_ts(line):
    """Extrae el timestamp k8s (RFC3339) del inicio de una linea de log.

    Retorna un datetime UTC o None si la linea no lo trae.
    """
    parts = str(line).split(" ", 1)
    if len(parts[0]) >= 20 and parts[0][4] == "-" and "T" in parts[0]:
        try:
            return datetime.fromisoformat(parts[0][:26]).replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _is_read_timeout(e):
    """True si el error es un timeout de lectura (pod callado, no un fallo)."""
    if isinstance(e, TimeoutError):
        return True
    try:
        import urllib3
        return isinstance(e, urllib3.exceptions.ReadTimeoutError)
    except Exception:
        return False


def _looks_like_ip(text):
    """True si el texto tiene pinta de IPv4 (ej: 10.128.19.183)."""
    parts = str(text).strip().split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _make_ip_button(ip, tooltip_prefix="Copiar IP"):
    """Boton amarillo cliqueable con una IP: un clic la copia al portapapeles.

    No es editable: solo cliqueable. Mismo estilo que los badges de puertos.
    """
    btn = QPushButton(ip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(f"{tooltip_prefix}: {ip}  (clic para copiar)")
    btn.setMinimumWidth(120)
    btn.setStyleSheet(
        "QPushButton {"
        " background-color: #f5c518; color: #1a1a1a;"
        " border: none; border-radius: 4px;"
        " font-size: 13px; font-weight: bold; padding: 3px 12px;"
        "}"
        "QPushButton:hover { background-color: #ffd633; }"
        "QPushButton:pressed { background-color: #cc9900; }"
    )
    btn.clicked.connect(lambda checked, val=ip: QGuiApplication.clipboard().setText(val))
    return btn


class _LoadingOverlay(QWidget):
    """Overlay con spinner circular animado que cubre un widget mientras carga."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background-color: rgba(26, 26, 26, 180);")
        self._frame_idx = 0

        # 1 - LAYOUT CON EL SPINNER Y EL TEXTO:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self.lbl_spinner = QLabel(self.FRAMES[0])
        self.lbl_spinner.setStyleSheet(
            "font-size: 34px; color: #f5c518; background: transparent; border: none;"
        )
        self.lbl_spinner.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_spinner)
        self.lbl_text = QLabel("Cargando...")
        self.lbl_text.setStyleSheet(
            "font-size: 13px; color: #e0e0e0; background: transparent; border: none;"
        )
        self.lbl_text.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_text)

        # 2 - TIMER QUE ANIMA EL SPINNER:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        # 1 - AVANZO AL SIGUIENTE FRAME DEL SPINNER:
        self._frame_idx = (self._frame_idx + 1) % len(self.FRAMES)
        self.lbl_spinner.setText(self.FRAMES[self._frame_idx])

    def start(self, text="Cargando..."):
        # 1 - CUBRO TODO EL WIDGET PADRE Y ARRANCO LA ANIMACION:
        self.setGeometry(self.parentWidget().rect())
        self.lbl_text.setText(text)
        self.raise_()
        self.show()
        self._timer.start(80)

    def stop(self):
        # 1 - DETENGO LA ANIMACION Y ME OCULTO:
        self._timer.stop()
        self.hide()


class _RowDot(QWidget):
    """Bolita de estado pintada: gris/amarillo(parpadea)/verde/naranja/rojo."""

    COLORS = {
        "unknown": "#555555",
        "scanning": "#f5c518",
        "ok": "#2ecc71",
        "denied": "#f39c12",
        "fail": "#e74c3c",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "unknown"
        self._blink = False
        self.setFixedSize(14, 14)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._toggle_blink)

    def _toggle_blink(self):
        # 1 - ALTERNO LA INTENSIDAD PARA EL EFECTO PARPADEO:
        self._blink = not self._blink
        self.update()

    def set_state(self, state):
        # 1 - CAMBIO EL ESTADO Y ARRANCO/CORTO EL PARPADEO SI ES SCANNING:
        self._state = state if state in self.COLORS else "unknown"
        if self._state == "scanning":
            self._timer.start(400)
        else:
            self._timer.stop()
            self._blink = False
        self.update()

    def paintEvent(self, event):
        # 1 - PINTO LA BOLITA SEGUN EL ESTADO:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.COLORS[self._state])
        if self._state == "scanning" and self._blink:
            color = QColor("#806a10")
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawEllipse(1, 1, 12, 12)


class ClusterRow(QWidget):
    """Fila de cluster: nombre + host a la izquierda, bolita de estado a la derecha."""

    def __init__(self, name, host, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(8)

        # 1 - ICONO + NOMBRE:
        self.lbl_name = QLabel(f"{ICON_CLUSTER}  {name}")
        self.lbl_name.setStyleSheet(
            "font-size: 13px; color: #e8e8e8; background: transparent; border: none;"
        )
        self.lbl_name.setToolTip(name)
        layout.addWidget(self.lbl_name)

        # 2 - HOST EN GRIS CHICO:
        if host:
            lbl_host = QLabel(host)
            lbl_host.setStyleSheet(
                "font-size: 11px; color: #8a8a8a; background: transparent; border: none;"
            )
            layout.addWidget(lbl_host)

        layout.addStretch()

        # 3 - BOLITA DE ESTADO A LA DERECHA:
        self.dot = _RowDot()
        layout.addWidget(self.dot)

    def set_state(self, state):
        # 1 - ACTUALIZO LA BOLITA:
        self.dot.set_state(state)


class ContextRow(QWidget):
    """Fila de context: nombre a la izquierda, badge de pods + bolita a la derecha."""

    def __init__(self, name, is_current=False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(8)

        # 1 - ICONO + NOMBRE (+ "(actual)" si es el current-context):
        display = f"{ICON_CONTEXT}  {name}" + ("  (actual)" if is_current else "")
        self.lbl_name = QLabel(display)
        self.lbl_name.setStyleSheet(
            "font-size: 13px; color: #e8e8e8; background: transparent; border: none;"
            + ("font-weight: bold;" if is_current else "")
        )
        self.lbl_name.setToolTip(name)
        layout.addWidget(self.lbl_name)

        layout.addStretch()

        # 2 - BADGE DE PODS (pill redondeada, se llena al terminar el scan):
        self.badge = QLabel("")
        self.badge.setStyleSheet(
            "QLabel {"
            " font-size: 11px; font-weight: bold; color: #8a8a8a;"
            " background: transparent; border: none; padding: 1px 8px;"
            " border-radius: 8px;"
            "}"
        )
        self.badge.hide()
        layout.addWidget(self.badge)

        # 3 - BOLITA DE ESTADO:
        self.dot = _RowDot()
        layout.addWidget(self.dot)

    def set_state(self, state, n_pods=None):
        # 1 - ACTUALIZO LA BOLITA:
        self.dot.set_state(state)

        # 2 - ACTUALIZO EL BADGE SEGUN EL ESTADO:
        if state == "ok":
            # n_pods=None = conecto pero no se contaron pods (solo "OK"):
            self.badge.setText(f"{n_pods} pods" if n_pods is not None else "OK")
            self.badge.setStyleSheet(
                "QLabel { font-size: 11px; font-weight: bold; color: #2ecc71;"
                " background: rgba(46, 204, 113, 0.12); border: 1px solid rgba(46, 204, 113, 0.4);"
                " border-radius: 8px; padding: 1px 8px; }"
            )
            self.badge.show()
        elif state == "denied":
            self.badge.setText("403")
            self.badge.setStyleSheet(
                "QLabel { font-size: 11px; font-weight: bold; color: #f39c12;"
                " background: rgba(243, 156, 18, 0.12); border: 1px solid rgba(243, 156, 18, 0.4);"
                " border-radius: 8px; padding: 1px 8px; }"
            )
            self.badge.show()
        elif state == "fail":
            self.badge.setText("sin conexion")
            self.badge.setStyleSheet(
                "QLabel { font-size: 11px; font-weight: bold; color: #e74c3c;"
                " background: rgba(231, 76, 60, 0.12); border: 1px solid rgba(231, 76, 60, 0.4);"
                " border-radius: 8px; padding: 1px 8px; }"
            )
            self.badge.show()
        elif state == "scanning":
            self.badge.setText("...")
            self.badge.setStyleSheet(
                "QLabel { font-size: 11px; font-weight: bold; color: #f5c518;"
                " background: transparent; border: none; padding: 1px 8px; }"
            )
            self.badge.show()
        else:
            self.badge.hide()


# 1 - LOADER YAML QUE DETECTA CLAVES DUPLICADAS (ej: dos bloques 'users:'):
#     El parser estandar pisa la primera clave sin avisar; este loader
#     registra las repetidas para poder avisar en el log de importacion:
_DUP_KEYS = []

class _DuplicateKeyLoader(yaml.SafeLoader):
    pass

def _construct_mapping(loader, node, deep=False):
    # 1 - CONSTRUYO EL MAPPING; SI HAY CLAVES DUPLICADAS LAS ACOMODO
    #     (listas se unen, dicts se mezclan) en lugar de pisar la primera:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        value = loader.construct_object(value_node, deep=deep)
        if key in mapping:
            _DUP_KEYS.append(str(key))
            prev = mapping[key]
            if isinstance(prev, list) and isinstance(value, list):
                value = prev + value
            elif isinstance(prev, dict) and isinstance(value, dict):
                merged = dict(prev)
                merged.update(value)
                value = merged
        mapping[key] = value
    return mapping

_DuplicateKeyLoader.add_constructor("tag:yaml.org,2002:map", _construct_mapping)


class ServiceCard(QFrame):
    """Tarjeta grafica tipo 'servidor' que representa un Service + sus Pods."""

    def __init__(self, svc, matched_pods, parent=None, on_pod_click=None):
        super().__init__(parent)
        self.setObjectName("service_card")
        self.setMinimumWidth(300)
        self.setMaximumWidth(380)
        self.setMinimumHeight(180)
        self._on_pod_click = on_pod_click

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # 1 - HEADER: icono servidor + nombre + bolita de estado general:
        header = QHBoxLayout()
        title = QLabel(f"{ICON_SERVER}  {svc.metadata.name}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f5c518;")
        title.setWordWrap(True)
        header.addWidget(title, stretch=1)

        # Estado general: verde si hay al menos 1 pod Running, rojo si ninguno, etc.
        overall = self._overall_status(matched_pods)
        header.addWidget(StatusDot(overall))
        layout.addLayout(header)

        # 2 - FICHA DEL SERVICE: tipo + IP (con boton copiar) + puertos,
        #     todo dentro del box negro para que se entienda que es el SERVICE:
        svc_type = (svc.spec.type if svc.spec else None) or "ClusterIP"
        cluster_ip = (svc.spec.cluster_ip if svc.spec else None) or "-"

        ip_box = QFrame()
        ip_box.setStyleSheet(
            "QFrame { background-color: #1a1a1a; border: 1px solid #555; "
            "border-radius: 6px; padding: 4px; }"
        )
        ip_layout = QVBoxLayout(ip_box)
        ip_layout.setContentsMargins(8, 6, 8, 6)
        ip_layout.setSpacing(4)

        type_lbl = QLabel(f"Tipo: {svc_type}")
        type_lbl.setStyleSheet("color: #aaa; font-size: 11px; border: none; background: transparent;")
        ip_layout.addWidget(type_lbl)

        # 2a - IP DEL SERVICE como boton amarillo cliqueable (clic = copiar):
        ip_row = QHBoxLayout()
        ip_row.setSpacing(6)
        ip_titulo = QLabel("IP del SERVICE:")
        ip_titulo.setStyleSheet("color: #aaa; font-size: 11px; border: none; background: transparent;")
        ip_row.addWidget(ip_titulo)
        if cluster_ip and cluster_ip != "-":
            ip_row.addWidget(_make_ip_button(cluster_ip, tooltip_prefix="IP del SERVICE"))
        else:
            no_ip = QLabel("-")
            no_ip.setStyleSheet("color: #888; font-size: 13px; border: none; background: transparent;")
            ip_row.addWidget(no_ip)
        ip_row.addStretch()
        ip_layout.addLayout(ip_row)

        # 2b - PUERTOS ABIERTOS (lista vertical, un badge por fila):
        ports_titulo = QLabel(f"{ICON_PORT} Puertos abiertos:")
        ports_titulo.setStyleSheet("color: #aaa; font-size: 11px; border: none; background: transparent;")
        ip_layout.addWidget(ports_titulo)

        if svc.spec and svc.spec.ports:
            for p in svc.spec.ports:
                port_text = f"{p.port}/{p.protocol or 'TCP'}"
                if p.target_port and str(p.target_port) != str(p.port):
                    port_text += f" \u2192 {p.target_port}"
                port_badge = QLabel(f" {port_text} ")
                port_badge.setStyleSheet(
                    "background-color: #f5c518; color: #1a1a1a; "
                    "border-radius: 4px; font-size: 12px; font-weight: bold; padding: 3px 10px; border: none;"
                )
                ip_layout.addWidget(port_badge)
        else:
            no_ports = QLabel("(sin puertos)")
            no_ports.setStyleSheet("color: #888; font-size: 11px; font-style: italic; border: none; background: transparent;")
            ip_layout.addWidget(no_ports)

        layout.addWidget(ip_box)

        # 3 - SEPARADOR:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #555;")
        layout.addWidget(sep)

        # 4 - PODS DETRAS DEL SERVICE (cada fila muestra la IP DEL POD):
        pods_title = QLabel(f"{ICON_POD} Procesos / Pods detras ({len(matched_pods)}):")
        pods_title.setStyleSheet("color: #f5c518; font-size: 13px; font-weight: bold;")
        layout.addWidget(pods_title)

        if not matched_pods:
            empty = QLabel("(ningun pod matchea el selector del service)")
            empty.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
            layout.addWidget(empty)
        else:
            for pod in matched_pods:
                layout.addWidget(self._make_pod_row(pod))

    def _overall_status(self, pods):
        if not pods:
            return "Unknown"
        phases = [(p.status.phase if p.status else None) or "Unknown" for p in pods]
        if any(ph == "Running" for ph in phases):
            return "Running"
        if any(ph == "Failed" for ph in phases):
            return "Failed"
        if any(ph == "Pending" for ph in phases):
            return "Pending"
        return phases[0]

    def _make_pod_row(self, pod):
        # 1 - FILA CON BOLITA + NOMBRE + IMAGEN + PUERTOS:
        row = QFrame()
        row.setObjectName("pod_row")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.setSpacing(2)

        top = QHBoxLayout()
        phase = (pod.status.phase if pod.status else None) or "Unknown"
        top.addWidget(StatusDot(phase))

        name_lbl = QLabel(pod.metadata.name)
        name_lbl.setStyleSheet("color: #e0e0e0; font-size: 12px; font-weight: bold;")
        name_lbl.setWordWrap(True)
        top.addWidget(name_lbl, stretch=1)
        row_layout.addLayout(top)

        # 2 - IMAGENES DOCKER:
        images = _get_pod_images(pod)
        if images:
            img_text = ", ".join(images)
            img_lbl = QLabel(f"{ICON_DOCKER} {img_text}")
            img_lbl.setStyleSheet("color: #8ecae6; font-size: 11px;")
            img_lbl.setWordWrap(True)
            row_layout.addWidget(img_lbl)

        # 3 - PUERTOS DEL CONTAINER:
        ports = _get_pod_ports(pod)
        pod_ip = (pod.status.pod_ip if pod.status else None) or "-"
        if ports:
            detail_lbl = QLabel("ports: " + ", ".join(ports))
            detail_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
            detail_lbl.setWordWrap(True)
            row_layout.addWidget(detail_lbl)

        # 4 - IP DEL POD como boton amarillo cliqueable (clic = copiar):
        ip_row = QHBoxLayout()
        ip_row.setSpacing(6)
        ip_titulo = QLabel("ip pod:")
        ip_titulo.setStyleSheet("color: #aaa; font-size: 11px; border: none; background: transparent;")
        ip_row.addWidget(ip_titulo)
        if pod_ip != "-":
            ip_row.addWidget(_make_ip_button(pod_ip, tooltip_prefix="IP del POD"))
        else:
            no_ip = QLabel("-")
            no_ip.setStyleSheet("color: #888; font-size: 11px; border: none; background: transparent;")
            ip_row.addWidget(no_ip)
        ip_row.addStretch()
        row_layout.addLayout(ip_row)

        # 4 - CLIC PARA ABRIR DETALLE:
        if self._on_pod_click:
            row.setCursor(Qt.PointingHandCursor)
            row.mousePressEvent = lambda e, p=pod: self._on_pod_click(p)

        return row


class HotbarItem(QFrame):
    """Chip cuadrado tipo OpenLens para un cluster anclado en la hotbar."""

    def __init__(self, cluster_id, label, color, icon=None, short_alias=None, on_click=None, on_unpin=None, on_edit=None, parent=None):
        super().__init__(parent)
        self.cluster_id = cluster_id
        self._on_click = on_click
        self._on_unpin = on_unpin
        self._on_edit = on_edit
        self._selected = False
        self._color = color

        self.setObjectName("hotbar_item")
        self.setFixedSize(44, 44)
        self.setStyleSheet(f"background-color: {color};")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # 1 - ICONO (si hay) o LABEL (short_alias o 3 letras del nombre):
        display_icon = icon if icon else ICON_CLUSTER
        display_text = (short_alias[:4].upper() if short_alias else label[:3].upper()) if label else "?"

        icon_lbl = QLabel(display_icon)
        icon_lbl.setStyleSheet("color: #ffffff; font-size: 16px; border: none; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        text_lbl = QLabel(display_text)
        text_lbl.setStyleSheet("color: #ffffff; font-size: 9px; font-weight: bold; border: none; background: transparent;")
        text_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(text_lbl)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click:
            self._on_click(self.cluster_id)
        elif event.button() == Qt.RightButton:
            # 1 - MENU CONTEXTUAL: editar o desanclar:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            menu.setStyleSheet("QMenu { background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #555; } QMenu::item:selected { background-color: #f5c518; color: #1a1a1a; }")
            act_edit = menu.addAction(f"{ICON_GEAR}  Editar alias / color / icono")
            act_unpin = menu.addAction(f"{ICON_TRASH}  Quitar de la hotbar")
            action = menu.exec(event.globalPos().pos() if hasattr(event.globalPos(), 'pos') else event.globalPos())
            if action == act_edit and self._on_edit:
                self._on_edit(self.cluster_id)
            elif action == act_unpin and self._on_unpin:
                self._on_unpin(self.cluster_id)

    def set_selected(self, selected):
        self._selected = selected
        if selected:
            self.setObjectName("hotbar_item_selected")
        else:
            self.setObjectName("hotbar_item")
        self.setStyleSheet(f"background-color: {self._color};")


class HotbarItemEditor(QDialog):
    """Dialogo para editar alias, abreviatura, color e icono de un cluster anclado."""

    def __init__(self, cluster_data, parent=None):
        super().__init__(parent)
        self._cluster_data = cluster_data
        self._selected_color = cluster_data.get("color", "#3b8ad4")
        self._selected_icon = cluster_data.get("icon", None)

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_GEAR}  Editar cluster anclado")
        self.resize(420, 560)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 2 - NOMBRE ORIGINAL (solo lectura):
        orig_name = cluster_data.get("name", "-")
        orig_lbl = QLabel(f"Nombre original: {orig_name}")
        orig_lbl.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(orig_lbl)

        # 3 - ALIAS:
        layout.addWidget(QLabel("Alias (nombre personalizado):"))
        self.txt_alias = QLineEdit(cluster_data.get("alias") or "")
        self.txt_alias.setStyleSheet("QLineEdit { background-color: #2a2a2a; color: #f5c518; border: 1px solid #555; border-radius: 4px; padding: 6px; font-size: 14px; }")
        self.txt_alias.setPlaceholderText("ej: Produccion, Staging, Dev...")
        layout.addWidget(self.txt_alias)

        # 4 - SHORT ALIAS (abreviatura 3-4 letras):
        layout.addWidget(QLabel("Abreviatura (3-4 letras para la hotbar):"))
        self.txt_short = QLineEdit(cluster_data.get("short_alias") or "")
        self.txt_short.setStyleSheet("QLineEdit { background-color: #2a2a2a; color: #f5c518; border: 1px solid #555; border-radius: 4px; padding: 6px; font-size: 14px; }")
        self.txt_short.setPlaceholderText("ej: PRO, STG, DEV...")
        self.txt_short.setMaxLength(4)
        layout.addWidget(self.txt_short)

        # 5 - ICONO:
        layout.addWidget(QLabel("Icono:"))
        icon_row = QHBoxLayout()
        icon_row.setSpacing(4)
        self._icon_buttons = QButtonGroup(self)
        self._icon_buttons.setExclusive(True)

        # 5a - Boton "sin icono":
        btn_none = QRadioButton("Default")
        btn_none.setStyleSheet("QRadioButton { color: #e0e0e0; font-size: 12px; }")
        if not self._selected_icon:
            btn_none.setChecked(True)
        self._icon_buttons.addButton(btn_none, 0)
        icon_row.addWidget(btn_none)

        for i, ic in enumerate(HOTBAR_ICONS):
            btn = QRadioButton(ic)
            btn.setStyleSheet("QRadioButton { color: #e0e0e0; font-size: 18px; }")
            if self._selected_icon == ic:
                btn.setChecked(True)
            self._icon_buttons.addButton(btn, i + 1)
            icon_row.addWidget(btn)

        icon_row.addStretch()
        layout.addLayout(icon_row)

        # 6 - COLOR:
        layout.addWidget(QLabel("Color:"))
        self._color_buttons = QButtonGroup(self)
        self._color_buttons.setExclusive(True)

        # 6a - PALETA DE COLORES GUARDADOS EN LA DB:
        colors = dbmod.get_colors()
        color_row = QHBoxLayout()
        color_row.setSpacing(4)

        for i, c in enumerate(colors):
            btn = QPushButton("")
            btn.setFixedSize(32, 32)
            btn.setStyleSheet(f"background-color: {c['hex']}; border: 2px solid {'#f5c518' if c['hex'] == self._selected_color else '#555'}; border-radius: 6px;")
            btn.setToolTip(c.get("name", c["hex"]))
            btn.clicked.connect(lambda checked, hex_val=c["hex"]: self._select_color(hex_val))
            color_row.addWidget(btn)

        # 6b - BOTON COLOR RANDOM PASTEL:
        btn_random = QPushButton("🎲")
        btn_random.setFixedSize(32, 32)
        btn_random.setStyleSheet("background-color: #2a2a2a; border: 2px solid #555; border-radius: 6px; font-size: 16px;")
        btn_random.setToolTip("Generar color pastel aleatorio")
        btn_random.clicked.connect(self._random_color)
        color_row.addWidget(btn_random)

        # 6c - BOTON COLOR PERSONALIZADO:
        btn_custom = QPushButton("🎨")
        btn_custom.setFixedSize(32, 32)
        btn_custom.setStyleSheet("background-color: #2a2a2a; border: 2px solid #555; border-radius: 6px; font-size: 16px;")
        btn_custom.setToolTip("Color personalizado")
        btn_custom.clicked.connect(self._custom_color)
        color_row.addWidget(btn_custom)

        color_row.addStretch()
        layout.addLayout(color_row)

        # 6d - GUARDAR COLOR EN PALETA:
        self.chk_save_color = QRadioButton("Guardar color en paleta")
        self.chk_save_color.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self.chk_save_color)

        # 7 - PREVIEW DEL ITEM:
        layout.addWidget(QLabel("Preview:"))
        self.preview_frame = QFrame()
        self.preview_frame.setFixedSize(60, 60)
        self.preview_frame.setStyleSheet(f"background-color: {self._selected_color}; border-radius: 10px;")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.setSpacing(0)
        self.preview_icon = QLabel(self._selected_icon or ICON_CLUSTER)
        self.preview_icon.setStyleSheet("color: #ffffff; font-size: 20px; border: none; background: transparent;")
        self.preview_icon.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_icon)
        self.preview_text = QLabel((self.txt_short.text()[:4].upper() if self.txt_short.text() else orig_name[:3].upper()))
        self.preview_text.setStyleSheet("color: #ffffff; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        self.preview_text.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(self.preview_frame)

        # 8 - CONEXIONES PARA ACTUALIZAR PREVIEW:
        self.txt_short.textChanged.connect(self._update_preview)
        self._icon_buttons.buttonClicked.connect(self._on_icon_changed)

        layout.addStretch()

        # 9 - BOTONES:
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Guardar")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet("QPushButton { background-color: #444; color: #e0e0e0; }")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _select_color(self, hex_val):
        self._selected_color = hex_val
        self._update_preview()

    def _random_color(self):
        self._selected_color = random_pastel_color()
        self._update_preview()

    def _custom_color(self):
        c = QColorDialog.getColor(QColor(self._selected_color), self, "Seleccionar color")
        if c.isValid():
            self._selected_color = c.name()
            self._update_preview()

    def _on_icon_changed(self, button):
        idx = self._icon_buttons.id(button)
        if idx == 0:
            self._selected_icon = None
        else:
            self._selected_icon = HOTBAR_ICONS[idx - 1]
        self._update_preview()

    def _update_preview(self):
        # 1 - ACTUALIZO EL PREVIEW:
        self.preview_frame.setStyleSheet(f"background-color: {self._selected_color}; border-radius: 10px;")
        self.preview_icon.setText(self._selected_icon or ICON_CLUSTER)
        short = self.txt_short.text()[:4].upper() if self.txt_short.text() else (self._cluster_data.get("name", "?")[:3].upper())
        self.preview_text.setText(short)

    def get_values(self):
        # 1 - RETORNO LOS VALORES INGRESADOS:
        idx = self._icon_buttons.checkedId()
        icon = None if idx <= 0 else HOTBAR_ICONS[idx - 1]
        return {
            "alias": self.txt_alias.text().strip(),
            "short_alias": self.txt_short.text().strip(),
            "color": self._selected_color,
            "icon": icon,
            "save_color": self.chk_save_color.isChecked(),
        }


class Hotbar(QFrame):
    """Barra vertical izquierda con clusters anclados (estilo OpenLens).

    Acepta drag & drop de clusters desde la lista para anclarlos.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hotbar")
        self.setFixedWidth(64)
        self.setAcceptDrops(True)
        self._items = {}
        self._selected_id = None
        self._on_item_click = None
        self._on_item_unpin = None
        self._on_item_edit = None
        self._on_item_drop = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        # 1 - HEADER CON ICONO HOME:
        header = QLabel(ICON_CLUSTER)
        header.setStyleSheet("font-size: 20px; color: #9ca3af; border: none; background: transparent;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # 2 - CONTAINER PARA LOS ITEMS:
        self.items_layout = QVBoxLayout()
        self.items_layout.setSpacing(8)
        self.items_layout.setAlignment(Qt.AlignTop)
        layout.addLayout(self.items_layout)

        layout.addStretch()

        # 3 - FOOTER (indicador de pagina):
        footer = QLabel("1")
        footer.setStyleSheet("color: #6b7280; font-size: 11px; border: none; background: transparent;")
        footer.setAlignment(Qt.AlignCenter)
        layout.addWidget(footer)

    def set_callbacks(self, on_click, on_unpin, on_edit=None, on_drop=None):
        self._on_item_click = on_click
        self._on_item_unpin = on_unpin
        self._on_item_edit = on_edit
        self._on_item_drop = on_drop

    def dragEnterEvent(self, event: QDragEnterEvent):
        # 1 - ACEPTO EL DRAG SI TRAE UN CLUSTER DE MINILENS:
        if event.mimeData().hasFormat("application/x-minilens-cluster"):
            event.acceptProposedAction()
            self.setStyleSheet("QFrame#hotbar { background-color: #1e2126; border: 2px dashed #f5c518; }")

    def dragLeaveEvent(self, event):
        # 1 - RESTAURO EL ESTILO NORMAL DE LA HOTBAR:
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        # 1 - RESTAURO EL ESTILO Y OBTENGO EL CLUSTER ARRASTRADO:
        self.setStyleSheet("")
        if not self._on_item_drop:
            return
        data = bytes(event.mimeData().data("application/x-minilens-cluster")).decode("utf-8")
        if "|" not in data:
            return
        cluster_name, kc_id = data.rsplit("|", 1)
        event.acceptProposedAction()
        self._on_item_drop(cluster_name, int(kc_id or 0))

    def refresh(self, pinned_clusters):
        """Reconstruye los items de la hotbar desde la lista de clusters anclados."""
        # 1 - BORRO ITEMS EXISTENTES:
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._items.clear()

        # 2 - AGREGO LOS CLUSTERS ANCLADOS:
        for i, c in enumerate(pinned_clusters):
            label = c.get("alias") or c.get("name", "?")
            short_alias = c.get("short_alias") or ""
            color = c.get("color", HOTBAR_COLORS[i % len(HOTBAR_COLORS)])
            icon = c.get("icon") or None
            tooltip = c.get("name", "?")
            if c.get("alias"):
                tooltip = f"{c['alias']} ({c['name']})"
            item = HotbarItem(
                cluster_id=c["id"],
                label=tooltip,
                color=color,
                icon=icon,
                short_alias=short_alias,
                on_click=self._on_item_click,
                on_unpin=self._on_item_unpin,
                on_edit=self._on_item_edit,
            )
            if c["id"] == self._selected_id:
                item.set_selected(True)
            self.items_layout.addWidget(item)
            self._items[c["id"]] = item

        # 3 - AGREGO SLOTS VACIOS (hasta 12):
        empty_slots = max(0, 12 - len(pinned_clusters))
        for _ in range(empty_slots):
            slot = QFrame()
            slot.setObjectName("hotbar_slot_empty")
            self.items_layout.addWidget(slot)

    def select(self, cluster_id):
        # 1 - DESMARCO EL ANTERIOR:
        if self._selected_id and self._selected_id in self._items:
            self._items[self._selected_id].set_selected(False)

        # 2 - MARCO EL NUEVO:
        self._selected_id = cluster_id
        if cluster_id and cluster_id in self._items:
            self._items[cluster_id].set_selected(True)


class DropZone(QLabel):
    """Zona de drag & drop para archivos kubeconfig."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setText(
            f"{ICON_FILE}  Arrastra aqui tu archivo kubeconfig (.yaml / .yml)\n"
            f"   o usa los botones de arriba"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._parent_window = None

    def set_parent_window(self, window):
        self._parent_window = window

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QLabel#dropzone { border-color: #ffd633; background-color: #333; }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        if not urls:
            return
        file_path = urls[0].toLocalFile()
        if file_path and (file_path.endswith(".yaml") or file_path.endswith(".yml")):
            if self._parent_window:
                self._parent_window.load_kubeconfig(file_path)
        else:
            QMessageBox.warning(
                self._parent_window,
                f"{ICON_WARN} Formato no valido",
                "Por favor arrastra un archivo .yaml o .yml",
            )


class ClusterListWidget(QListWidget):
    """Lista de clusters que permite arrastrar un cluster hacia la hotbar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.parent_window = None

    def startDrag(self, supported_actions):
        # 1 - ARMO EL DRAG CON EL NOMBRE DEL CLUSTER Y EL KUBECONFIG ACTIVO:
        item = self.currentItem()
        if not item or not self.parent_window:
            return
        cluster = item.data(Qt.UserRole)
        if not cluster:
            return
        mime = QMimeData()
        mime.setData(
            "application/x-minilens-cluster",
            f"{cluster.get('name', '')}|{self.parent_window._current_kubeconfig_id or 0}".encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class ErrorLogDialog(QDialog):
    """Dialogo que muestra un log (errores de API/conexion o importacion)."""

    def __init__(self, error_log, parent=None, title=None, empty_text="(sin errores registrados)"):
        super().__init__(parent)
        self._error_log = error_log
        self._empty_text = empty_text

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(title or f"{ICON_WARN}  Log de errores")
        self.resize(760, 500)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")

        layout = QVBoxLayout(self)

        # 2 - TEXTO DEL LOG (solo lectura):
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet(
            "QTextEdit { background-color: #111; color: #e0e0e0; border: 1px solid #555; "
            "border-radius: 4px; font-family: Consolas, monospace; font-size: 12px; }"
        )
        self.txt_log.setPlainText("\n\n".join(error_log) if error_log else self._empty_text)
        layout.addWidget(self.txt_log)

        # 3 - BOTONES:
        btn_row = QHBoxLayout()
        btn_copy = QPushButton("Copiar todo")
        btn_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.txt_log.toPlainText()))
        btn_clear = QPushButton("Limpiar log")
        btn_clear.clicked.connect(self._clear_log)
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _clear_log(self):
        # 1 - LIMPIO LA LISTA COMPARTIDA CON LA VENTANA PRINCIPAL:
        self._error_log.clear()
        self.txt_log.setPlainText(self._empty_text)


class KubeconfigReportDialog(QDialog):
    """Reporte interactivo de revision de un kubeconfig.

    Muestra cada fix/issue con un checkbox para aplicarlo o no,
    y botones para guardar copia o sobrescribir el original.
    """

    def __init__(self, fixes, issues, fixed_config, original_path, parent=None):
        super().__init__(parent)
        self._fixed_config = fixed_config
        self._original_path = original_path
        self._fixes = fixes
        self._issues = issues

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_INFO}  Revision del kubeconfig")
        self.resize(760, 560)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 2 - TITULO EXPLICATIVO:
        title = QLabel(f"{ICON_INFO}  Se encontraron {len(fixes) + len(issues)} puntos de revision:")
        title.setStyleSheet("font-size: 14px; color: #f5c518; font-weight: bold;")
        layout.addWidget(title)

        # 3 - LISTA DE FIXES CON CHECKBOX (cada uno aplicable o no):
        self._fix_checks = []
        if fixes:
            lbl_fixes = QLabel(f"{ICON_OK}  Correcciones automaticas:")
            lbl_fixes.setStyleSheet("color: #2ecc71; font-size: 13px; font-weight: bold;")
            layout.addWidget(lbl_fixes)

            for fx in fixes:
                cb = QCheckBox(f"[AUTO-FIX] {fx}")
                cb.setChecked(True)
                cb.setStyleSheet("QCheckBox { color: #e0e0e0; font-size: 12px; } QCheckBox::indicator { width: 16px; height: 16px; }")
                layout.addWidget(cb)
                self._fix_checks.append((cb, fx))

        # 4 - LISTA DE ISSUES (informativos, no aplicables con checkbox):
        if issues:
            lbl_issues = QLabel(f"{ICON_WARN}  Avisos y errores:")
            lbl_issues.setStyleSheet("color: #f39c12; font-size: 13px; font-weight: bold;")
            layout.addWidget(lbl_issues)

            for sev, msg in issues:
                color = "#e74c3c" if sev == "ERROR" else "#f39c12"
                lbl = QLabel(f"  [{sev}] {msg}")
                lbl.setStyleSheet(f"color: {color}; font-size: 12px; padding: 2px 0;")
                lbl.setWordWrap(True)
                layout.addWidget(lbl)

        layout.addStretch()

        # 5 - BOTONES:
        btn_row = QHBoxLayout()
        btn_apply = QPushButton(f"{ICON_OK}  Aplicar al original")
        btn_apply.setToolTip("Sobrescribe el archivo original con las correcciones seleccionadas")
        btn_apply.setStyleSheet("QPushButton { background-color: #2ecc71; color: #1a1a1a; font-weight: bold; padding: 6px 12px; }")
        btn_apply.clicked.connect(self._apply_to_original)

        btn_save_copy = QPushButton("Guardar copia corregida...")
        btn_save_copy.setToolTip("Guarda el kubeconfig corregido como <nombre>-fixed.yaml")
        btn_save_copy.clicked.connect(self._save_fixed)

        btn_close = QPushButton("Cerrar sin cambios")
        btn_close.setStyleSheet("QPushButton { background-color: #444; color: #e0e0e0; }")
        btn_close.clicked.connect(self.accept)

        btn_row.addStretch()
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_save_copy)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _build_fixed_config(self):
        # 1 - CONSTRUYO EL CONFIG CON SOLO LOS FIXES SELECCIONADOS:
        import copy
        config = copy.deepcopy(self._fixed_config)

        # 1a - SI HAY FIXES NO SELECCIONADOS, LOS REVIERTO:
        for cb, fx in self._fix_checks:
            if not cb.isChecked():
                # 1b - SI EL FIX ERA ASIGNAR 'default' A UN CONTEXT SIN NS, LO REVIERTO:
                if "namespace 'default' asignado" in fx:
                    # EXTRAIGO EL NOMBRE DEL CONTEXT DEL MENSAJE:
                    import re
                    match = re.search(r"context '([^']+)'", fx)
                    if match:
                        ctx_name = match.group(1)
                        for ctx in config.get("contexts", []):
                            if ctx.get("name") == ctx_name:
                                cd = ctx.get("context", {})
                                if cd.get("namespace") == "default":
                                    del cd["namespace"]
        return config

    def _apply_to_original(self):
        # 1 - CONSTRUYO EL CONFIG CORREGIDO:
        config = self._build_fixed_config()

        # 2 - PREGUNTO ANTES DE SOBRESCRIBIR:
        reply = QMessageBox.question(
            self,
            f"{ICON_WARN} Sobrescribir archivo original",
            f"¿Seguro que queres sobrescribir el archivo original?\n\n"
            f"  {self._original_path}\n\n"
            f"Se aplicaran {sum(1 for cb, _ in self._fix_checks if cb.isChecked())} correccion(es).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 3 - GUARDO SOBRE EL ORIGINAL:
        try:
            with open(self._original_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
            QMessageBox.information(
                self,
                f"{ICON_OK} Archivo corregido",
                f"El archivo original fue corregido:\n{self._original_path}",
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                f"{ICON_WARN} Error",
                f"No se pudo sobrescribir:\n{e}",
            )

    def _save_fixed(self):
        # 1 - CONSTRUYO EL CONFIG CORREGIDO:
        config = self._build_fixed_config()

        # 2 - GUARDO JUNTO AL ORIGINAL CON SUFIJO -fixed:
        base, ext = os.path.splitext(self._original_path)
        out = f"{base}-fixed{ext or '.yaml'}"
        try:
            with open(out, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
            QMessageBox.information(
                self,
                f"{ICON_OK} Guardado",
                f"Copia corregida guardada en:\n{out}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                f"{ICON_WARN} Error",
                f"No se pudo guardar:\n{e}",
            )


class _MergeTestSkip(Exception):
    """El context no se puede probar automaticamente (exec plugin / auth-provider sin token)."""
    pass


def _api_error_message(e):
    """Extrae el mensaje completo del body JSON de un ApiException.

    El body trae el detalle real del RBAC, por ejemplo:
    'pods is forbidden: User "rghernandez" cannot list resource "pods"...'
    """
    import json
    try:
        body = json.loads(e.body or "{}")
        msg = body.get("message") or ""
        if msg:
            return msg
    except Exception:
        pass
    return str(e.reason or e)


def _api_error_user(e):
    """Extrae el nombre de usuario del mensaje de error de la API (si viene)."""
    import json
    import re
    try:
        body = json.loads(e.body or "{}")
        msg = body.get("message") or ""
        match = re.search(r'User "([^"]+)"', msg)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def _build_api_client_from_dict(cfg, ctx_name, base_dir):
    """Arma un ApiClient aislado desde un dict kubeconfig (sin tocar el global).

    Soporta: token, tokenFile, client cert (data o archivo), username/password
    y auth-provider con id-token cacheado. Para exec plugins lanza _MergeTestSkip.
    Retorna (api_client, [archivos_temporales_a_borrar]).
    """
    import base64

    # 1 - BUSCO EL CONTEXT PEDIDO:
    ctx_entry = next(
        (c for c in (cfg.get("contexts") or []) if c.get("name") == ctx_name),
        None,
    )
    if not ctx_entry:
        raise ValueError(f"el context '{ctx_name}' no existe")
    cd = ctx_entry.get("context") or {}

    # 2 - BUSCO EL CLUSTER:
    cluster = next(
        ((c.get("cluster") or {}) for c in (cfg.get("clusters") or []) if c.get("name") == cd.get("cluster")),
        None,
    )
    if not cluster or not cluster.get("server"):
        raise ValueError(f"el cluster '{cd.get('cluster')}' no existe o no define server")

    # 3 - BUSCO EL USER (puede no existir: algunos clusters permiten anonimo):
    user_entry = next(
        (u for u in (cfg.get("users") or []) if u.get("name") == cd.get("user")),
        None,
    )
    ud = (user_entry or {}).get("user") or {}

    # 4 - ARMO LA CONFIGURACION DEL CLIENTE:
    kcfg = client.Configuration()
    kcfg.host = cluster.get("server")
    temps = []

    def b64_clean(data):
        # 1 - LOS KUBECONFIGS A VECES TIENEN SALTOS DE LINEA EN EL BASE64:
        return (data or "").replace("\n", "").replace(" ", "")

    def write_temp(data_b64):
        # 1 - DECODIFICO BASE64 A UN ARCHIVO TEMPORAL:
        fd = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
        fd.write(base64.b64decode(b64_clean(data_b64)))
        fd.close()
        temps.append(fd.name)
        return fd.name

    def resolve_path(path):
        # 1 - LAS RUTAS RELATIVAS VAN RESPECTO AL KUBECONFIG ORIGINAL:
        return path if os.path.isabs(path) else os.path.join(base_dir, path)

    # 4a - CA DEL CLUSTER:
    if cluster.get("insecure-skip-tls-verify"):
        kcfg.verify_ssl = False
    if cluster.get("certificate-authority-data"):
        kcfg.ssl_ca_cert = write_temp(cluster.get("certificate-authority-data"))
    elif cluster.get("certificate-authority"):
        kcfg.ssl_ca_cert = resolve_path(cluster.get("certificate-authority"))

    # 5 - CREDENCIALES:
    if ud.get("token"):
        kcfg.api_key = {"authorization": f"Bearer {ud.get('token')}"}
    elif ud.get("tokenFile"):
        with open(resolve_path(ud.get("tokenFile")), "r", encoding="utf-8") as tf:
            kcfg.api_key = {"authorization": f"Bearer {tf.read().strip()}"}
    elif ud.get("client-certificate-data") or ud.get("client-certificate"):
        # CERT + KEY (data base64 o rutas de archivo):
        if ud.get("client-certificate-data"):
            kcfg.cert_file = write_temp(ud.get("client-certificate-data"))
        else:
            kcfg.cert_file = resolve_path(ud.get("client-certificate"))
        if ud.get("client-key-data"):
            kcfg.key_file = write_temp(ud.get("client-key-data"))
        elif ud.get("client-key"):
            kcfg.key_file = resolve_path(ud.get("client-key"))
    elif ud.get("username"):
        kcfg.username = ud.get("username")
        kcfg.password = ud.get("password") or ""
    elif ud.get("auth-provider"):
        # OIDC/GCP/etc: solo si hay id-token cacheado en el config:
        id_token = ((ud.get("auth-provider") or {}).get("config") or {}).get("id-token")
        if id_token:
            kcfg.api_key = {"authorization": f"Bearer {id_token}"}
        else:
            raise _MergeTestSkip("no probable: auth-provider sin id-token")
    elif ud.get("exec"):
        raise _MergeTestSkip("no probable: usa plugin exec")
    # sin credenciales: pruebo anonimo igual

    return client.ApiClient(kcfg), temps


class _MergeTestSignals(QObject):
    # SENAL PARA REPORTAR EL RESULTADO DEL TEST DE UN CONTEXT DEL MERGE:
    result = Signal(str, str, str, str)   # (side, ctx_name, estado, detalle)


class _MergeTestTask(QRunnable):
    # TASK: prueba un context del merge conectando y listando pods:
    def __init__(self, side, ctx_name, cfg, namespace, base_dir, signals):
        super().__init__()
        self._side = side
        self._ctx_name = ctx_name
        self._cfg = cfg
        self._ns = namespace
        self._base_dir = base_dir
        self._signals = signals

    def run(self):
        api_client = None
        temps = []
        try:
            # 1 - ARMO EL CLIENTE DESDE EL DICT (aislado, sin config global):
            api_client, temps = _build_api_client_from_dict(
                self._cfg, self._ctx_name, self._base_dir
            )

            # 2 - PRUEBO LISTANDO LOS PODS DEL NAMESPACE (timeout 8s):
            v1 = client.CoreV1Api(api_client)
            pod_list = v1.list_namespaced_pod(namespace=self._ns, _request_timeout=8)
            n = len(pod_list.items)
            print(f"[MiniLens] Merge test '{self._ctx_name}': OK, {n} pods")
            self._signals.result.emit(self._side, self._ctx_name, "ok", f"OK - {n} pods")
        except _MergeTestSkip as e:
            self._signals.result.emit(self._side, self._ctx_name, "skip", str(e))
        except ApiException as e:
            if e.status == 403:
                user = _api_error_user(e)
                msg = _api_error_message(e)
                print(f"[MiniLens] Merge test '{self._ctx_name}': 403 (sin permiso) -> {msg}")
                detalle = f'403 · sos "{user}"' if user else "403 sin permiso"
                self._signals.result.emit(self._side, self._ctx_name, "denied", detalle)
            elif e.status == 401:
                user = _api_error_user(e)
                msg = _api_error_message(e)
                print(f"[MiniLens] Merge test '{self._ctx_name}': 401 -> {msg}")
                detalle = f'401 · sos "{user}"' if user else "401 credenciales"
                self._signals.result.emit(self._side, self._ctx_name, "auth", detalle)
            else:
                self._signals.result.emit(self._side, self._ctx_name, "fail", f"API {e.status}")
        except Exception as e:
            print(f"[MiniLens] Merge test '{self._ctx_name}': fallo ({_short_error(e)})")
            self._signals.result.emit(self._side, self._ctx_name, "fail", "sin conexion")
        finally:
            # 3 - LIMPIO LOS ARCHIVOS TEMPORALES DE CERTS:
            for t in temps:
                try:
                    os.unlink(t)
                except Exception:
                    pass


class _MergeList(QListWidget):
    """Lista de contexts de un lado del merge; acepta drops del lado opuesto."""

    def __init__(self, side, dialog, parent=None):
        super().__init__(parent)
        self._side = side
        self._dialog = dialog
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def startDrag(self, supported_actions):
        # 1 - ARMO EL DRAG CON EL NOMBRE DEL CONTEXT:
        item = self.currentItem()
        if not item:
            return
        mime = QMimeData()
        mime.setData(
            "application/x-minilens-merge",
            f"{self._side}|{item.data(Qt.UserRole) or ''}".encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    def dragEnterEvent(self, e):
        # 1 - ACEPTO SOLO DROPS DEL OTRO LADO DEL MERGE:
        if e.mimeData().hasFormat("application/x-minilens-merge"):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat("application/x-minilens-merge"):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        # 1 - SI NO ES UN DRAG DEL MERGE, LO DEJO EN MANOS DE QT:
        if not e.mimeData().hasFormat("application/x-minilens-merge"):
            super().dropEvent(e)
            return

        # 2 - DECODIFICO (lado|nombre del context):
        data = bytes(e.mimeData().data("application/x-minilens-merge")).decode("utf-8")
        src_side, _, ctx_name = data.partition("|")

        # 2a - DROP AL MISMO LADO: IGNORO:
        if src_side == self._side:
            return
        e.acceptProposedAction()
        self._dialog.move_context(src_side, self._side, ctx_name)


class _MergeRow(QWidget):
    """Fila de context en el merge: texto + estado del test + boton Probar."""

    STATUS_COLORS = {
        "ok": "#2ecc71",
        "denied": "#f39c12",
        "auth": "#e74c3c",
        "fail": "#e74c3c",
        "skip": "#8a8a8a",
        "testing": "#f5c518",
    }

    def __init__(self, dialog, side, ctx_name, text, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self._side = side
        self._ctx_name = ctx_name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)

        # 1 - TEXTO DEL CONTEXT (cluster / user / ns):
        self.lbl_text = QLabel(text)
        self.lbl_text.setStyleSheet(
            "font-size: 12px; color: #e8e8e8; background: transparent; border: none;"
        )
        self.lbl_text.setToolTip(text)
        layout.addWidget(self.lbl_text)

        layout.addStretch()

        # 2 - ESTADO DEL TEST (se llena al probar):
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(
            "font-size: 11px; font-weight: bold; background: transparent; border: none;"
        )
        layout.addWidget(self.lbl_status)

        # 3 - BOTON PROBAR (lanza el test de conexion real):
        self.btn_test = QPushButton("Probar")
        self.btn_test.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 10px; }"
        )
        self.btn_test.setToolTip("Conecta al cluster con este context y lista los pods")
        self.btn_test.clicked.connect(self._on_test)
        layout.addWidget(self.btn_test)

    def _on_test(self):
        # 1 - MARCO EN ESPERA Y LANZO EL TEST:
        self.btn_test.setEnabled(False)
        self.lbl_status.setText("probando...")
        self.lbl_status.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #f5c518; background: transparent; border: none;"
        )
        self._dialog.test_context(self._side, self._ctx_name)

    def set_result(self, estado, detalle):
        # 1 - PINTO EL RESULTADO SEGUN EL ESTADO:
        self.btn_test.setEnabled(True)
        color = self.STATUS_COLORS.get(estado, "#8a8a8a")
        self.lbl_status.setText(detalle)
        self.lbl_status.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {color};"
            " background: transparent; border: none;"
        )


class KubeconfigMergeDialog(QDialog):
    """Ventana para fusionar 2 kubeconfigs arrastrando contexts entre ambos.

    Cada lado se carga con un archivo (validado al abrir). Al arrastrar un
    context al otro lado se mueve junto con su cluster y su user (si faltan).
    Al guardar se vuelve a validar y pide confirmacion si hay errores.
    """

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._configs = {"left": None, "right": None}
        self._paths = {"left": None, "right": None}
        self._lists = {}
        self._lbl_files = {}
        self._lbl_issues = {}

        # 1a - POOL Y SENALES PARA LOS TESTS DE CONEXION POR CONTEXT:
        #      Resultados: {(side, ctx_name): (estado, detalle)}
        self._test_pool = QThreadPool()
        self._test_pool.setMaxThreadCount(4)
        self._test_signals = _MergeTestSignals()
        self._test_signals.result.connect(self._on_merge_test_done)
        self._test_results = {}
        self._fix_tried = set()

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_FILE}  Fusionar kubeconfigs")
        self.resize(900, 620)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")
        layout = QVBoxLayout(self)

        # 2 - EXPLICACION:
        lbl_help = QLabel(
            "Abrí un kubeconfig en cada lado y arrastrá contexts de uno al otro para pasarlos.\n"
            "Al pasar un context se copian también su cluster y su user si no existen en el destino."
        )
        lbl_help.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(lbl_help)

        # 3 - DOS PANELES (izquierda y derecha):
        panels = QHBoxLayout()
        self._panel_left = self._build_side("left")
        self._panel_right = self._build_side("right")
        panels.addWidget(self._panel_left, stretch=1)
        panels.addWidget(self._panel_right, stretch=1)
        layout.addLayout(panels, stretch=1)

        # 4 - LOG DE ACCIONES:
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(90)
        self.txt_log.setStyleSheet(
            "QTextEdit { background-color: #111; color: #e0e0e0; border: 1px solid #555;"
            " border-radius: 4px; font-family: Consolas, monospace; font-size: 11px; }"
        )
        layout.addWidget(self.txt_log)

        # 5 - BOTONES DE GUARDADO:
        btn_row = QHBoxLayout()
        btn_save_l = QPushButton(f"{ICON_FILE}  Guardar izquierda...")
        btn_save_l.clicked.connect(lambda: self._save_side("left"))
        btn_save_r = QPushButton(f"{ICON_FILE}  Guardar derecha...")
        btn_save_r.clicked.connect(lambda: self._save_side("right"))
        btn_close = QPushButton("Cerrar")
        btn_close.setStyleSheet("QPushButton { background-color: #444; color: #e0e0e0; }")
        btn_close.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_save_l)
        btn_row.addWidget(btn_save_r)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _build_side(self, side):
        # 1 - GRUPO CON HEADER (archivo + abrir), LISTA Y LABEL DE VALIDACION:
        group = QGroupBox(f"{ICON_FILE}  {side == 'left' and 'Origen' or 'Destino'}")
        group.setStyleSheet("QGroupBox { border: 2px solid #f5c518; border-radius: 6px; margin-top: 10px; padding-top: 6px; } QGroupBox::title { color: #f5c518; }")
        v = QVBoxLayout(group)

        header = QHBoxLayout()
        lbl_file = QLabel("(sin archivo)")
        lbl_file.setStyleSheet("color: #888; font-size: 12px;")
        btn_open = QPushButton("Abrir...")
        btn_open.clicked.connect(lambda: self._open_file(side))
        btn_creds = QPushButton("🔑 Creds")
        btn_creds.setToolTip(
            "Ver los users del archivo: a que contexts/clusters pertenecen y copiar sus credenciales"
        )
        btn_creds.clicked.connect(lambda: self._show_creds(side))
        header.addWidget(lbl_file, stretch=1)
        header.addWidget(btn_creds)
        header.addWidget(btn_open)
        v.addLayout(header)

        lst = _MergeList(side, self)
        lst.setStyleSheet("QListWidget { font-size: 12px; }")
        v.addWidget(lst, stretch=1)

        lbl_issues = QLabel("")
        lbl_issues.setWordWrap(True)
        lbl_issues.setStyleSheet("font-size: 11px;")
        v.addWidget(lbl_issues)

        self._lists[side] = lst
        self._lbl_files[side] = lbl_file
        self._lbl_issues[side] = lbl_issues
        return group

    def _show_creds(self, side):
        # 1 - VERIFICO QUE EL LADO TENGA CONFIG:
        cfg = self._configs.get(side)
        if not cfg:
            QMessageBox.information(
                self, f"{ICON_INFO} Sin archivo", "Ese lado no tiene kubeconfig cargado"
            )
            return

        # 2 - ABRO EL VISOR DE CREDENCIALES:
        titulo = f"Credenciales - {'Origen' if side == 'left' else 'Destino'}"
        dlg = KubeconfigCredsDialog(cfg, titulo, self)
        dlg.exec()

    def _open_file(self, side):
        # 1 - PIDO EL ARCHIVO:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Abrir kubeconfig ({'origen' if side == 'left' else 'destino'})",
            "",
            "Todos (*);;YAML (*.yaml *.yml)",
        )
        if not path:
            return

        # 2 - LEO Y VALIDO ANTES DE ACEPTAR EL ARCHIVO:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            QMessageBox.critical(self, f"{ICON_WARN} Error", f"No se pudo leer el archivo:\n{e}")
            return

        if not isinstance(cfg, dict):
            QMessageBox.warning(self, f"{ICON_WARN} Invalido", "El archivo no es un kubeconfig valido (no hay mapping YAML)")
            return
        if not (cfg.get("contexts") or cfg.get("clusters")):
            QMessageBox.warning(self, f"{ICON_WARN} Invalido", "El archivo no tiene contexts ni clusters")
            return

        # 3 - GUARDO Y RENDERIZO:
        self._configs[side] = cfg
        self._paths[side] = path
        self._lbl_files[side].setText(path)
        self._render_side(side)

        # 4 - MUESTRO LOS PROBLEMAS DETECTADOS EN EL LOG Y EN EL LABEL:
        issues = self._main._validate_kubeconfig(cfg)
        if issues:
            self._lbl_issues[side].setText(
                f"{ICON_WARN} {len(issues)} problema(s) de validacion (detalle en el log)"
            )
            self._lbl_issues[side].setStyleSheet("font-size: 11px; color: #f39c12;")
            for sev, msg in issues:
                self._log(f"[{sev}] {msg}")
        else:
            self._lbl_issues[side].setText(f"{ICON_OK} Estructura valida")
            self._lbl_issues[side].setStyleSheet("font-size: 11px; color: #2ecc71;")
            self._log(f"OK: {os.path.basename(path)} valido ({len(cfg.get('contexts') or [])} contexts)")

    def _render_side(self, side):
        # 1 - LIMPIO Y REDIBUJO LOS CONTEXTS COMO BOXES CON BOTON PROBAR:
        lst = self._lists[side]
        lst.clear()
        cfg = self._configs.get(side)
        if not cfg:
            return

        cluster_names = {c.get("name") for c in (cfg.get("clusters") or [])}
        user_names = {u.get("name") for u in (cfg.get("users") or [])}

        for ctx in cfg.get("contexts") or []:
            name = ctx.get("name", "(sin nombre)")
            cd = ctx.get("context") or {}
            broken = []
            if cd.get("cluster") not in cluster_names:
                broken.append(f"cluster '{cd.get('cluster')}' no existe")
            if cd.get("user") and cd.get("user") not in user_names:
                broken.append(f"user '{cd.get('user')}' no existe")

            # 2 - TEXTO DEL BOX; SI HAY REFERENCIAS ROTAS LO AVISO:
            if broken:
                txt = f"{ICON_WARN}  {name}   [{'; '.join(broken)}]"
            else:
                ns = cd.get("namespace") or "sin ns"
                txt = f"{ICON_CONTEXT}  {name}   ({cd.get('cluster', '-')} / {cd.get('user') or '-'} / {ns})"

            # 2a - TOOLTIP CON EL SERVER REAL (para identificar cada cluster):
            cluster_entry = next(
                (c for c in (cfg.get("clusters") or []) if c.get("name") == cd.get("cluster")),
                None,
            )
            server = ((cluster_entry or {}).get("cluster") or {}).get("server") or "(sin server)"
            tooltip = (
                f"Context: {name}\n"
                f"Cluster: {cd.get('cluster') or '-'}\n"
                f"Server:  {server}\n"
                f"User:    {cd.get('user') or '-'}\n"
                f"Namespace: {cd.get('namespace') or '(sin definir)'}"
            )

            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setSizeHint(QSize(0, 34))
            lst.addItem(item)
            row = _MergeRow(self, side, name, txt)
            row.lbl_text.setToolTip(tooltip)
            row.setToolTip(tooltip)
            lst.setItemWidget(item, row)

            # 3 - SI YA HAY RESULTADO DE TEST, LO PINTO:
            saved = self._test_results.get((side, name))
            if saved:
                row.set_result(saved[0], saved[1])

    def test_context(self, side, ctx_name):
        # 1 - VERIFICO QUE EL LADO TENGA CONFIG:
        cfg = self._configs.get(side)
        if not cfg:
            return

        # 2 - NAMESPACE DEL CONTEXT (o default) Y DIR BASE PARA RUTAS RELATIVAS:
        ctx_entry = next(
            (c for c in (cfg.get("contexts") or []) if c.get("name") == ctx_name),
            None,
        )
        ns = ((ctx_entry or {}).get("context") or {}).get("namespace") or "default"
        base_dir = os.path.dirname(self._paths.get(side) or "") or "."

        # 3 - LANZO EL TEST EN BACKGROUND (copia del config para thread-safety):
        import copy
        task = _MergeTestTask(side, ctx_name, copy.deepcopy(cfg), ns, base_dir, self._test_signals)
        self._test_pool.start(task)

    def _find_row(self, side, ctx_name):
        # 1 - BUSCO LA FILA ACTUAL DE ESE CONTEXT EN LA LISTA:
        lst = self._lists.get(side)
        if not lst:
            return None
        for i in range(lst.count()):
            item = lst.item(i)
            if item.data(Qt.UserRole) == ctx_name:
                try:
                    return lst.itemWidget(item)
                except RuntimeError:
                    return None
        return None

    def _on_merge_test_done(self, side, ctx_name, estado, detalle):
        # 1 - GUARDO EL RESULTADO Y ACTUALIZO LA FILA:
        self._test_results[(side, ctx_name)] = (estado, detalle)
        row = self._find_row(side, ctx_name)
        if row:
            row.set_result(estado, detalle)

        # 1a - EN ERRORES DE PERMISOS, LOGUEO EL DETALLE (dice quien sos segun el server):
        if estado in ("denied", "auth"):
            lado = "izquierda" if side == "left" else "derecha"
            self._log(f"[{lado}] {ctx_name}: {detalle} (mensaje completo en la consola)")

        # 2 - AUTO-FIX: SI FALLO Y EL OTRO ARCHIVO TIENE EL MISMO USER,
        #     LO COPIO (una sola vez por context) Y RE-TESTEO:
        if estado in ("denied", "fail", "auth"):
            if (side, ctx_name) in self._fix_tried:
                return
            if self._autofix_dependencies(side, ctx_name):
                self._fix_tried.add((side, ctx_name))
                self._log(f"Re-testeando '{ctx_name}' con dependencias del otro archivo...")
                self.test_context(side, ctx_name)

    def _autofix_dependencies(self, side, ctx_name):
        """Copia del otro lado el cluster/user que falten o difieran. Retorna True si cambio algo."""
        import copy
        other = "right" if side == "left" else "left"
        src_cfg = self._configs.get(side)
        other_cfg = self._configs.get(other)
        if not src_cfg or not other_cfg:
            return False

        ctx_entry = next(
            (c for c in (src_cfg.get("contexts") or []) if c.get("name") == ctx_name),
            None,
        )
        if not ctx_entry:
            return False
        cd = ctx_entry.get("context") or {}
        cambio = False

        # 1 - CLUSTER FALTANTE EN ESTE LADO: LO COPIO DEL OTRO:
        cl_name = cd.get("cluster")
        if cl_name and cl_name not in {c.get("name") for c in (src_cfg.get("clusters") or [])}:
            other_cluster = next(
                (c for c in (other_cfg.get("clusters") or []) if c.get("name") == cl_name),
                None,
            )
            if other_cluster:
                src_cfg.setdefault("clusters", []).append(copy.deepcopy(other_cluster))
                self._log(f"Cluster '{cl_name}' copiado desde el otro archivo")
                cambio = True

        # 2 - USER FALTANTE O DISTINTO: LO COPIO DEL OTRO ARCHIVO:
        usr_name = cd.get("user")
        if usr_name:
            my_user = next(
                (u for u in (src_cfg.get("users") or []) if u.get("name") == usr_name),
                None,
            )
            other_user = next(
                (u for u in (other_cfg.get("users") or []) if u.get("name") == usr_name),
                None,
            )
            if other_user and (not my_user or my_user != other_user):
                # 2a - REEMPLAZO EL USER DE ESTE LADO POR EL DEL OTRO ARCHIVO:
                src_cfg["users"] = [u for u in (src_cfg.get("users") or []) if u.get("name") != usr_name]
                src_cfg.setdefault("users", []).append(copy.deepcopy(other_user))
                self._log(f"User '{usr_name}' copiado desde el otro archivo")
                cambio = True

        if cambio:
            self._render_side(side)
        return cambio

    def move_context(self, src, dst, ctx_name):
        # 1 - VERIFICO QUE EL ORIGEN TENGA CONFIG:
        src_cfg = self._configs.get(src)
        if not src_cfg:
            return

        # 2 - SI EL DESTINO NO TIENE ARCHIVO, OFREZCO CREAR UNO VACIO:
        dst_cfg = self._configs.get(dst)
        if not dst_cfg:
            reply = QMessageBox.question(
                self,
                f"{ICON_INFO} Crear kubeconfig destino",
                f"El lado {'destino' if dst == 'right' else 'origen'} no tiene archivo abierto.\n"
                f"¿Crear un kubeconfig nuevo vacio y mover ahi '{ctx_name}'?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            dst_cfg = {"apiVersion": "v1", "kind": "Config", "clusters": [], "contexts": [], "users": []}
            self._configs[dst] = dst_cfg

        # 3 - BUSCO EL CONTEXT EN EL ORIGEN:
        contexts = src_cfg.get("contexts") or []
        ctx_entry = next((c for c in contexts if c.get("name") == ctx_name), None)
        if not ctx_entry:
            return
        cd = ctx_entry.get("context") or {}

        # 4 - SI YA EXISTE EN EL DESTINO, NO HAGO NADA:
        dst_ctx_names = {c.get("name") for c in (dst_cfg.get("contexts") or [])}
        if ctx_name in dst_ctx_names:
            self._log(f"AVISO: el context '{ctx_name}' ya existe en el destino: no se movio")
            return

        # 5 - COPIO EL CLUSTER Y EL USER SI FALTAN EN EL DESTINO:
        import copy
        agregados = []
        cl_name = cd.get("cluster")
        if cl_name and cl_name not in {c.get("name") for c in (dst_cfg.get("clusters") or [])}:
            src_cluster = next((c for c in (src_cfg.get("clusters") or []) if c.get("name") == cl_name), None)
            if src_cluster:
                dst_cfg.setdefault("clusters", []).append(copy.deepcopy(src_cluster))
                agregados.append(f"cluster '{cl_name}'")
            else:
                self._log(f"AVISO: el context referencia al cluster '{cl_name}' que no existe en el origen")

        usr_name = cd.get("user")
        if usr_name and usr_name not in {u.get("name") for u in (dst_cfg.get("users") or [])}:
            src_user = next((u for u in (src_cfg.get("users") or []) if u.get("name") == usr_name), None)
            if src_user:
                dst_cfg.setdefault("users", []).append(copy.deepcopy(src_user))
                agregados.append(f"user '{usr_name}'")

        # 6 - MUEVO EL CONTEXT (lo saco del origen):
        contexts.remove(ctx_entry)
        dst_cfg.setdefault("contexts", []).append(copy.deepcopy(ctx_entry))

        # 7 - SI EL CURRENT-CONTEXT DEL ORIGEN SE FUE, LO LIMPIO:
        if src_cfg.get("current-context") == ctx_name:
            src_cfg.pop("current-context", None)

        # 8 - RE-RENDERIZO AMBOS LADOS:
        self._render_side(src)
        self._render_side(dst)
        msg = f"Context '{ctx_name}' movido"
        if agregados:
            msg += " (+" + ", ".join(agregados) + ")"
        self._log(msg)

    def _save_side(self, side):
        # 1 - VERIFICO QUE HAYA ALGO PARA GUARDAR:
        cfg = self._configs.get(side)
        path = self._paths.get(side)
        if not cfg:
            QMessageBox.information(self, f"{ICON_INFO} Nada que guardar", "Ese lado no tiene kubeconfig cargado")
            return

        # 2 - VALIDO ANTES DE ESCRIBIR:
        issues = self._main._validate_kubeconfig(cfg)
        errores = [m for sev, m in issues if sev == "ERROR"]
        if errores:
            reply = QMessageBox.question(
                self,
                f"{ICON_WARN} El kubeconfig tiene errores",
                "El kubeconfig tiene errores de validacion:\n\n"
                + "\n".join(f"  - {m}" for m in errores[:5])
                + "\n\n¿Guardar de todos modos?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # 3 - ELIJO DONDE GUARDAR:
        path = self._paths.get(side)
        if path:
            reply = QMessageBox.question(
                self,
                f"{ICON_WARN} Sobrescribir",
                f"¿Sobrescribir el archivo?\n\n{path}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Guardar kubeconfig como", "kubeconfig-merge.yaml", "Todos (*);;YAML (*.yaml *.yml)")
            if not path:
                return

        # 4 - ESCRIBO EL YAML:
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)
            self._paths[side] = path
            self._lbl_files[side].setText(path)
            self._log(f"Guardado: {path}")
        except Exception as e:
            QMessageBox.critical(self, f"{ICON_WARN} Error", f"No se pudo guardar:\n{e}")

    def _log(self, msg):
        # 1 - AGREGO UNA LINEA AL LOG DEL DIALOGO:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{stamp}] {msg}")


class KubeconfigCredsDialog(QDialog):
    """Lista los users de un kubeconfig: a que contexts/clusters pertenecen,
    sus credenciales ocultas y un boton amarillo para copiar cada una."""

    BTN_YELLOW = (
        "QPushButton { background-color: #f5c518; color: #111; font-weight: bold;"
        " font-size: 11px; padding: 2px 12px; border: none; border-radius: 3px; }"
        "QPushButton:hover { background-color: #ffd633; }"
        "QPushButton:disabled { background-color: #665c33; color: #333; }"
    )

    def __init__(self, cfg, titulo, parent=None):
        super().__init__(parent)
        self._cfg = cfg or {}

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_USER}  {titulo}")
        self.resize(780, 620)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")
        layout = QVBoxLayout(self)

        # 2 - INDEXO CONTEXTS Y CLUSTERS POR USER:
        clusters = {
            c.get("name"): ((c.get("cluster") or {}).get("server") or "-")
            for c in (self._cfg.get("clusters") or [])
        }
        contexts_by_user = {}
        for ctx in self._cfg.get("contexts") or []:
            cd = ctx.get("context") or {}
            contexts_by_user.setdefault(cd.get("user"), []).append(
                (ctx.get("name", "?"), cd.get("cluster") or "-", clusters.get(cd.get("cluster"), "-"))
            )

        # 3 - SCROLL CON UN GRUPO POR USER:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        v = QVBoxLayout(container)
        v.setSpacing(10)
        users = self._cfg.get("users") or []
        if not users:
            v.addWidget(QLabel("(este kubeconfig no define users)"))
        for u in users:
            v.addWidget(self._build_user_group(u, contexts_by_user.get(u.get("name"), [])))
        v.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # 3 - BOTON CERRAR:
        btn_row = QHBoxLayout()
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _build_user_group(self, user_entry, usos):
        # 1 - GRUPO DEL USER:
        name = user_entry.get("name", "(sin nombre)")
        ud = user_entry.get("user") or {}
        group = QGroupBox(f"{ICON_USER}  {name}")
        group.setStyleSheet(
            "QGroupBox { border: 1px solid #f5c518; border-radius: 6px; margin-top: 10px;"
            " padding-top: 6px; font-weight: bold; }"
            "QGroupBox::title { color: #f5c518; }"
        )
        v = QVBoxLayout(group)
        v.setSpacing(4)

        # 2 - A QUE CONTEXTS/CLUSTERS PERTENECE:
        if usos:
            for ctx_name, cluster_name, server in usos:
                lbl = QLabel(f"{ICON_CONTEXT}  {ctx_name}  →  cluster '{cluster_name}'  ({server})")
                lbl.setStyleSheet("font-size: 12px; color: #bbb; background: transparent; border: none;")
                lbl.setWordWrap(True)
                v.addWidget(lbl)
        else:
            lbl = QLabel(f"{ICON_WARN}  ningun context usa este user")
            lbl.setStyleSheet("font-size: 12px; color: #e67e22; background: transparent; border: none;")
            v.addWidget(lbl)

        # 3 - CREDENCIALES OCULTAS CON BOTON COPIAR:
        fields = self._cred_fields(ud)
        if not fields:
            lbl = QLabel("(sin credenciales estaticas)")
            lbl.setStyleSheet("font-size: 12px; color: #888; background: transparent; border: none;")
            v.addWidget(lbl)
        for field_name, value in fields:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl_field = QLabel(field_name)
            lbl_field.setStyleSheet("font-size: 11px; color: #888; background: transparent; border: none;")
            lbl_field.setMinimumWidth(150)
            lbl_val = QLabel(self._mask(value))
            lbl_val.setStyleSheet("font-size: 11px; font-family: Consolas, monospace; color: #ccc; background: transparent; border: none;")
            btn = QPushButton("Copiar")
            btn.setStyleSheet(self.BTN_YELLOW)
            btn.setToolTip("Copiar la credencial completa al portapapeles")
            btn.clicked.connect(lambda _, val=value, b=btn: self._copy(val, b))
            row.addWidget(lbl_field)
            row.addWidget(lbl_val, stretch=1)
            row.addWidget(btn)
            v.addLayout(row)

        # 4 - COPIAR EL USER COMPLETO EN YAML (para pegar en otro kubeconfig):
        btn_yaml = QPushButton("Copiar user completo (YAML)")
        btn_yaml.setStyleSheet(self.BTN_YELLOW)
        btn_yaml.setToolTip("Copia la entrada completa del user en YAML para pegarla en otro kubeconfig")
        btn_yaml.clicked.connect(
            lambda _, u=user_entry, b=btn_yaml: self._copy(
                yaml.safe_dump(u, sort_keys=False, default_flow_style=False), b
            )
        )
        v.addWidget(btn_yaml)
        return group

    def _cred_fields(self, ud):
        # 1 - JUNTO TODOS LOS CAMPOS DE CREDENCIAL DEL USER:
        fields = []
        if ud.get("token"):
            fields.append(("token", ud.get("token")))
        if ud.get("tokenFile"):
            fields.append(("tokenFile", ud.get("tokenFile")))
        if ud.get("client-certificate-data"):
            fields.append(("client-certificate-data (b64)", ud.get("client-certificate-data")))
        if ud.get("client-key-data"):
            fields.append(("client-key-data (b64)", ud.get("client-key-data")))
        if ud.get("client-certificate"):
            fields.append(("client-certificate (archivo)", ud.get("client-certificate")))
        if ud.get("client-key"):
            fields.append(("client-key (archivo)", ud.get("client-key")))
        if ud.get("username"):
            fields.append(("username", ud.get("username")))
        if ud.get("password"):
            fields.append(("password", ud.get("password")))
        ap = (ud.get("auth-provider") or {}).get("config") or {}
        if ap.get("id-token"):
            fields.append(("auth-provider id-token", ap.get("id-token")))
        if ap.get("access-token"):
            fields.append(("auth-provider access-token", ap.get("access-token")))
        if ap.get("client-secret"):
            fields.append(("auth-provider client-secret", ap.get("client-secret")))
        if ud.get("exec"):
            ex = ud.get("exec") or {}
            cmd = " ".join([ex.get("command", "")] + [str(a) for a in (ex.get("args") or [])])
            fields.append(("exec plugin (comando)", cmd))
        return fields

    def _mask(self, value):
        # 1 - OCULTO EL VALOR: MUESTRO INICIO, FIN Y LONGITUD:
        s = str(value)
        if len(s) <= 12:
            return "•" * len(s)
        return f"{s[:6]}••••••••{s[-4:]}   ({len(s)} caracteres)"

    def _copy(self, value, btn=None):
        # 1 - COPIO AL PORTAPAPELES Y DOY FEEDBACK VISUAL:
        QGuiApplication.clipboard().setText(str(value))
        if btn:
            btn.setText("✓ Copiado")
            QTimer.singleShot(1200, lambda: btn.setText("Copiar"))


# 1 - FUNCION PARA ACORTAR MENSAJES DE ERROR LARGOS (urllib3, DNS, etc):
def _short_error(e):
    # 1 - SI ES MaxRetryError, EXTRAIGO EL HOST Y LA CAUSA:
    msg = str(e)
    if "MaxRetryError" in msg or "NameResolutionError" in msg:
        # 1a - BUSCO EL HOST EN EL MENSAJE:
        import re
        host_match = re.search(r"host='([^']+)'", msg)
        host = host_match.group(1) if host_match else "?"
        if "NameResolutionError" in msg or "getaddrinfo failed" in msg:
            return f"No se puede resolver el hostname del cluster: {host}"
        elif "MaxRetryError" in msg:
            return f"No se puede conectar al cluster: {host}"
    # 1b - SI ES MUY LARGO, LO CORTO:
    if len(msg) > 120:
        return msg[:120] + "..."
    return msg


class _ClusterPingSignals(QObject):
    # SENAL PARA REPORTAR EL RESULTADO DEL PING TCP DE UN CLUSTER:
    result = Signal(object, bool)   # (QListWidgetItem, conectado)


class _ClusterPingTask(QRunnable):
    # TAREA EN BACKGROUND: TCP CONNECT AL SERVER DEL CLUSTER
    # (asi no se congela la UI verificando todos los clusters):
    def __init__(self, item, host, port, signals):
        super().__init__()
        self._item = item
        self._host = host
        self._port = port
        self._signals = signals

    def run(self):
        ok = False
        try:
            sock = socket.create_connection((self._host, self._port), timeout=2)
            sock.close()
            ok = True
        except Exception:
            ok = False
        self._signals.result.emit(self._item, ok)


# 2 - SENALES Y TASKS PARA LLAMADAS A LA API DE KUBERNETES EN BACKGROUND:
class _ApiSignals(QObject):
    # SENAL: ok=True/False, data=resultado o mensaje de error:
    done = Signal(bool, object)


class _ConnectTask(QRunnable):
    # TASK: carga el kubeconfig + lista namespaces en background (con timeout):
    def __init__(self, file_path, context_name, signals):
        super().__init__()
        self._file_path = file_path
        self._context_name = context_name
        self._signals = signals

    def run(self):
        try:
            # 1 - CARGO EL KUBECONFIG CON EL CONTEXT SELECCIONADO:
            print(f"[MiniLens] Conectando: context='{self._context_name}' file='{self._file_path}'")
            config.load_kube_config(
                config_file=self._file_path,
                context=self._context_name,
            )

            # 2 - CREO EL CLIENTE (el timeout se pasa en cada llamada via _request_timeout):
            api_client = client.ApiClient()
            v1 = client.CoreV1Api(api_client)

            # 3 - LISTO LOS NAMESPACES (con timeout de 10s):
            #     Si da 403 NO es un error de conexion: el server respondio,
            #     solo que el usuario no tiene permiso para listar namespaces
            #     (RBAC restrictivo). Sigo con lista vacia y el combo usa
            #     los namespaces de los contexts como fallback:
            names = []
            try:
                ns_list = v1.list_namespace(_request_timeout=10)
                names = sorted(ns.metadata.name for ns in ns_list.items)
                print(f"[MiniLens] list_namespace OK: {len(names)} namespaces")
            except ApiException as e:
                print(f"[MiniLens] list_namespace fallo (codigo {e.status}): {e.reason} -> fallback a namespaces del context")
                if e.status != 403:
                    # 401 u otro codigo de API = problema real de auth/permisos:
                    self._signals.done.emit(False, ("api", e.status, e.reason))
                    return
                names = []

            print(f"[MiniLens] Conexion OK a context='{self._context_name}'")
            self._signals.done.emit(True, (v1, names))
        except ApiException as e:
            print(f"[MiniLens] ApiException al conectar (codigo {e.status}): {e.reason}")
            self._signals.done.emit(False, ("api", e.status, e.reason))
        except Exception as e:
            print(f"[MiniLens] Error al conectar: {_short_error(e)}")
            self._signals.done.emit(False, ("conn", _short_error(e)))


class _LoadResourcesTask(QRunnable):
    # TASK: lista pods y services del namespace en background (con timeout):
    def __init__(self, v1, namespace, signals):
        super().__init__()
        self._v1 = v1
        self._namespace = namespace
        self._signals = signals

    def run(self):
        try:
            # 1 - LISTO PODS DEL NAMESPACE (con timeout de 15s):
            print(f"[MiniLens] Listando pods/services de namespace='{self._namespace}'...")
            pod_list = self._v1.list_namespaced_pod(
                namespace=self._namespace,
                _request_timeout=15,
            )

            # 2 - LISTO SERVICES DEL NAMESPACE:
            svc_list = self._v1.list_namespaced_service(
                namespace=self._namespace,
                _request_timeout=15,
            )

            print(f"[MiniLens] Recursos OK: {len(pod_list.items)} pods, {len(svc_list.items)} services en '{self._namespace}'")
            self._signals.done.emit(True, (pod_list.items, svc_list.items))
        except ApiException as e:
            print(f"[MiniLens] ApiException al listar recursos (codigo {e.status}): {_api_error_message(e)}")
            self._signals.done.emit(False, ("api", e.status, e.reason, _api_error_message(e)))
        except Exception as e:
            print(f"[MiniLens] Error al listar recursos: {_short_error(e)}")
            self._signals.done.emit(False, ("conn", _short_error(e)))


class _DiscoveryTask(QRunnable):
    # TASK: lista todos los pods de todos los namespaces del cluster (discovery):
    def __init__(self, v1, signals, known_namespaces=None):
        super().__init__()
        self._v1 = v1
        self._signals = signals
        self._known_ns = [n for n in (known_namespaces or []) if n]

    def run(self):
        try:
            # 1 - INTENTO LISTAR TODOS LOS PODS/SERVICES DE TODOS LOS NAMESPACES:
            try:
                print("[MiniLens] Discovery: listando pods/services de TODOS los namespaces...")
                pod_items = self._v1.list_pod_for_all_namespaces(_request_timeout=20).items
                svc_items = self._v1.list_service_for_all_namespaces(_request_timeout=20).items
            except ApiException as e:
                # 1a - SIN PERMISO CLUSTER-WIDE (403): FALLBACK a escanear uno
                #      por uno los namespaces conocidos (contexts del kubeconfig
                #      + el actual), que es lo mismo que hace OpenLens:
                if e.status != 403:
                    raise
                print(f"[MiniLens] Discovery cluster-wide bloqueado (403): escaneo {len(self._known_ns)} namespaces conocidos uno por uno")
                pod_items = []
                svc_items = []
                for ns in self._known_ns:
                    try:
                        pods_ns = self._v1.list_namespaced_pod(namespace=ns, _request_timeout=10)
                        svcs_ns = self._v1.list_namespaced_service(namespace=ns, _request_timeout=10)
                        pod_items.extend(pods_ns.items)
                        svc_items.extend(svcs_ns.items)
                        print(f"[MiniLens] Discovery ns '{ns}': {len(pods_ns.items)} pods, {len(svcs_ns.items)} svcs")
                    except ApiException as e2:
                        # 403/401 en UN namespace: lo salteo y sigo con el resto:
                        print(f"[MiniLens] Discovery: namespace '{ns}' salteado (codigo {e2.status})")
                        continue

            # 2 - AGRUPO PODS POR NAMESPACE:
            ns_pods = {}
            for pod in pod_items:
                ns = pod.metadata.namespace or "?"
                ns_pods.setdefault(ns, []).append(pod)

            # 3 - AGRUPO SERVICES POR NAMESPACE:
            ns_svcs = {}
            for svc in svc_items:
                ns = svc.metadata.namespace or "?"
                ns_svcs.setdefault(ns, []).append(svc)

            # 4 - CONSTRUYO RESUMEN: lista de (namespace, n_pods, n_svcs, pod_names):
            summary = []
            all_ns = sorted(set(list(ns_pods.keys()) + list(ns_svcs.keys())))
            for ns in all_ns:
                pods_in_ns = ns_pods.get(ns, [])
                svcs_in_ns = ns_svcs.get(ns, [])
                # 4a - PRIMEROS 5 NOMBRES DE PODS COMO PREVIEW:
                pod_names = [p.metadata.name for p in pods_in_ns[:5]]
                summary.append((ns, len(pods_in_ns), len(svcs_in_ns), pod_names))

            self._signals.done.emit(True, summary)
        except ApiException as e:
            print(f"[MiniLens] Discovery ApiException (codigo {e.status}): {e.reason}")
            self._signals.done.emit(False, ("api", e.status, e.reason, _api_error_message(e)))
        except Exception as e:
            print(f"[MiniLens] Discovery error: {_short_error(e)}")
            self._signals.done.emit(False, ("conn", _short_error(e)))


class KubeconfigViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_CLUSTER} MiniLens - Kubernetes Explorer")
        self.resize(1500, 950)

        # 1a - SETEO EL ICONO DE LA VENTANA DESDE EL SVG:
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "minilens_logo.svg")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))

        # 2 - APLICO EL TEMA:
        app = QApplication.instance()
        app.setStyleSheet(STYLESHEET)

        # 3 - INICIALIZO LA BASE DE DATOS:
        dbmod.init_db()

        # 4 - ESTADO:
        self.config = None
        self.current_context_name = None
        self._loaded_file_path = None
        self._pods_cache = {}
        self._current_kubeconfig_id = None
        self._current_contexts = []
        self._error_log = []
        self._import_log = []

        # 4a - THREAD POOL Y SENALES PARA EL PING TCP DE CLUSTERS:
        self._ping_pool = QThreadPool()
        self._ping_signals = _ClusterPingSignals()
        self._ping_signals.result.connect(self._on_cluster_ping_result)

        # 4b - THREAD POOL Y SENALES PARA LLAMADAS A LA API EN BACKGROUND:
        self._api_pool = QThreadPool()
        self._api_pool.setMaxThreadCount(2)
        self._connect_signals = _ApiSignals()
        self._connect_signals.done.connect(self._on_connect_done)
        self._resources_signals = _ApiSignals()
        self._resources_signals.done.connect(self._on_resources_done)
        self._discovery_signals = _ApiSignals()
        self._discovery_signals.done.connect(self._on_discovery_done)

        # 4c - CACHE DE ESTADO DE CONTEXTS (solo se llena al conectar de verdad):
        #      {context_name: (estado, n_pods)} - estado: ok/denied/fail:
        self._context_scan_cache = {}

        # 5 - WIDGET CENTRAL:
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # 6 - HOTBAR (barra izquierda):
        self.hotbar = Hotbar()
        self.hotbar.set_callbacks(
            on_click=self.on_hotbar_item_clicked,
            on_unpin=self.on_hotbar_item_unpinned,
            on_edit=self.on_hotbar_item_edit,
            on_drop=self._on_cluster_dropped,
        )
        root_layout.addWidget(self.hotbar)

        # 7 - CONTENIDO PRINCIPAL (derecha de la hotbar):
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)
        root_layout.addWidget(main_widget, stretch=1)

        # 8 - BARRA SUPERIOR CON BOTONES:
        top_bar = QHBoxLayout()
        self.btn_load = QPushButton(f"{ICON_FILE}  Cargar ~/.kube/config")
        self.btn_load.clicked.connect(self.on_load)
        top_bar.addWidget(self.btn_load)

        self.btn_copy_user = QPushButton(f"{ICON_USER}  Importar a ~/.kube/config")
        self.btn_copy_user.clicked.connect(self.on_import_to_user_config)
        self.btn_copy_user.setEnabled(False)
        top_bar.addWidget(self.btn_copy_user)

        # BOTON DE MERGE: abre la ventana para pasar contexts entre
        # 2 kubeconfigs arrastrando (con validacion previa):
        self.btn_merge = QPushButton(f"{ICON_FILE}  Fusionar kubeconfigs")
        self.btn_merge.setToolTip("Abrir 2 kubeconfigs y pasar contexts de uno al otro (drag & drop)")
        self.btn_merge.clicked.connect(self.on_open_merge)
        top_bar.addWidget(self.btn_merge)

        # BOTON DE LOG DE IMPORTACION: muestra que se detecto/valido/fallo
        # al cargar cada kubeconfig (claves duplicadas, elements faltantes):
        self.btn_import_log = QPushButton(f"{ICON_INFO}  Log import")
        self.btn_import_log.setToolTip("Ver el log de importacion/validacion de kubeconfigs")
        self.btn_import_log.clicked.connect(self.on_open_import_log)
        top_bar.addWidget(self.btn_import_log)

        # BOTON LOGOUT OIDC: borra la cache de tokens de kubelogin
        # (~/.kube/cache/oidc-login) para forzar re-login en el navegador
        # (util si quedo cacheada la sesion de otro usuario, ej: ngrossi):
        self.btn_oidc_logout = QPushButton(f"{ICON_CONTEXT}  Logout OIDC")
        self.btn_oidc_logout.setToolTip(
            "Borra la cache de tokens de kubelogin (~/.kube/cache/oidc-login).\n"
            "La proxima conexion a un context OIDC va a pedir login en el navegador."
        )
        self.btn_oidc_logout.clicked.connect(self.on_oidc_logout)
        top_bar.addWidget(self.btn_oidc_logout)

        top_bar.addStretch()

        # BOTON LIMPIAR: resetea todo lo cargado para empezar de cero
        # (la hotbar no se toca: los clusters anclados viven en la DB):
        self.btn_clear = QPushButton(f"{ICON_TRASH}  Limpiar")
        self.btn_clear.setToolTip("Limpia la config cargada (clusters, contexts, pods, services)")
        self.btn_clear.clicked.connect(self.on_clear_config)
        top_bar.addWidget(self.btn_clear)

        layout.addLayout(top_bar)

        # 9 - TOP: drag&drop + metadatos + import panel (3 columnas):
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # 9a - DRAG & DROP:
        self.dropzone = DropZone()
        self.dropzone.set_parent_window(self)
        self.dropzone.setMinimumHeight(56)
        self.dropzone.setMaximumHeight(120)
        self.dropzone.setText(
            f"{ICON_FILE}  Arrastra kubeconfig\n(.yaml / .yml)"
        )
        top_row.addWidget(self.dropzone, stretch=1)

        # 9b - METADATOS:
        meta_group = QGroupBox(f"{ICON_INFO}  Metadatos")
        meta_group.setMaximumHeight(120)
        meta_form = QFormLayout(meta_group)
        meta_form.setContentsMargins(8, 4, 8, 4)
        meta_form.setSpacing(2)
        self.lbl_file_path = QLabel("-")
        self.lbl_file_path.setWordWrap(True)
        self.lbl_api_version = QLabel("-")
        self.lbl_kind = QLabel("-")
        self.lbl_current_context = QLabel("-")
        self.lbl_current_context.setWordWrap(True)
        for lbl in [self.lbl_file_path, self.lbl_api_version, self.lbl_kind, self.lbl_current_context]:
            lbl.setStyleSheet("font-size: 12px; color: #f5c518;")
        meta_form.addRow("Archivo:", self.lbl_file_path)
        meta_form.addRow("apiVersion:", self.lbl_api_version)
        meta_form.addRow("kind:", self.lbl_kind)
        meta_form.addRow("current-context:", self.lbl_current_context)
        top_row.addWidget(meta_group, stretch=1)

        # 9c - USERS (arriba a la derecha, compacto):
        users_group = QGroupBox(f"{ICON_USER}  Users")
        users_group.setMaximumHeight(120)
        users_layout = QVBoxLayout(users_group)
        users_layout.setContentsMargins(6, 4, 6, 4)
        self.table_users = QTableWidget(0, 2)
        self.table_users.setHorizontalHeaderLabels(["Usuario", "Entorno (clusters)"])
        self.table_users.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_users.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_users.verticalHeader().setDefaultSectionSize(22)
        self.table_users.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_users.doubleClicked.connect(self.on_user_double_click)
        users_layout.addWidget(self.table_users)
        top_row.addWidget(users_group, stretch=1)

        layout.addLayout(top_row)

        # 10 - AREA PRINCIPAL: Clusters+Contexts (~30%) | Detalle/Mapa (~70%):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 10a - IZQUIERDA: Clusters + Contexts apilados:
        left_panel = QWidget()
        left_panel.setMinimumWidth(220)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        col1_group = QGroupBox(f"{ICON_CLUSTER}  Clusters")
        col1_layout = QVBoxLayout(col1_group)
        col1_layout.setContentsMargins(6, 6, 6, 6)
        self.list_clusters = ClusterListWidget()
        self.list_clusters.parent_window = self
        self.list_clusters.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.list_clusters.currentItemChanged.connect(self.on_cluster_selected)
        col1_layout.addWidget(self.list_clusters)
        left_layout.addWidget(col1_group, stretch=1)

        col2_group = QGroupBox(f"{ICON_CONTEXT}  Contexts")
        col2_layout = QVBoxLayout(col2_group)
        col2_layout.setContentsMargins(6, 6, 6, 6)

        # BUSCADOR DE CONTEXTS: filtra la lista mientras escribis,
        # con una X integrada para limpiar la busqueda:
        self.txt_search_contexts = QLineEdit()
        self.txt_search_contexts.setPlaceholderText("Buscar context...")
        self.txt_search_contexts.setClearButtonEnabled(True)
        self.txt_search_contexts.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #555; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
        )
        self.txt_search_contexts.textChanged.connect(self._render_contexts)
        col2_layout.addWidget(self.txt_search_contexts)

        self.list_contexts = QListWidget()
        self.list_contexts.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.list_contexts.currentItemChanged.connect(self.on_context_selected)
        col2_layout.addWidget(self.list_contexts)

        # BOTON AGREGAR CONTEXT: abre un dialogo para crear un context nuevo
        # a mano (cluster/user existentes o cluster nuevo) y guardarlo en el
        # kubeconfig cargado. Util cuando el usuario no puede listar
        # namespaces (RBAC) y necesita un context por namespace:
        self.btn_add_context = QPushButton(f"{ICON_PLUS}  Agregar context")
        self.btn_add_context.setToolTip(
            "Crear un context nuevo en el kubeconfig cargado:\n"
            "elegi cluster (o uno nuevo), user y namespace."
        )
        self.btn_add_context.clicked.connect(self.on_add_context)
        self.btn_add_context.setEnabled(False)
        col2_layout.addWidget(self.btn_add_context)

        left_layout.addWidget(col2_group, stretch=2)

        splitter.addWidget(left_panel)

        # 10b - DERECHA: Detalle del context:
        col3_group = QGroupBox(f"{ICON_DETAIL}  Detalle del context")
        col3_layout = QVBoxLayout(col3_group)
        col3_layout.setContentsMargins(6, 6, 6, 6)
        col3_layout.setSpacing(4)

        # Context info compacto en una linea (valores elipsados y
        # cliqueables: un clic copia el texto completo):
        ctx_bar = QHBoxLayout()
        self.lbl_ctx_name = ElideLabel("-")
        self.lbl_ctx_namespace = ElideLabel("-")
        self.lbl_ctx_user = ElideLabel("-")
        self.lbl_ctx_cluster = ElideLabel("-")
        for lbl in [self.lbl_ctx_name, self.lbl_ctx_namespace, self.lbl_ctx_user, self.lbl_ctx_cluster]:
            lbl.setObjectName("detail_value")
            lbl.setStyleSheet("font-size: 12px; color: #f5c518; font-weight: bold;")

        def _titulo(texto):
            t = QLabel(texto)
            t.setStyleSheet("color: #aaa; font-size: 11px;")
            return t

        ctx_bar.addWidget(_titulo("NS:"))
        self.lbl_ctx_namespace.set_prefix("NS")
        ctx_bar.addWidget(self.lbl_ctx_namespace, stretch=1)
        ctx_bar.addWidget(_titulo("Ctx:"))
        self.lbl_ctx_name.set_prefix("Ctx")
        ctx_bar.addWidget(self.lbl_ctx_name, stretch=1)
        ctx_bar.addWidget(_titulo("User:"))
        self.lbl_ctx_user.set_prefix("User")
        ctx_bar.addWidget(self.lbl_ctx_user, stretch=1)

        # COMBO DE NAMESPACES: al conectar, la app le pregunta al cluster
        # todos los namespaces visibles para el usuario y permite navegar
        # entre ellos sin necesidad de un context por cada uno:
        self.combo_namespaces = QComboBox()
        self.combo_namespaces.setEditable(True)
        self.combo_namespaces.setMinimumWidth(220)
        self.combo_namespaces.setToolTip("Namespaces visibles en el cluster (traidos de la API). Tambien podes tipear uno manualmente si no tenes permiso para listar namespaces.")
        self.combo_namespaces.setStyleSheet(
            "QComboBox { background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #555; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
            "QComboBox QAbstractItemView { background-color: #2a2a2a; color: #e0e0e0; "
            "selection-background-color: #f5c518; selection-color: #1a1a1a; }"
        )
        # DEBOUNCE: al tipear manualmente no dispara en cada tecla, solo 600ms
        # despues de que el usuario deja de escribir. Al seleccionar del
        # dropdown dispara inmediatamente via activated:
        self._ns_debounce = QTimer(self)
        self._ns_debounce.setSingleShot(True)
        self._ns_debounce.setInterval(600)
        self._ns_debounce.timeout.connect(self._ns_debounce_fire)
        self.combo_namespaces.activated.connect(self._ns_pick_immediate)
        self.combo_namespaces.lineEdit().textEdited.connect(self._ns_debounce_start)
        ctx_bar.addWidget(self.combo_namespaces)

        self.btn_test_connection = QPushButton(f"{ICON_REFRESH}")
        self.btn_test_connection.setMaximumWidth(36)
        self.btn_test_connection.setMaximumHeight(28)
        self.btn_test_connection.setToolTip("Refrescar Pods y Services")
        self.btn_test_connection.clicked.connect(self.on_test_connection)
        self.btn_test_connection.setEnabled(False)
        ctx_bar.addWidget(self.btn_test_connection)

        # BOTON PING: hace un TCP connect al server del cluster para
        # verificar si hay ruta / si hace falta VPN:
        self.btn_ping = QPushButton(f"{ICON_PING}")
        self.btn_ping.setMaximumWidth(36)
        self.btn_ping.setMaximumHeight(28)
        self.btn_ping.setToolTip("Verificar conectividad TCP al server del cluster")
        self.btn_ping.clicked.connect(self.on_ping_cluster)
        self.btn_ping.setEnabled(False)
        ctx_bar.addWidget(self.btn_ping)

        # BOTON DISCOVERY: lista todos los pods de todos los namespaces
        # del cluster para descubrir donde estan las cosas:
        self.btn_discovery = QPushButton(f"{ICON_DISCOVERY}")
        self.btn_discovery.setMaximumWidth(36)
        self.btn_discovery.setMaximumHeight(28)
        self.btn_discovery.setToolTip("Discovery: listar pods de TODOS los namespaces del cluster")
        self.btn_discovery.clicked.connect(self.on_discovery)
        self.btn_discovery.setEnabled(False)
        ctx_bar.addWidget(self.btn_discovery)
        col3_layout.addLayout(ctx_bar)

        self.lbl_pods_title = QLabel(f"{ICON_POD}  Recursos:")
        self.lbl_pods_title.setObjectName("detail_value")
        self.lbl_pods_title.setStyleSheet("font-size: 12px; color: #f5c518;")
        col3_layout.addWidget(self.lbl_pods_title)

        # Tabs Lista / Mapa:
        self.resource_tabs = QTabWidget()

        # --- TAB LISTA ---
        list_tab = QWidget()
        list_layout = QVBoxLayout(list_tab)
        list_layout.setContentsMargins(2, 2, 2, 2)
        list_layout.setSpacing(4)

        self.lbl_pods_list_title = QLabel(f"{ICON_POD}  Pods")
        self.lbl_pods_list_title.setObjectName("detail_value")
        list_layout.addWidget(self.lbl_pods_list_title)

        self.table_pods = QTableWidget(0, 6)
        self.table_pods.setHorizontalHeaderLabels(["NAME", "STATUS", "READY", "IP", "AGE", "LOGS"])
        self.table_pods.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_pods.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # IP CON ANCHO FIJO: si es ResizeToContents el boton amarillo colapsa
        # cuando el nombre del pod es muy largo:
        self.table_pods.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_pods.setColumnWidth(3, 130)
        self.table_pods.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_pods.doubleClicked.connect(self.on_pod_double_click)
        self.table_pods.cellClicked.connect(self.on_pod_table_click)
        list_layout.addWidget(self.table_pods, stretch=1)

        self.lbl_services_title = QLabel(f"{ICON_CLUSTER}  Services")
        self.lbl_services_title.setObjectName("detail_value")
        list_layout.addWidget(self.lbl_services_title)

        self.table_services = QTableWidget(0, 5)
        self.table_services.setHorizontalHeaderLabels(["NAME", "TYPE", "CLUSTER IP", "PORTS", "AGE"])
        self.table_services.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_services.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_services.cellClicked.connect(self.on_svc_table_click)
        list_layout.addWidget(self.table_services, stretch=1)

        self.resource_tabs.addTab(list_tab, f"{ICON_DETAIL}  Lista")

        # --- TAB MAPA ---
        map_tab = QWidget()
        map_layout = QVBoxLayout(map_tab)
        map_layout.setContentsMargins(2, 2, 2, 2)
        map_layout.setSpacing(4)

        legend = QHBoxLayout()
        legend.setSpacing(6)
        for status_name in ["Running", "Pending", "Failed", "Unknown"]:
            legend.addWidget(StatusDot(status_name))
            l = QLabel(status_name)
            l.setStyleSheet("font-size: 11px; color: #ccc;")
            legend.addWidget(l)
        legend.addStretch()
        map_layout.addLayout(legend)

        self.map_scroll = QScrollArea()
        self.map_scroll.setWidgetResizable(True)
        self.map_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1a1a1a; }")
        self.map_container = QWidget()
        self.map_flow = FlowLayout(self.map_container, margin=8, hspacing=12, vspacing=12)
        self.map_container.setLayout(self.map_flow)
        self.map_scroll.setWidget(self.map_container)
        map_layout.addWidget(self.map_scroll, stretch=1)

        self.resource_tabs.addTab(map_tab, f"{ICON_SERVER}  Mapa")
        # ARRANCO EN MODO LISTA (el mapa queda como segunda pestana):
        self.resource_tabs.setCurrentIndex(0)

        col3_layout.addWidget(self.resource_tabs, stretch=1)

        # Estado de conexion compacto:
        conn_status_layout = QHBoxLayout()
        self.lbl_connection_status = QLabel("-")
        self.lbl_connection_status.setWordWrap(True)
        self.lbl_connection_status.setStyleSheet("font-size: 12px;")
        conn_status_layout.addWidget(self.lbl_connection_status, stretch=1)

        self.btn_copy_error = QPushButton("Copiar")
        self.btn_copy_error.setMaximumWidth(70)
        self.btn_copy_error.clicked.connect(self.on_copy_error)
        self.btn_copy_error.setVisible(False)
        conn_status_layout.addWidget(self.btn_copy_error)

        # BOTON DE LOG DE ERRORES: abre un dialogo con el detalle de todos
        # los errores (API/conexion) registrados en la sesion:
        self.btn_error_log = QPushButton(f"{ICON_INFO}  Log errores")
        self.btn_error_log.setToolTip("Ver el log de errores (API/conexion)")
        self.btn_error_log.clicked.connect(self.on_open_error_log)
        conn_status_layout.addWidget(self.btn_error_log)
        col3_layout.addLayout(conn_status_layout)

        splitter.addWidget(col3_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([360, 1000])
        layout.addWidget(splitter, stretch=1)

        # 12 - ETIQUETA DE ESTADO:
        self.lbl_status = QLabel(f"{ICON_WARN}  Arrastra un kubeconfig para empezar")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setMaximumHeight(24)
        layout.addWidget(self.lbl_status)

        # 13 - CARGO HOTBAR DESDE LA DB:
        self._refresh_hotbar()

        # 14 - OVERLAYS DE SPINNER (circulito de carga):
        #     Uno sobre la lista de contexts y otro sobre el area de
        #     recursos (lista pods/services + mapa):
        self._overlay_contexts = _LoadingOverlay(self.list_contexts)
        self._overlay_resources = _LoadingOverlay(self.resource_tabs)
        self._overlay_contexts.hide()
        self._overlay_resources.hide()

    def _spinner_start(self, which, text="Cargando..."):
        # 1 - MUESTRO EL SPINNER SOBRE EL AREA INDICADA:
        overlay = self._overlay_contexts if which == "contexts" else self._overlay_resources
        overlay.setGeometry(overlay.parentWidget().rect())
        overlay.start(text)

    def _spinner_stop(self, which):
        # 1 - OCULTO EL SPINNER DEL AREA INDICADA:
        overlay = self._overlay_contexts if which == "contexts" else self._overlay_resources
        overlay.stop()

    def on_load(self):
        # 1 - CARGO DIRECTAMENTE EL KUBECONFIG POR DEFECTO DEL USUARIO:
        #     Si no existe, aviso (siempre se puede cargar otro con drag & drop):
        if not os.path.exists(USER_KUBECONFIG):
            QMessageBox.warning(
                self,
                f"{ICON_WARN} No existe ~/.kube/config",
                f"No se encontro el archivo:\n{USER_KUBECONFIG}\n\n"
                "Arrastra un kubeconfig a la app para cargarlo.",
            )
            return
        self.load_kubeconfig(USER_KUBECONFIG)

    def on_clear_config(self):
        # 1 - LIMPIO EL ESTADO DE LA APLICACION:
        self.config = None
        self.current_context_name = None
        self._loaded_file_path = None
        self._current_kubeconfig_id = None
        self._current_contexts = []
        self._context_scan_cache = {}
        self.selected_context_name = None
        self.selected_namespace = None
        self._v1 = None
        self._pods_cache = {}
        self._services_cache = []

        # 2 - LIMPIO LAS LISTAS, TABLAS, MAPA Y COMBO:
        self.list_clusters.clear()
        self.list_contexts.clear()
        self.txt_search_contexts.clear()
        self.table_pods.setRowCount(0)
        self.table_services.setRowCount(0)
        self.table_users.setRowCount(0)
        self._clear_map()
        self.combo_namespaces.clear()

        # 3 - LIMPIO METADATOS, DETALLES Y ESTADOS:
        self.lbl_file_path.setText("-")
        self.lbl_api_version.setText("-")
        self.lbl_kind.setText("-")
        self.lbl_current_context.setText("-")
        self.lbl_ctx_name.setText("-")
        self.lbl_ctx_namespace.setText("-")
        self.lbl_ctx_user.setText("-")
        self.lbl_ctx_cluster.setText("-")
        self.lbl_pods_title.setText(f"{ICON_POD}  Recursos:")
        self.lbl_pods_list_title.setText(f"{ICON_POD}  Pods")
        self.lbl_services_title.setText(f"{ICON_CLUSTER}  Services")
        self.lbl_connection_status.setText("-")
        self.btn_copy_error.setVisible(False)
        self.btn_test_connection.setEnabled(False)
        self.btn_ping.setEnabled(False)
        self.btn_discovery.setEnabled(False)
        self.btn_copy_user.setEnabled(False)
        self.btn_add_context.setEnabled(False)

        # 4 - DESELECCIONO LA HOTBAR (los anclados quedan en la DB):
        self.hotbar.select(None)

        # 5 - ESTADO FINAL:
        self.lbl_status.setText(f"{ICON_WARN}  Arrastra un kubeconfig para empezar")

    def on_oidc_logout(self):
        # 1 - BUSCO LA CACHE DE TOKENS DE KUBELOGIN (oidc-login):
        cache_dir = os.path.join(os.path.expanduser("~"), ".kube", "cache", "oidc-login")
        if not os.path.isdir(cache_dir):
            QMessageBox.information(
                self,
                f"{ICON_INFO} Sin cache OIDC",
                "No hay cache de kubelogin para borrar:\n" + cache_dir,
            )
            return

        # 2 - CONFIRMO (borra los tokens cacheados de TODOS los clusters OIDC):
        reply = QMessageBox.question(
            self,
            f"{ICON_CONTEXT} Cerrar sesion OIDC",
            "Se va a borrar la cache de tokens de kubelogin:\n\n"
            f"  {cache_dir}\n\n"
            "La proxima conexion a un context OIDC va a pedir login en el navegador.\n"
            "Si en el portal quedo la sesion de otro usuario, cerrala primero.\n\n"
            "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 3 - BORRO LA CACHE:
        try:
            shutil.rmtree(cache_dir)
        except Exception as e:
            self._log_error("No se pudo borrar la cache de kubelogin", _short_error(e))
            QMessageBox.critical(
                self,
                f"{ICON_WARN} Error",
                f"No se pudo borrar la cache de kubelogin:\n{_short_error(e)}",
            )
            return

        # 4 - ESTADO FINAL:
        print(f"[MiniLens] Cache de kubelogin borrada: {cache_dir}")
        self.lbl_status.setText(f"{ICON_OK}  Sesion OIDC cerrada (cache de kubelogin borrada)")

    def on_import_to_user_config(self):
        # 1 - VERIFICO QUE HAYA UN KUBECONFIG CARGADO:
        if not self.config or not self._current_kubeconfig_id:
            return

        # 2 - LEO EL KUBECONFIG ORIGINAL DEL USUARIO (~/.kube/config):
        existing = {}
        if os.path.exists(USER_KUBECONFIG):
            try:
                with open(USER_KUBECONFIG, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}

        # 3 - DETECTO QUE HAY DE NUEVO (comparo por nombre clusters/contexts/users):
        ex_clusters = {c.get("name") for c in (existing.get("clusters") or [])}
        ex_contexts = {c.get("name") for c in (existing.get("contexts") or [])}
        ex_users = {u.get("name") for u in (existing.get("users") or [])}

        new_clusters = [c for c in (self.config.get("clusters") or []) if c.get("name") not in ex_clusters]
        new_contexts = [c for c in (self.config.get("contexts") or []) if c.get("name") not in ex_contexts]
        new_users = [u for u in (self.config.get("users") or []) if u.get("name") not in ex_users]

        # 4 - SI NO HAY NADA NUEVO, AVISO Y SALGO:
        if not new_clusters and not new_contexts and not new_users:
            self._log_import("Importacion: no habia elementos nuevos para ~/.kube/config")
            QMessageBox.information(
                self,
                f"{ICON_INFO} Nada para importar",
                "Todos los clusters, contexts y users del kubeconfig cargado\n"
                "ya existen en ~/.kube/config",
            )
            return

        # 5 - CONFIRMO LA IMPORTACION:
        reply = QMessageBox.question(
            self,
            f"{ICON_INFO} Importar a ~/.kube/config",
            f"Se van a importar SOLO los elementos nuevos a:\n\n"
            f"  {USER_KUBECONFIG}\n\n"
            f"  Clusters nuevos: {len(new_clusters)}\n"
            f"  Contexts nuevos: {len(new_contexts)}\n"
            f"  Users nuevos:    {len(new_users)}\n\n"
            f"Lo que ya existe NO se toca.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 6 - MERGEO: kubeconfig original + elementos nuevos:
        merged = dict(existing) if existing else {}
        merged.setdefault("apiVersion", "v1")
        merged.setdefault("kind", "Config")
        merged["clusters"] = list(existing.get("clusters") or []) + new_clusters
        merged["contexts"] = list(existing.get("contexts") or []) + new_contexts
        merged["users"] = list(existing.get("users") or []) + new_users
        if not merged.get("current-context") and self.config.get("current-context"):
            merged["current-context"] = self.config.get("current-context")

        # 7 - ESCRIBO EL KUBECONFIG DEL USUARIO:
        kube_dir = os.path.dirname(USER_KUBECONFIG)
        try:
            os.makedirs(kube_dir, exist_ok=True)
            with open(USER_KUBECONFIG, "w", encoding="utf-8") as f:
                yaml.safe_dump(merged, f, sort_keys=False, default_flow_style=False)
            self._log_import(
                f"Importado a ~/.kube/config: {len(new_clusters)} clusters, "
                f"{len(new_contexts)} contexts, {len(new_users)} users nuevos"
            )
            QMessageBox.information(
                self,
                f"{ICON_OK} Importado",
                f"Importados a {USER_KUBECONFIG}:\n\n"
                f"  Clusters nuevos: {len(new_clusters)}\n"
                f"  Contexts nuevos: {len(new_contexts)}\n"
                f"  Users nuevos:    {len(new_users)}",
            )
        except Exception as e:
            self._log_import(f"ERROR importando a ~/.kube/config: {e}")
            QMessageBox.critical(
                self,
                f"{ICON_WARN} Error",
                f"No se pudo importar:\n{e}",
            )

    def load_kubeconfig(self, file_path):
        # 1 - LEO EL ARCHIVO YAML (con deteccion de claves duplicadas):
        _DUP_KEYS.clear()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.config = yaml.load(f, Loader=_DuplicateKeyLoader)
            self._context_scan_cache = {}
        except Exception as e:
            self._log_import(f"ERROR leyendo {os.path.basename(file_path)}: {e}")
            QMessageBox.critical(self, f"{ICON_WARN} Error", f"No se pudo leer el archivo:\n{e}")
            return

        # 1a - SI HABIA CLAVES YAML DUPLICADAS: ya se acomodaron (listas
        #     unidas / dicts mezclados) en lugar de pisar la primera:
        if _DUP_KEYS:
            dups = ", ".join(sorted(set(_DUP_KEYS)))
            self._log_import(f"AUTO-FIX: claves YAML duplicadas en {os.path.basename(file_path)}: {dups} (se acomodaron)")

        # 1b - AUTO-FIX: asigno namespace 'default' a los contexts sin namespace:
        fixes = self._autofix_kubeconfig(self.config)
        for fx in fixes:
            self._log_import(f"AUTO-FIX: {fx}")

        # 1c - VALIDO LA ESTRUCTURA (sobre el archivo ya acomodado):
        issues = self._validate_kubeconfig(self.config)
        for sev, msg in issues:
            self._log_import(f"[{sev}] {msg}")

        # 2 - GUARDO EN LA BASE DE DATOS:
        try:
            self._current_kubeconfig_id = dbmod.import_kubeconfig(file_path)
        except Exception as e:
            QMessageBox.critical(self, f"{ICON_WARN} Error DB", f"No se pudo guardar en la base de datos:\n{e}")
            return

        # 3 - GUARDO LA RUTA DEL ARCHIVO CARGADO:
        self._loaded_file_path = file_path

        # 3a - LOG DE IMPORTACION OK:
        self._log_import(
            f"OK: {os.path.basename(file_path)} cargado "
            f"({len(self.config.get('clusters') or [])} clusters, "
            f"{len(self.config.get('users') or [])} users, "
            f"{len(self.config.get('contexts') or [])} contexts)"
        )

        # 3c - SI HUBO FIXES O PROBLEMAS, MUESTRO EL REPORTE INTERACTIVO:
        if fixes or issues:
            dlg = KubeconfigReportDialog(
                fixes,
                issues,
                self.config,
                file_path,
                self,
            )
            dlg.exec()

        # 4 - METADATOS:
        self.lbl_file_path.setText(file_path)
        self.lbl_api_version.setText(str(self.config.get("apiVersion", "-")))
        self.lbl_kind.setText(str(self.config.get("kind", "-")))
        self.current_context_name = self.config.get("current-context", "-")
        self.lbl_current_context.setText(str(self.current_context_name))

        # 5 - LIMPIO LAS LISTAS Y TABLAS:
        self.list_clusters.clear()
        self.list_contexts.clear()
        self.table_pods.setRowCount(0)
        self.table_users.setRowCount(0)

        # 6 - POBLA COLUMNA 1: CLUSTERS (con bolita de estado + IP):
        self._populate_cluster_list()

        # 7 - POBLA AREA INFERIOR: USERS:
        self._populate_users_table()

        # 8 - HABILITO EL BOTON DE COPIAR Y EL DE AGREGAR CONTEXT:
        self.btn_copy_user.setEnabled(True)
        self.btn_add_context.setEnabled(True)

        # 9 - REFRESCO LA HOTBAR:
        self._refresh_hotbar()

        # 10 - ESTADO FINAL:
        n_clusters = len(self.config.get("clusters", []))
        n_users = len(self.config.get("users", []))
        n_contexts = len(self.config.get("contexts", []))
        self.lbl_status.setText(
            f"{ICON_OK}  Kubeconfig cargado: "
            f"{n_clusters} cluster(s), {n_users} user(s), {n_contexts} context(s)"
        )

    def _pin_cluster(self, cluster_id):
        # 1 - ANCLO EL CLUSTER EN LA DB:
        dbmod.pin_cluster(cluster_id)
        # 2 - REFRESCO LA HOTBAR:
        self._refresh_hotbar()

    def _unpin_cluster(self, cluster_id):
        # 1 - DESANCO EL CLUSTER EN LA DB:
        dbmod.unpin_cluster(cluster_id)
        # 2 - REFRESCO LA HOTBAR:
        self._refresh_hotbar()

    def _on_cluster_dropped(self, cluster_name, kubeconfig_id):
        # 1 - BUSCO EL CLUSTER EN LA DB (por nombre, del kubeconfig de origen):
        target_kc = kubeconfig_id or self._current_kubeconfig_id
        if not target_kc:
            return
        for c in dbmod.get_clusters(target_kc):
            if c["name"] == cluster_name:
                # 2 - SI YA ESTA ANCLADO NO HAGO NADA; SI NO, LO ANCLO:
                if not c["pinned"]:
                    dbmod.pin_cluster(c["id"])
                    self._refresh_hotbar()
                    self.lbl_status.setText(f"{ICON_OK}  Cluster anclado a la hotbar: {cluster_name}")
                return

    def _refresh_hotbar(self):
        # 1 - OBTENGO LOS CLUSTERS ANCLADOS DESDE LA DB:
        pinned = dbmod.get_pinned_clusters()
        self.hotbar.refresh(pinned)

    def on_hotbar_item_clicked(self, cluster_id):
        # 1 - MARCO EL ITEM COMO SELECCIONADO:
        self.hotbar.select(cluster_id)

        # 2 - RESETEO LA VISTA (logs, tablas, estado):
        self._reset_view_on_switch()

        # 3 - OBTENGO EL CLUSTER DESDE LA DB:
        c = dbmod.get_cluster(cluster_id)
        if not c:
            return

        # 3 - CARGO EL KUBECONFIG DESDE LA DB (yaml_content):
        yaml_content = c.get("yaml_content", "")
        if not yaml_content:
            return

        # 4 - PARSEO EL YAML:
        self.config = yaml.safe_load(yaml_content)
        self._context_scan_cache = {}
        self._loaded_file_path = c.get("file_path") or None
        self.current_context_name = self.config.get("current-context", "-")
        self._current_kubeconfig_id = c.get("kubeconfig_id")

        # 5 - ESCRIBO A UN ARCHIVO TEMPORAL PARA EL KUBERNETES CLIENT:
        self._temp_kubeconfig = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        self._temp_kubeconfig.write(yaml_content)
        self._temp_kubeconfig.close()
        self._loaded_file_path = self._temp_kubeconfig.name

        # 6 - METADATOS:
        self.lbl_file_path.setText(c.get("filename", "-"))
        self.lbl_api_version.setText(str(self.config.get("apiVersion", "-")))
        self.lbl_kind.setText(str(self.config.get("kind", "-")))
        self.lbl_current_context.setText(str(self.current_context_name))

        # 7 - POBLA CLUSTERS Y USERS:
        self.list_clusters.clear()
        self.list_contexts.clear()
        self.table_pods.setRowCount(0)
        self.table_users.setRowCount(0)

        self._populate_cluster_list()

        self._populate_users_table()

        self.btn_copy_user.setEnabled(True)

        # 8 - SELECCIONO EL CLUSTER EN LA LISTA Y BUSCO SU CONTEXT:
        #     (comparo por el nombre guardado en UserRole, no por el texto):
        cluster_name = c.get("name", "")
        for i in range(self.list_clusters.count()):
            item = self.list_clusters.item(i)
            if (item.data(Qt.UserRole) or {}).get("name") == cluster_name:
                self.list_clusters.setCurrentItem(item)
                break

        # 10 - BUSCO EL CONTEXT DEL CLUSTER Y CONECTO:
        for ctx in self.config.get("contexts", []):
            ctx_data = ctx.get("context", {})
            if ctx_data.get("cluster") == cluster_name:
                name = ctx.get("name", "-")
                self.selected_context_name = name
                self.selected_namespace = ctx_data.get("namespace", None)
                self.lbl_ctx_name.setText(name)
                self.lbl_ctx_namespace.setText(str(ctx_data.get("namespace", "-")))
                self.lbl_ctx_user.setText(str(ctx_data.get("user", "-")))
                self.lbl_ctx_cluster.setText(str(ctx_data.get("cluster", "-")))
                self.btn_test_connection.setEnabled(True)
                self.on_test_connection()
                break

    def on_hotbar_item_unpinned(self, cluster_id):
        # 1 - DESANCO EL CLUSTER:
        self._unpin_cluster(cluster_id)

    def on_hotbar_item_edit(self, cluster_id):
        # 1 - OBTENGO EL CLUSTER DESDE LA DB:
        c = dbmod.get_cluster(cluster_id)
        if not c:
            return

        # 2 - ABRO EL DIALOGO EDITOR:
        editor = HotbarItemEditor(c, self)
        if editor.exec() != QDialog.Accepted:
            return

        # 3 - GUARDO LOS CAMBIOS EN LA DB:
        vals = editor.get_values()
        dbmod.update_cluster_appearance(
            cluster_id,
            alias=vals["alias"] or None,
            short_alias=vals["short_alias"] or None,
            color=vals["color"],
            icon=vals["icon"],
        )

        # 4 - SI EL USUARIO QUIERE GUARDAR EL COLOR EN LA PALETA:
        if vals["save_color"]:
            dbmod.add_color(vals["color"], vals["alias"] or "")

        # 5 - REFRESCO LA HOTBAR:
        self._refresh_hotbar()

    @staticmethod
    def _parse_server(server):
        # 1 - EXTRAIGO HOST Y PUERTO DE LA URL DEL SERVER:
        parsed = urlparse(server)
        return parsed.hostname, (parsed.port or 443)

    def _populate_cluster_list(self):
        # 1 - LIMPIO LA LISTA:
        self.list_clusters.clear()

        # 2 - POBLA CADA CLUSTER CON FILA CUSTOM (nombre + host + bolita a la derecha):
        for c in self.config.get("clusters", []):
            name = c.get("name", "(sin nombre)")
            server = (c.get("cluster") or {}).get("server", "")
            host, port = self._parse_server(server)

            # 2a - ITEM CON FILA CUSTOM (la bolita va a la derecha):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c)
            item.setSizeHint(QSize(0, 34))
            self.list_clusters.addItem(item)
            row = ClusterRow(name, host)
            self.list_clusters.setItemWidget(item, row)

            # 2b - LANZO EL PING TCP EN BACKGROUND PARA PINTAR LA BOLITA:
            if host:
                task = _ClusterPingTask(item, host, port, self._ping_signals)
                self._ping_pool.start(task)

    def _on_cluster_ping_result(self, item, ok):
        # 1 - ACTUALIZO LA BOLITA DE LA FILA SEGUN EL RESULTADO:
        #     (el item puede haberse borrado si se limpio la lista
        #      mientras el ping estaba en vuelo -> RuntimeError)
        try:
            row = self.list_clusters.itemWidget(item)
            if row:
                row.set_state("ok" if ok else "fail")
        except RuntimeError:
            pass

    def _reset_view_on_switch(self):
        # 1 - LIMPIO LOGS DE ERROR E IMPORT:
        self._error_log.clear()
        self._import_log.clear()
        self.btn_error_log.setText(f"{ICON_INFO}  Log errores")
        self.btn_import_log.setText(f"{ICON_INFO}  Log import")

        # 2 - LIMPIO TABLAS DE PODS, SERVICES Y MAPA:
        self.table_pods.setRowCount(0)
        self.table_services.setRowCount(0)
        self._clear_map()
        self._pods_cache = {}
        self._services_cache = []

        # 3 - LIMPIO COMBO DE NAMESPACES:
        self.combo_namespaces.clear()

        # 4 - LIMPIO ESTADO DE CONEXION:
        self.lbl_connection_status.setText("-")
        self.lbl_pods_title.setText(f"{ICON_POD}  Recursos del namespace:")
        self.lbl_pods_list_title.setText(f"{ICON_POD}  Pods:")
        self.lbl_services_title.setText(f"{ICON_CLUSTER}  Services:")
        self.btn_copy_error.setVisible(False)

        # 5 - LIMPIO EL CLIENTE V1 CACHEADO:
        self._v1 = None

    def on_cluster_selected(self, current, previous):
        # 1 - SI NO HAY ITEM SELECCIONADO, LIMPIO:
        if not current:
            return

        # 2 - RESETEO LA VISTA (logs, tablas, estado):
        self._reset_view_on_switch()

        # 3 - OBTENGO EL NOMBRE DEL CLUSTER DESDE LOS DATOS DEL ITEM
        #     (el texto ahora tiene bolita de estado e IP entre parentesis):
        cluster_data = current.data(Qt.UserRole) or {}
        cluster_name = cluster_data.get("name", "")

        # 3a - GUARDO EL SERVER DEL CLUSTER SELECCIONADO (para el ping):
        server = (cluster_data.get("cluster") or {}).get("server", "")
        self._selected_cluster_server = server
        self.btn_ping.setEnabled(bool(server))

        # 4 - LIMPIO LA COLUMNA 2 (CONTEXTS) Y LA COLUMNA 3 (DETALLE):
        self.list_contexts.clear()
        self.lbl_ctx_name.setText("-")
        self.lbl_ctx_namespace.setText("-")
        self.lbl_ctx_user.setText("-")
        self.lbl_ctx_cluster.setText("-")

        # 5 - GUARDO LOS CONTEXTS DE ESTE CLUSTER Y LOS RENDERIZO
        #     (aplicando el filtro del buscador si hay algo escrito):
        self._current_contexts = []
        if not self.config:
            return
        for ctx in self.config.get("contexts", []):
            ctx_data = ctx.get("context", {})
            if ctx_data.get("cluster") == cluster_name:
                self._current_contexts.append(ctx)
        self._render_contexts()

    def _render_contexts(self):
        # 1 - POBLA LA LISTA DE CONTEXTS APLICANDO EL FILTRO DEL BUSCADOR:
        self.list_contexts.clear()
        filtro = self.txt_search_contexts.text().strip().lower()
        for ctx in getattr(self, "_current_contexts", []):
            name = ctx.get("name", "(sin nombre)")
            # 2 - SI HAY FILTRO, SALTEO LOS CONTEXTS QUE NO MATCHEN:
            if filtro and filtro not in name.lower():
                continue

            # 3 - ITEM CON FILA CUSTOM (badge de pods + bolita a la derecha):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, ctx)
            item.setSizeHint(QSize(0, 34))
            self.list_contexts.addItem(item)
            row = ContextRow(name, is_current=(name == self.current_context_name))
            self.list_contexts.setItemWidget(item, row)

            # 4 - SOLO PINTO SI EL USUARIO YA CONECTO ESTE CONTEXT ANTES:
            #     (si nunca hizo click, no muestro nada: ni badge ni estado)
            cached = self._context_scan_cache.get(name)
            if cached:
                row.set_state(cached[0], cached[1])

    def _update_context_row(self, context_name, state, n_pods):
        # 1 - GUARDO EN CACHE:
        self._context_scan_cache[context_name] = (state, n_pods)

        # 2 - BUSCO EL ITEM ACTUAL DE ESE CONTEXT Y ACTUALIZO LA FILA:
        #     (si el item ya no existe por re-render/filtro, no pasa nada:
        #      el cache lo va a pintar cuando se vuelva a renderizar)
        for i in range(self.list_contexts.count()):
            item = self.list_contexts.item(i)
            ctx = item.data(Qt.UserRole) or {}
            if ctx.get("name") == context_name:
                row = self.list_contexts.itemWidget(item)
                if row:
                    row.set_state(state, n_pods)
                break

    def on_ping_cluster(self):
        # 1 - OBTENGO EL SERVER DEL CLUSTER SELECCIONADO:
        server = getattr(self, "_selected_cluster_server", "")
        if not server:
            self.lbl_connection_status.setText(f"{ICON_WARN}  No hay server definido para este cluster")
            return

        # 2 - PARSEO LA URL PARA EXTRAER HOST Y PUERTO:
        parsed = urlparse(server)
        host = parsed.hostname
        port = parsed.port or 443
        if not host:
            self.lbl_connection_status.setText(f"{ICON_WARN}  No se pudo extraer el host de: {server}")
            return

        # 3 - HAGO TCP CONNECT CON TIMEOUT DE 3 SEGUNDOS:
        self.btn_ping.setEnabled(False)
        self.lbl_connection_status.setText(f"{ICON_INFO}  Verificando conectividad a {host}:{port}...")
        QApplication.processEvents()

        try:
            # 3a - INTENTO CONECTAR TCP:
            sock = socket.create_connection((host, port), timeout=3)
            sock.close()

            # 3b - SI ES HTTPS, INTENTO EL HANDSHAKE SSL:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                sock2 = socket.create_connection((host, port), timeout=3)
                ssock = ctx.wrap_socket(sock2, server_hostname=host)
                ssock.close()
                ssl_ok = True
            except Exception:
                ssl_ok = False

            if ssl_ok:
                self.lbl_connection_status.setText(
                    f"{ICON_OK}  Conectividad OK: {host}:{port} responde (TCP + SSL)"
                )
            else:
                self.lbl_connection_status.setText(
                    f"{ICON_OK}  TCP OK pero SSL fallo: {host}:{port} (posible cert/self-signed)"
                )

        except socket.gaierror:
            self.lbl_connection_status.setText(
                f"{ICON_WARN}  No se puede resolver {host} - DNS fallo. ¿Necesitas VPN?"
            )
        except (socket.timeout, TimeoutError):
            self.lbl_connection_status.setText(
                f"{ICON_WARN}  Timeout conectando a {host}:{port} - ¿Necesitas VPN?"
            )
        except ConnectionRefusedError:
            self.lbl_connection_status.setText(
                f"{ICON_WARN}  Conexion rechazada en {host}:{port} - el server no responde"
            )
        except Exception as e:
            short = _short_error(e)
            self.lbl_connection_status.setText(f"{ICON_WARN}  Error de conectividad: {short}")
        finally:
            self.btn_ping.setEnabled(True)

    def on_context_selected(self, current, previous):
        # 1 - SI NO HAY ITEM SELECCIONADO, LIMPIO:
        if not current:
            return

        # 2 - RESETEO LA VISTA (logs, tablas, estado):
        self._reset_view_on_switch()

        # 3 - OBTENGO EL CONTEXT SELECCIONADO:
        ctx = current.data(Qt.UserRole)
        ctx_data = ctx.get("context", {})
        name = ctx.get("name", "-")

        # 4 - MUESTRO EL DETALLE EN LA COLUMNA 3 (ElideLabel: clic = copiar):
        self.lbl_ctx_name.setText(name)
        self.lbl_ctx_namespace.setText(str(ctx_data.get("namespace", "-")))
        self.lbl_ctx_user.setText(str(ctx_data.get("user", "-")))
        self.lbl_ctx_cluster.setText(str(ctx_data.get("cluster", "-")))

        # 5 - GUARDO EL CONTEXT SELECCIONADO Y HABILITO EL BOTON:
        self.selected_context_name = name
        self.selected_namespace = ctx_data.get("namespace", None)
        self.btn_test_connection.setEnabled(True)

        # 6 - CONECTO AUTOMATICAMENTE AL CLUSTER Y LISTO LOS PODS:
        self.on_test_connection()

    def _copy_to_clipboard(self, text):
        # 1 - COPIO UN TEXTO AL PORTAPAPELES:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)

    def on_copy_error(self):
        # 1 - COPIO EL TEXTO DEL ERROR AL PORTAPAPELES:
        text = self.lbl_connection_status.text()
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)

    def closeEvent(self, event):
        # 1 - CIERRE DE LA APP: corto TODOS los streams de logs vivos para
        #     que no quede ningun thread colgado despues de cerrar:
        try:
            vivos = list(_LogsStreamTask._ALIVE)
            for t in vivos:
                t.stop()
            if vivos:
                _log.info("Cierre de la app: %d stream(s) de logs cortados", len(vivos))
        except Exception:
            pass

        # 2 - VACIO LAS COLAS DE TASKS EN ESPERA Y CORTO LOS POOLS:
        try:
            self._api_pool.clear()
        except Exception:
            pass
        try:
            QThreadPool.globalInstance().clear()
        except Exception:
            pass
        event.accept()

    def _identity(self):
        # 1 - ARMO LA IDENTIDAD ACTUAL: user@cluster/context
        #     (formato: cyberdefensa-oidc@clavaria-dev/cyber-battle-lab):
        ctx_name = getattr(self, "selected_context_name", None) or "-"
        cluster = "-"
        user = "-"
        for c in ((self.config or {}).get("contexts") or []):
            if c.get("name") == ctx_name:
                cd = c.get("context") or {}
                cluster = cd.get("cluster") or "-"
                user = cd.get("user") or "-"
                break
        return f"{user}@{cluster}/{ctx_name}"

    def _log_error(self, titulo, detalle=""):
        # 1 - GUARDO EL ERROR EN EL LOG EN MEMORIA Y ACTUALIZO EL BOTON:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 1a - IDENTIDAD COMPLETA EN EL LOG: user@cluster/context:
        prefix = f"[{self._identity()}] "
        self._error_log.append(f"[{stamp}] {prefix}{titulo}" + (f"\n{detalle}" if detalle else ""))
        self.btn_error_log.setText(f"{ICON_WARN}  Log errores ({len(self._error_log)})")

    def on_open_error_log(self):
        # 1 - ABRO EL DIALOGO CON EL LOG DE ERRORES:
        dlg = ErrorLogDialog(self._error_log, self)
        dlg.exec()
        # 2 - SI SE LIMPIO EL LOG DENTRO DEL DIALOGO, RESTAURO EL BOTON:
        if not self._error_log:
            self.btn_error_log.setText(f"{ICON_INFO}  Log errores")

    def _log_import(self, mensaje):
        # 1 - GUARDO UNA LINEA EN EL LOG DE IMPORTACION Y ACTUALIZO EL BOTON:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._import_log.append(f"[{stamp}] {mensaje}")
        self.btn_import_log.setText(f"{ICON_INFO}  Log import ({len(self._import_log)})")

    def on_open_import_log(self):
        # 1 - ABRO EL DIALOGO CON EL LOG DE IMPORTACION:
        dlg = ErrorLogDialog(
            self._import_log,
            self,
            title=f"{ICON_INFO}  Log de importacion de kubeconfigs",
            empty_text="(todavia no se importo ningun kubeconfig)",
        )
        dlg.exec()

    def on_add_context(self):
        # 1 - VERIFICO QUE HAYA UN KUBECONFIG CARGADO:
        if not self.config:
            QMessageBox.information(
                self,
                f"{ICON_INFO} Sin kubeconfig",
                "Primero carga un kubeconfig (drag & drop o el boton Cargar ~/.kube/config)",
            )
            return

        # 2 - CLUSTER SELECCIONADO: el context se agrega A ESE cluster
        #     (el que esta seleccionado en la lista de la izquierda):
        cur_item = self.list_clusters.currentItem()
        cluster_name = ((cur_item.data(Qt.UserRole) or {}).get("name")) if cur_item else None
        if not cluster_name:
            QMessageBox.warning(
                self,
                f"{ICON_WARN} Sin cluster",
                "Selecciona un cluster de la lista primero",
            )
            return

        # 3 - USER: el del context seleccionado (si es de este cluster);
        #     si no hay, el del primer context de ese cluster; si tampoco,
        #     el unico user del archivo (solo si hay exactamente uno):
        user_name = None
        cur_ctx = next(
            (c for c in (self.config.get("contexts") or []) if c.get("name") == getattr(self, "selected_context_name", None)),
            None,
        )
        if cur_ctx and ((cur_ctx.get("context") or {}).get("cluster") == cluster_name):
            user_name = (cur_ctx.get("context") or {}).get("user")
        if not user_name:
            for c in (self.config.get("contexts") or []):
                cd = c.get("context") or {}
                if cd.get("cluster") == cluster_name and cd.get("user"):
                    user_name = cd.get("user")
                    break
        if not user_name and len(self.config.get("users") or []) == 1:
            user_name = (self.config.get("users") or [{}])[0].get("name")
        if not user_name:
            QMessageBox.warning(
                self,
                f"{ICON_WARN} Sin user",
                f"El cluster '{cluster_name}' no tiene ningun context con user\n"
                "y hay varios users en el archivo: no se pueden determinar las credenciales.",
            )
            return

        # 4 - DIALOGO SIMPLE: SOLO PIDE EL NAMESPACE (cluster/user fijos):
        dlg = AddContextDialog(
            cluster_name,
            user_name,
            getattr(self, "selected_namespace", None) or "",
            self,
        )
        if dlg.exec() != QDialog.Accepted or not dlg.result_ctx:
            return
        ctx = dlg.result_ctx
        ctx_name = ctx.get("name", "")

        # 5 - AGREGO (O REEMPLAZO) EL CONTEXT EN EL CONFIG EN MEMORIA:
        contexts = self.config.setdefault("contexts", [])
        ctx_existente = next((c for c in contexts if c.get("name") == ctx_name), None)
        if ctx_existente:
            reply = QMessageBox.question(
                self,
                f"{ICON_WARN} Context existente",
                f"El context '{ctx_name}' ya existe.\n¿Reemplazarlo?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            contexts[contexts.index(ctx_existente)] = ctx
        else:
            contexts.append(ctx)

        # 6 - GUARDO EL KUBECONFIG EN EL ARCHIVO CARGADO (con confirmacion):
        #     Nota: se reescribe con yaml.safe_dump (igual que el auto-fix del
        #     reporte), asi que se pierden comentarios/formato del original:
        path = self._loaded_file_path
        guardado = False
        if path:
            reply = QMessageBox.question(
                self,
                f"{ICON_INFO} Guardar kubeconfig",
                f"¿Guardar el context '{ctx_name}' en el archivo?\n\n  {path}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(self.config, f, sort_keys=False, default_flow_style=False)
                    guardado = True
                except Exception as e:
                    QMessageBox.critical(self, f"{ICON_WARN} Error", f"No se pudo guardar el archivo:\n{e}")
                    self._log_error(f"No se pudo guardar el context '{ctx_name}': {e}")

        # 7 - REFRESCO LA LISTA DE CLUSTERS Y CONTEXTS:
        self._populate_cluster_list()

        # 7a - RE-SELECCIONO EL CLUSTER DEL CONTEXT NUEVO PARA REPUBLAR CONTEXTS:
        #      (si es el mismo cluster, setCurrentItem no dispara la senal:
        #      actualizo _current_contexts y re-renderizo a mano)
        cluster_name = (ctx.get("context") or {}).get("cluster", "")
        cur_cluster = (self.list_clusters.currentItem().data(Qt.UserRole) or {}).get("name") \
            if self.list_clusters.currentItem() else None
        if cluster_name and cluster_name != cur_cluster:
            for i in range(self.list_clusters.count()):
                it = self.list_clusters.item(i)
                if (it.data(Qt.UserRole) or {}).get("name") == cluster_name:
                    self.list_clusters.setCurrentItem(it)
                    break
        else:
            self._current_contexts = [
                c for c in (self.config.get("contexts") or [])
                if (c.get("context") or {}).get("cluster") == cluster_name
            ]
            self._render_contexts()

        # 7b - SELECCIONO EL CONTEXT NUEVO (dispara la conexion automatica):
        for i in range(self.list_contexts.count()):
            it = self.list_contexts.item(i)
            if (it.data(Qt.UserRole) or {}).get("name") == ctx_name:
                self.list_contexts.setCurrentItem(it)
                break

        # 8 - LOG Y ESTADO FINAL:
        detalle = f"guardado en {os.path.basename(path)}" if guardado else "solo en memoria (no se guardo el archivo)"
        self._log_import(f"Context '{ctx_name}' agregado ({detalle})")
        self.lbl_status.setText(
            f"{ICON_OK}  Context '{ctx_name}' agregado ({detalle})"
            if guardado else
            f"{ICON_WARN}  Context '{ctx_name}' agregado solo en memoria: usa 'Importar a ~/.kube/config' o guarda el archivo"
        )

    def on_open_merge(self):
        # 1 - ABRO LA VENTANA DE MERGE DE KUBECONFIGS:
        dlg = KubeconfigMergeDialog(self, self)
        dlg.exec()
        # 1a - SI EL ARCHIVO ACTIVO FUE MODIFICADO EN EL MERGE, LO RECARGO:
        #      (simple: si hay config activa, la dejo como esta; el usuario
        #       puede recargar con el boton de cargar)

    def _validate_kubeconfig(self, config):
        """Valida la estructura de un kubeconfig y retorna [(severidad, mensaje)].

        Detecta: clusters/contexts/users faltantes, referencias rotas,
        contexts sin namespace y users sin credenciales.
        """
        issues = []
        clusters = config.get("clusters") or []
        users = config.get("users") or []
        contexts = config.get("contexts") or []

        # 1 - ESTRUCTURA BASICA:
        if not clusters:
            issues.append(("AVISO", "El archivo no define clusters"))
        if not users:
            issues.append(("ERROR", "El archivo no define users (no se podra autenticar)"))
        if not contexts:
            issues.append(("AVISO", "El archivo no define contexts"))

        cluster_names = {c.get("name") for c in clusters}
        user_names = {u.get("name") for u in users}

        # 2 - CADA CLUSTER DEBE TENER SERVER:
        for c in clusters:
            if not (c.get("cluster") or {}).get("server"):
                issues.append(("ERROR", f"El cluster '{c.get('name')}' no define 'server'"))

        # 3 - CADA USER DEBERIA TENER ALGUNA CREDENCIAL:
        for u in users:
            ud = u.get("user") or {}
            if not any([ud.get("token"), ud.get("client-certificate-data"), ud.get("username"), ud.get("exec")]):
                issues.append(("AVISO", f"El user '{u.get('name')}' no tiene credenciales (token/cert/exec)"))

        # 4 - CADA CONTEXT DEBE REFERENCIAR CLUSTER Y USER EXISTENTES:
        for c in contexts:
            name = c.get("name", "(sin nombre)")
            cd = c.get("context") or {}
            if cd.get("cluster") not in cluster_names:
                issues.append(("ERROR", f"El context '{name}' referencia al cluster '{cd.get('cluster')}' que NO existe"))
            if cd.get("user") and cd.get("user") not in user_names:
                issues.append(("ERROR", f"El context '{name}' referencia al user '{cd.get('user')}' que NO existe"))
            if not cd.get("namespace"):
                issues.append(("AVISO", f"El context '{name}' no define namespace (elegilo del combo al conectar)"))

        # 5 - CURRENT-CONTEXT VALIDO:
        cc = config.get("current-context")
        if cc and cc not in {c.get("name") for c in contexts}:
            issues.append(("AVISO", f"current-context '{cc}' no existe en la lista de contexts"))
        return issues

    def _autofix_kubeconfig(self, config):
        """Aplica correcciones automaticas al kubeconfig y retorna la lista de fixes.

        Acomoda lo que se puede arreglar solo (contexts sin namespace).
        Lo que no (referencias rotas, users sin credenciales) solo se reporta.
        """
        fixes = []

        # 1 - CONTEXTS SIN NAMESPACE: les asigno 'default' (el default de kubectl):
        for c in config.get("contexts") or []:
            cd = c.get("context") or {}
            c["context"] = cd
            if not cd.get("namespace"):
                cd["namespace"] = "default"
                fixes.append(f"context '{c.get('name')}': namespace 'default' asignado")

        return fixes

    def on_open_error_log(self):
        # 1 - ABRO EL DIALOGO CON EL LOG DE ERRORES:
        dlg = ErrorLogDialog(self._error_log, self)
        dlg.exec()
        # 2 - SI SE LIMPIO EL LOG DENTRO DEL DIALOGO, RESTAURO EL BOTON:
        if not self._error_log:
            self.btn_error_log.setText(f"{ICON_INFO}  Log errores")

    def _populate_users_table(self):
        # 1 - POBLA LA TABLA DE USERS: nombre + entornos (clusters) a los que accede:
        users = self.config.get("users", []) if self.config else []
        self.table_users.setRowCount(len(users))

        # 1a - MAPEO user -> clusters (via los contexts que lo referencian):
        user_clusters = {}
        for ctx in (self.config.get("contexts") or []):
            cd = ctx.get("context", {})
            uname = cd.get("user")
            clname = cd.get("cluster")
            if uname and clname:
                user_clusters.setdefault(uname, set()).add(clname)

        # 1b - CONTEXTO ACTUAL: para marcar cual user esta en uso:
        current_user = None
        for ctx in (self.config.get("contexts") or []):
            if ctx.get("name") == self.current_context_name:
                current_user = ctx.get("context", {}).get("user")
                break

        for i, u in enumerate(users):
            name = u.get("name", "-")
            user_data = u.get("user", {})

            # 1c - ENTORNOS: clusters que referencian a este user:
            clusters = sorted(user_clusters.get(name, set()))
            env_str = ", ".join(clusters) if clusters else "(sin context)"
            if name == current_user:
                display_name = f"{ICON_USER}  {name}   (en uso)"
            else:
                display_name = f"{ICON_USER}  {name}"

            self.table_users.setItem(i, 0, QTableWidgetItem(display_name))
            self.table_users.setItem(i, 1, QTableWidgetItem(env_str or "(sin context)"))

    def on_user_double_click(self, index):
        # 1 - OBTENGO EL USER DE LA FILA:
        row = index.row()
        users = self.config.get("users", []) if self.config else []
        if row < 0 or row >= len(users):
            return
        u = users[row]

        # 2 - ABRO EL POPUP CON LAS CREDENCIALES:
        dlg = UserDetailDialog(u, self)
        dlg.exec()

    def _populate_namespaces(self, v1):
        # 1 - PIDO AL CLUSTER TODOS LOS NAMESPACES VISIBLES PARA EL USUARIO:
        #     list_namespace() hace GET a /api/v1/namespaces.
        #     Si el usuario no tiene permiso (RBAC), hago fallback y extraigo
        #     los namespaces de los contexts del kubeconfig:
        self._loading_namespaces = True
        try:
            ns_list = v1.list_namespace()
            names = sorted(ns.metadata.name for ns in ns_list.items)
        except ApiException as e:
            # 1a - SIN PERMISO PARA LISTAR NAMESPACES: extraigo de los contexts:
            self._log_error(f"No se pudieron listar los namespaces (codigo {e.status}): {e.reason}")
            names = self._get_namespaces_from_contexts()
        except Exception as e:
            # 1b - OTRO ERROR (ej: DNS): extraigo de los contexts:
            short_msg = _short_error(e)
            self._log_error(f"No se pudieron listar los namespaces: {short_msg}")
            names = self._get_namespaces_from_contexts()
        self.combo_namespaces.clear()
        self.combo_namespaces.addItems(names)

        # 2 - SELECCIONO EL NAMESPACE DEL CONTEXT ACTUAL:
        if self.selected_namespace and self.selected_namespace in names:
            self.combo_namespaces.setCurrentText(self.selected_namespace)
        self._loading_namespaces = False

    def _get_namespaces_from_contexts(self):
        # 1 - EXTRAIGO NAMESPACES UNICOS DE LOS CONTEXTS DEL KUBECONFIG ACTUAL:
        names = []
        if hasattr(self, "config") and self.config:
            cluster_name = None
            # 1a - BUSCO EL CLUSTER DEL CONTEXT SELECCIONADO:
            for ctx in self.config.get("contexts", []):
                if ctx.get("name") == self.selected_context_name:
                    cluster_name = ctx.get("context", {}).get("cluster")
                    break
            # 1b - RECORRO TODOS LOS CONTEXTS DEL MISMO CLUSTER:
            for ctx in self.config.get("contexts", []):
                cd = ctx.get("context", {})
                if cluster_name and cd.get("cluster") != cluster_name:
                    continue
                ns = cd.get("namespace")
                if ns and ns not in names:
                    names.append(ns)
        # 1c - SI NO ENCONTRE NINGUNO, USO EL SELECCIONADO:
        if not names and self.selected_namespace:
            names = [self.selected_namespace]
        return sorted(names)

    def _ns_debounce_start(self, _text):
        # 1 - SI ESTOY CARGANDO EL COMBO PROGRAMATICAMENTE, NO DISPARO DEBOUNCE:
        if getattr(self, "_loading_namespaces", False):
            return
        # 2 - INICIO/REINICIO EL TIMER DE DEBOUNCE (600ms):
        self._ns_debounce.start()

    def _ns_debounce_fire(self):
        # 1 - EL TIMER EXPIRO: TOMO EL TEXTO ACTUAL DEL COMBO Y CARGO RECURSOS:
        ns_text = self.combo_namespaces.currentText().strip()
        if not ns_text:
            return
        self.selected_namespace = ns_text
        self.lbl_ctx_namespace.setText(ns_text)
        if getattr(self, "_v1", None):
            self._load_resources()

    def _ns_pick_immediate(self, idx):
        # 1 - SELECCION DEL DROPDOWN: TOMO EL TEXTO Y CARGO YA (sin debounce):
        ns_text = self.combo_namespaces.itemText(idx).strip()
        if not ns_text:
            return
        self.selected_namespace = ns_text
        self.lbl_ctx_namespace.setText(ns_text)
        if getattr(self, "_v1", None):
            self._load_resources()

    def on_test_connection(self):
        # 1 - VERIFICO QUE HAYA UN CONTEXT SELECCIONADO:
        if not hasattr(self, "selected_context_name") or not self.selected_context_name:
            return

        # 2 - DESHABILITO EL BOTON Y MUESTRO ESTADO:
        self.btn_test_connection.setEnabled(False)
        self.lbl_connection_status.setText(f"{ICON_INFO}  Conectando al cluster (timeout 10s)...")
        self.table_pods.setRowCount(0)
        self._spinner_start("contexts", "Conectando...")
        self._spinner_start("resources", "Conectando al cluster...")
        QApplication.processEvents()

        # 3 - LANZO LA CONEXION EN BACKGROUND (no bloquea la UI):
        task = _ConnectTask(
            self._loaded_file_path,
            self.selected_context_name,
            self._connect_signals,
        )
        self._api_pool.start(task)

    def _on_connect_done(self, ok, data):
        # 1 - SI FALLO, MUESTRO EL ERROR:
        if not ok:
            kind = data[0]
            if kind == "api":
                _, status, reason = data
                if status == 403:
                    msg = f"{ICON_WARN}  403: {self._identity()} no puede listar namespaces del cluster"
                else:
                    msg = f"{ICON_WARN}  Error de la API (codigo {status}): {reason}"
                self.lbl_connection_status.setText(msg)
                self._log_error(f"Error de la API al conectar (codigo {status}): {reason}")
            else:
                _, short_msg = data
                self.lbl_connection_status.setText(f"{ICON_WARN}  Error de conexion: {short_msg}")
                self._log_error(f"Error de conexion al conectar: {short_msg}")
            self.btn_copy_error.setVisible(True)
            self.btn_test_connection.setEnabled(True)
            self._spinner_stop("contexts")
            self._spinner_stop("resources")

            # 1a - MARCO LA FILA DEL CONTEXT COMO SIN CONEXION (rojo):
            ctx_name = getattr(self, "selected_context_name", None)
            if ctx_name:
                self._update_context_row(ctx_name, "fail", None)
            return

        # 2 - CONEXION OK: guardo el v1 y lleno el combo de namespaces:
        v1, names = data
        self._v1 = v1
        self._spinner_stop("contexts")

        # 2a - SI LA API DEVOLVIO NAMESPACES, LOS USO; SINO FALLBACK A CONTEXTS:
        if not names:
            names = self._get_namespaces_from_contexts()
            print(f"[MiniLens] Fallback: {len(names)} namespaces desde contexts del kubeconfig: {names}")
        self._loading_namespaces = True
        self.combo_namespaces.clear()
        self.combo_namespaces.addItems(names)
        if self.selected_namespace and self.selected_namespace in names:
            self.combo_namespaces.setCurrentText(self.selected_namespace)
        self._loading_namespaces = False

        # 3 - OCULTO EL BOTON DE COPIAR:
        self.btn_copy_error.setVisible(False)
        self.btn_discovery.setEnabled(True)

        # 4 - SI EL CONTEXT NO DEFINE NAMESPACE, PIDO ELEGIRLO DEL COMBO:
        if not self.selected_namespace:
            self.lbl_connection_status.setText(
                f"{ICON_INFO}  Conectado. El context no define namespace: elegi uno del combo"
            )
            self.btn_test_connection.setEnabled(True)
            self._spinner_stop("resources")

            # 4a - CONECTO: PINTO LA FILA EN VERDE (sin conteo de pods):
            if self.selected_context_name:
                self._update_context_row(self.selected_context_name, "ok", None)
            return

        # 5 - CARGO LOS RECURSOS DEL NAMESPACE:
        self._load_resources()

    def _load_resources(self):
        # 1 - VERIFICO QUE HAYA UN v1 Y UN NAMESPACE:
        v1 = getattr(self, "_v1", None)
        if not v1 or not self.selected_namespace:
            return

        # 2 - DESHABILITO Y MUESTRO ESTADO:
        self.btn_test_connection.setEnabled(False)
        self.lbl_connection_status.setText(
            f"{ICON_INFO}  Cargando recursos de '{self.selected_namespace}' (timeout 15s)..."
        )
        self.table_pods.setRowCount(0)
        self.table_services.setRowCount(0)
        self._clear_map()
        self._spinner_start("resources", f"Cargando pods/services de '{self.selected_namespace}'...")
        QApplication.processEvents()

        # 3 - LANZO LA CARGA DE RECURSOS EN BACKGROUND:
        task = _LoadResourcesTask(v1, self.selected_namespace, self._resources_signals)
        self._api_pool.start(task)

    def _on_resources_done(self, ok, data):
        # 1 - SI FALLO, MUESTRO EL ERROR:
        if not ok:
            kind = data[0]
            if kind == "api":
                _, status, reason = data[0], data[1], data[2]
                detail = data[3] if len(data) > 3 else reason
                if status == 403:
                    msg = (
                        f"{ICON_WARN}  403: {self._identity()} no puede listar pods en '{self.selected_namespace}'. "
                        f"Revisa los Contexts: estas parado en el namespace '{self.selected_namespace}' y no tiene nada tuyo. "
                        f"Tipea el namespace en el combo (ej: cyber-battle-lab) o usa Discovery para escanear el cluster."
                    )
                else:
                    msg = f"{ICON_WARN}  Error de la API (codigo {status}): {reason}"
                self.lbl_connection_status.setText(msg)
                self._log_error(f"Error de la API al listar pods (codigo {status}): {detail or reason}")
            else:
                _, short_msg = data
                self.lbl_connection_status.setText(f"{ICON_WARN}  Error de conexion: {short_msg}")
                self._log_error(f"Error de conexion al listar pods: {short_msg}")
            self.btn_copy_error.setVisible(True)
            self.btn_test_connection.setEnabled(True)
            self._spinner_stop("resources")

            # 1a - ACTUALIZO LA FILA DEL CONTEXT: 403 = sin permiso, resto = fallo:
            ctx_name = getattr(self, "selected_context_name", None)
            if ctx_name:
                if kind == "api" and data[1] == 403:
                    self._update_context_row(ctx_name, "denied", None)
                else:
                    self._update_context_row(ctx_name, "fail", None)
            return

        # 2 - RECIBO PODS Y SERVICES DESDE EL THREAD:
        pods, services = data

        # 3 - LLENO LA TABLA DE PODS:
        self._pods_cache = {pod.metadata.name: pod for pod in pods}
        self.table_pods.setRowCount(len(pods))

        for i, pod in enumerate(pods):
            # 3a - NOMBRE DEL POD:
            name = pod.metadata.name

            # 3b - ESTADO DEL POD (phase):
            status = pod.status.phase if pod.status and pod.status.phase else "Unknown"

            # 3c - CONTAINERS READY (ej: "1/1"):
            if pod.status and pod.status.container_statuses:
                ready = sum(1 for cs in pod.status.container_statuses if cs.ready)
                total = len(pod.status.container_statuses)
                ready_str = f"{ready}/{total}"
            else:
                ready_str = "-"

            # 3d - IP DEL POD:
            pod_ip = pod.status.pod_ip if pod.status and pod.status.pod_ip else "-"

            self.table_pods.setItem(i, 0, QTableWidgetItem(f"{ICON_POD}  {name}"))
            self.table_pods.setItem(i, 1, QTableWidgetItem(status))
            self.table_pods.setItem(i, 2, QTableWidgetItem(ready_str))

            # 3d - IP DEL POD como boton amarillo cliqueable (clic = copiar):
            if pod_ip != "-":
                self.table_pods.setCellWidget(i, 3, _make_ip_button(pod_ip, tooltip_prefix="IP del POD"))
            else:
                self.table_pods.setItem(i, 3, QTableWidgetItem("-"))

            # 3e - EDAD DEL POD (cuanto hace que esta vivo):
            created = pod.metadata.creation_timestamp if pod.metadata else None
            self.table_pods.setItem(i, 4, QTableWidgetItem(_format_age(created)))

            # 3f - BOTON LOGS: abre el popup con los logs en vivo del pod:
            btn_logs = QPushButton(f"{ICON_LOGS}  Logs")
            btn_logs.setCursor(Qt.PointingHandCursor)
            btn_logs.setToolTip(f"Ver logs en vivo de {name}")
            btn_logs.setStyleSheet(
                "QPushButton { background-color: #2a2a2a; color: #f5c518;"
                " border: 1px solid #f5c518; border-radius: 4px;"
                " font-size: 12px; padding: 2px 10px; }"
                "QPushButton:hover { background-color: #3d3320; }"
            )
            btn_logs.clicked.connect(lambda checked, pod_obj=pod: self.on_open_pod_logs(pod_obj))
            self.table_pods.setCellWidget(i, 5, btn_logs)

        # 4 - LLENO LA TABLA DE SERVICES:
        self.table_services.setRowCount(len(services))

        for i, svc in enumerate(services):
            # 4a - NOMBRE DEL SERVICE:
            svc_name = svc.metadata.name

            # 4b - TIPO (ClusterIP, NodePort, LoadBalancer):
            svc_type = svc.spec.type or "ClusterIP"

            # 4c - CLUSTER IP:
            cluster_ip = svc.spec.cluster_ip or "-"

            # 4d - PUERTOS (ej: "8080/TCP, 443/TCP"):
            if svc.spec.ports:
                ports_str = ", ".join(
                    f"{p.port}/{p.protocol}" + (f" -> {p.target_port}" if p.target_port and str(p.target_port) != str(p.port) else "")
                    for p in svc.spec.ports
                )
            else:
                ports_str = "-"

            self.table_services.setItem(i, 0, QTableWidgetItem(f"\U0001F310  {svc_name}"))
            self.table_services.setItem(i, 1, QTableWidgetItem(svc_type))

            # 4c - CLUSTER IP como boton amarillo cliqueable (clic = copiar):
            if cluster_ip and cluster_ip != "-":
                self.table_services.setCellWidget(i, 2, _make_ip_button(cluster_ip, tooltip_prefix="IP del SERVICE"))
            else:
                self.table_services.setItem(i, 2, QTableWidgetItem("-"))

            self.table_services.setItem(i, 3, QTableWidgetItem(ports_str))

            # 4e - EDAD DEL SERVICE (cuanto hace que esta vivo):
            created = svc.metadata.creation_timestamp if svc.metadata else None
            self.table_services.setItem(i, 4, QTableWidgetItem(_format_age(created)))

        # 5 - GUARDO CACHE Y RENDERIZO EL MAPA GRAFICO:
        self._services_cache = services
        self._render_service_map(services, pods)

        # 6 - MUESTRO EL RESULTADO EN LOS TITULOS:
        n_pods = len(pods)
        n_svcs = len(services)
        self.lbl_pods_title.setText(
            f"{ICON_POD}  Recursos del namespace:  ({n_pods} pods, {n_svcs} services)"
        )
        self.lbl_pods_list_title.setText(
            f"{ICON_POD}  Pods:  ({n_pods})"
        )
        self.lbl_services_title.setText(
            f"{ICON_CLUSTER}  Services:  ({n_svcs})"
        )
        self.lbl_connection_status.setText(
            f"{ICON_OK}  Conexion exitosa! {n_pods} pod(s), {n_svcs} service(s) en namespace '{self.selected_namespace}'"
        )

        # 7 - OCULTO EL BOTON DE COPIAR Y REHABILITO:
        self.btn_copy_error.setVisible(False)
        self.btn_test_connection.setEnabled(True)
        self._spinner_stop("resources")

        # 8 - ACTUALIZO LA FILA DEL CONTEXT CON EL CONTADOR REAL DE PODS:
        ctx_name = getattr(self, "selected_context_name", None)
        if ctx_name:
            self._update_context_row(ctx_name, "ok", n_pods)

    def on_discovery(self):
        # 1 - VERIFICO QUE HAYA UN v1 (conexion activa):
        v1 = getattr(self, "_v1", None)
        if not v1:
            return

        # 2 - MUESTRO ESTADO Y LANZO EL DISCOVERY EN BACKGROUND:
        self.lbl_connection_status.setText(f"{ICON_SEARCH}  Discovery: listando todos los namespaces (timeout 20s)...")
        self.btn_discovery.setEnabled(False)
        self._spinner_start("resources", "Discovery: escaneando todo el cluster...")
        QApplication.processEvents()

        # 2a - NAMESPACES CONOCIDOS PARA EL FALLBACK (si el escaneo
        #      cluster-wide da 403, escaneo estos uno por uno):
        known_ns = set(self._get_namespaces_from_contexts())
        if getattr(self, "selected_namespace", None):
            known_ns.add(self.selected_namespace)
        known_ns |= {self.combo_namespaces.itemText(i) for i in range(self.combo_namespaces.count())}
        known_ns.discard("")

        task = _DiscoveryTask(v1, self._discovery_signals, sorted(known))
        self._api_pool.start(task)

    def _on_discovery_done(self, ok, data):
        # 1 - REHABILITO EL BOTON:
        self.btn_discovery.setEnabled(True)

        # 2 - SI FALLO, MUESTRO EL ERROR (con popup: si solo cambia la etiqueta
        #     de estado el usuario no se entera de que el Discovery fallo):
        if not ok:
            kind = data[0]
            if kind == "api":
                _, status, reason = data[0], data[1], data[2]
                detail = data[3] if len(data) > 3 else reason
                if status == 403:
                    msg = (
                        f"{ICON_WARN}  Discovery bloqueado (403): {self._identity()} no tiene permiso para listar pods\n"
                        f"ni a nivel cluster ni en los namespaces conocidos del kubeconfig.\n\n"
                        f"Revisa los Contexts o tipea un namespace en el combo."
                    )
                    self.lbl_connection_status.setText(
                        f"{ICON_WARN}  Discovery bloqueado (403): {self._identity()} sin permiso de listar pods"
                    )
                    self._log_error(f"Discovery bloqueado (403): {detail or reason}")
                else:
                    msg = f"{ICON_WARN}  Discovery fallo (codigo {status}): {reason}"
                    self.lbl_connection_status.setText(msg)
                    self._log_error(f"Discovery fallo (codigo {status}): {detail or reason}")
                QMessageBox.warning(self, f"{ICON_SEARCH}  Discovery", msg)
            else:
                _, short_msg = data
                self.lbl_connection_status.setText(f"{ICON_WARN}  Discovery fallo: {short_msg}")
                self._log_error(f"Discovery fallo: {short_msg}")
                QMessageBox.warning(self, f"{ICON_SEARCH}  Discovery", f"Discovery fallo:\n{short_msg}")
            self._spinner_stop("resources")
            return

        # 3 - MUESTRO EL DIALOGO DE DISCOVERY CON LOS RESULTADOS:
        summary = data
        self._spinner_stop("resources")
        ctx = getattr(self, "selected_context_name", None) or "?"
        server = getattr(self, "_selected_cluster_server", None) or ""
        host = ""
        if server:
            try:
                host = urlparse(server).hostname or ""
            except Exception:
                pass

        dlg = DiscoveryDialog(summary, ctx, host, self)
        result = dlg.exec()

        # 4 - SI EL USUARIO ELEGIO UN NAMESPACE, LO CAMBIO Y CARGO RECURSOS:
        if result and dlg.selected_namespace:
            ns = dlg.selected_namespace
            self.selected_namespace = ns
            # 4a - SI EL NAMESPACE ESTA EN EL COMBO, LO SELECCIONO:
            idx = self.combo_namespaces.findText(ns)
            if idx >= 0:
                self.combo_namespaces.setCurrentIndex(idx)
            else:
                # 4b - SI NO ESTA, LO AGREGO Y LO SELECCIONO:
                self._loading_namespaces = True
                self.combo_namespaces.addItem(ns)
                self.combo_namespaces.setCurrentText(ns)
                self._loading_namespaces = False
            self._load_resources()


    def on_pod_double_click(self, index):
        # 1 - SI HACEN DOBLE CLIC EN LA COLUMNA IP, NO ABRO DETALLE
        #     (el clic simple en la IP ya copia):
        if index.column() == 3:
            return

        # 2 - OBTENGO EL NOMBRE DEL POD DE LA FILA SELECCIONADA:
        row = index.row()
        name_item = self.table_pods.item(row, 0)
        if not name_item:
            return

        # 3 - EXTRAIGO EL NOMBRE (sin el icono):
        pod_name = name_item.text().replace(f"{ICON_POD}  ", "")

        # 4 - BUSCO EL POD EN EL CACHE:
        pod = self._pods_cache.get(pod_name)
        if not pod:
            return

        # 5 - ABRO LA VENTANA DE DETALLE DEL POD:
        self._open_pod_detail(pod)

    def _open_pod_detail(self, pod):
        # 1 - ABRO LA VENTANA DE DETALLE DEL POD CON INFO DEL CONTEXTO/CLUSTER:
        detail_window = PodDetailWindow(pod, self, context_name=getattr(self, "selected_context_name", None), cluster_server=getattr(self, "_selected_cluster_server", None))
        detail_window.exec()

    def on_pod_table_click(self, row, column):
        # 1 - CLIC EN LA COLUMNA IP (3): COPIO LA IP DEL POD:
        if column != 3:
            return
        item = self.table_pods.item(row, 3)
        if item and item.text() != "-":
            self._copy_to_clipboard(item.text())
            self.lbl_connection_status.setText(f"{ICON_OK}  IP del pod copiada: {item.text()}")

    def on_open_pod_logs(self, pod):
        # 1 - VERIFICO QUE HAYA CONEXION ACTIVA (v1 cacheado):
        v1 = getattr(self, "_v1", None)
        if not v1:
            QMessageBox.warning(
                self,
                f"{ICON_WARN} Sin conexion",
                "No hay conexion activa al cluster: conecta un context primero.",
            )
            return

        # 2 - ABRO EL POPUP DE LOGS EN VIVO (stream con follow).
        #     Todo va en try/except: si algo explota aca, queda en el
        #     minilens.log y la app NO se muere:
        dlg = None
        try:
            dlg = PodLogsDialog(
                v1,
                pod,
                namespace=getattr(self, "selected_namespace", None) or "default",
                identity=self._identity(),
                parent=self,
            )
            dlg.exec()
        except Exception as e:
            try:
                _log.error("LOGS: error en el popup de logs:\n%s", "".join(traceback.format_exception(type(e), e, e.__traceback__)))
            except Exception:
                pass
            self._log_error(f"Error en la ventana de logs: {_short_error(e)}")
            QMessageBox.warning(self, f"{ICON_WARN} Logs", f"La ventana de logs tuvo un error:\n{_short_error(e)}\n\nQuedo registrado en minilens.log")
        finally:
            try:
                if dlg is not None:
                    dlg._drain_timer.stop()
                    dlg._stop_task()
            except Exception:
                pass

    def on_svc_table_click(self, row, column):
        # 1 - CLIC EN LA COLUMNA CLUSTER IP (2): COPIO LA IP DEL SERVICE:
        if column != 2:
            return
        item = self.table_services.item(row, 2)
        if item and item.text() != "-":
            self._copy_to_clipboard(item.text())
            self.lbl_connection_status.setText(f"{ICON_OK}  IP del service copiada: {item.text()}")

    def _clear_map(self):
        # 1 - BORRO TODAS LAS TARJETAS DEL MAPA:
        while self.map_flow.count():
            item = self.map_flow.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_service_map(self, services, pods):
        # 1 - LIMPIO EL MAPA ANTERIOR:
        self._clear_map()

        # 2 - SI NO HAY SERVICES, MUESTRO LOS PODS SUELTOS COMO TARJETAS:
        if not services:
            orphan_card = QFrame()
            orphan_card.setObjectName("service_card")
            orphan_layout = QVBoxLayout(orphan_card)
            orphan_layout.addWidget(QLabel(f"{ICON_POD}  Pods sin Service"))
            for pod in pods:
                phase = (pod.status.phase if pod.status else None) or "Unknown"
                images = _get_pod_images(pod)
                row = QLabel(
                    f"{'🟢' if phase == 'Running' else '🟡'} {pod.metadata.name}\n"
                    f"  {ICON_DOCKER} {', '.join(images) if images else '-'}"
                )
                row.setWordWrap(True)
                orphan_layout.addWidget(row)
            self.map_flow.addWidget(orphan_card)
            return

        # 3 - PARA CADA SERVICE, BUSCO LOS PODS QUE MATCHEAN SU SELECTOR:
        #    Un Service tiene spec.selector = {label_key: label_value, ...}
        #    Un Pod matchea si tiene TODOS esos labels.
        matched_pod_names = set()
        for svc in services:
            selector = (svc.spec.selector if svc.spec else None) or {}
            matched = [p for p in pods if _pod_matches_selector(p, selector)]
            for p in matched:
                matched_pod_names.add(p.metadata.name)

            card = ServiceCard(
                svc,
                matched,
                parent=self.map_container,
                on_pod_click=self._open_pod_detail,
            )
            self.map_flow.addWidget(card)

        # 4 - PODS HUERFANOS (sin ningun Service que los seleccione):
        orphans = [p for p in pods if p.metadata.name not in matched_pod_names]
        if orphans:
            orphan_svc_like = type("FakeSvc", (), {})()
            orphan_svc_like.metadata = type("Meta", (), {"name": "(pods sin service)"})()
            orphan_svc_like.spec = type("Spec", (), {"type": "-", "cluster_ip": "-", "ports": None})()
            card = ServiceCard(
                orphan_svc_like,
                orphans,
                parent=self.map_container,
                on_pod_click=self._open_pod_detail,
            )
            self.map_flow.addWidget(card)


class UserDetailDialog(QDialog):
    """Popup con las credenciales de un user del kubeconfig (enmascaradas)."""

    def __init__(self, user_entry, parent=None):
        super().__init__(parent)
        name = user_entry.get("name", "-")
        user_data = user_entry.get("user", {})

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_USER}  Credenciales: {name}")
        self.resize(480, 420)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")

        layout = QVBoxLayout(self)

        # 2 - NOMBRE EN GRANDE:
        lbl_name = QLabel(f"{ICON_USER}  {name}")
        lbl_name.setStyleSheet("font-size: 20px; font-weight: bold; color: #f5c518; padding: 4px 0;")
        layout.addWidget(lbl_name)

        # 3 - TIPO DE AUTH:
        if user_data.get("token"):
            auth_type = "Token (Bearer)"
        elif user_data.get("client-certificate-data"):
            auth_type = "Client Certificate"
        elif user_data.get("username"):
            auth_type = "Usuario/Password"
        elif user_data.get("auth-provider"):
            auth_type = f"AuthProvider: {user_data.get('auth-provider', {}).get('name', '?')}"
        elif user_data.get("exec"):
            exec_cmd = user_data.get("exec", {}).get("command", "?")
            auth_type = f"Exec plugin: {exec_cmd}"
        else:
            auth_type = "Desconocido"

        form = QFormLayout()
        form.addRow("Tipo de auth:", QLabel(auth_type))

        # 3a - TOKEN ENMASCARADO (solo longitud + primeros caracteres):
        token = user_data.get("token", "")
        if token:
            form.addRow("Token:", QLabel(f"{token[:8]}... ({len(token)} caracteres)"))
        else:
            form.addRow("Token:", QLabel("-"))

        # 3b - CERTIFICADO:
        has_cert = bool(user_data.get("client-certificate-data"))
        form.addRow("Client cert:", QLabel("presente" if has_cert else "-"))
        has_key = bool(user_data.get("client-key-data"))
        form.addRow("Client key:", QLabel("presente" if has_key else "-"))

        # 3c - USERNAME:
        form.addRow("Username:", QLabel(user_data.get("username", "-")))

        # 3d - AUTH-PROVIDER (oidc, gcp, etc):
        ap = user_data.get("auth-provider")
        if ap:
            form.addRow("Auth provider:", QLabel(ap.get("name", "-")))

        # 3e - EXEC (exec plugins):
        ex = user_data.get("exec")
        if ex:
            form.addRow("Exec command:", QLabel(ex.get("command", "-")))

        layout.addLayout(form)

        # 4 - NOTA DE SEGURIDAD:
        lbl_note = QLabel(
            "Las credenciales completas no se muestran por seguridad.\n"
            "Estan en el archivo kubeconfig original."
        )
        lbl_note.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(lbl_note)

        # 5 - BOTON CERRAR:
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


class AddContextDialog(QDialog):
    """Dialogo simple para agregar un context al cluster seleccionado.

    El cluster y el user son los del context actual (solo lectura, arriba):
    el UNICO dato que pide es el namespace. El nombre del context se genera
    solo como '<cluster>-<namespace>'.
    """

    def __init__(self, cluster_name, user_name, default_ns, parent=None):
        super().__init__(parent)
        self._cluster_name = cluster_name or "-"
        self._user_name = user_name or "-"
        self.setWindowTitle(f"{ICON_CONTEXT}  Agregar context a {self._cluster_name}")
        self.setMinimumWidth(420)
        self.result_ctx = None

        layout = QVBoxLayout(self)

        # 1 - IDENTIDAD FIJA (solo lectura): cluster y user del context actual:
        form = QFormLayout()
        lbl_cluster = QLabel(self._cluster_name)
        lbl_cluster.setStyleSheet("color: #f5c518; font-weight: bold;")
        lbl_user = QLabel(self._user_name)
        lbl_user.setStyleSheet("color: #f5c518; font-weight: bold;")
        form.addRow("Cluster:", lbl_cluster)
        form.addRow("User:", lbl_user)

        # 2 - UNICO CAMPO: NAMESPACE (Enter = aceptar):
        self.txt_namespace = QLineEdit(default_ns or "")
        self.txt_namespace.setPlaceholderText("namespace (ej: cyber-battle-lab)")
        form.addRow("Namespace:", self.txt_namespace)
        layout.addLayout(form)

        # 3 - PREVIEW DEL NOMBRE DEL CONTEXT QUE SE VA A CREAR:
        self.lbl_preview = QLabel("")
        self.lbl_preview.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        layout.addWidget(self.lbl_preview)

        # 4 - BOTONES:
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_ok = QPushButton(f"{ICON_OK}  Agregar context")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_ok)
        layout.addLayout(btns)

        # 5 - WIRING: Enter acepta, al tipear actualizo el preview:
        self.txt_namespace.returnPressed.connect(self._accept)
        self.txt_namespace.textChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self):
        # 1 - MUESTRO EL NOMBRE DE CONTEXT QUE SE VA A GENERAR:
        ns = self.txt_namespace.text().strip()
        self.lbl_preview.setText(
            f"Context nuevo:  {self._cluster_name}-{ns}" if ns else "Context nuevo:  -"
        )

    def _accept(self):
        # 1 - VALIDO EL NAMESPACE Y ARMO EL RESULTADO:
        ns = self.txt_namespace.text().strip()
        if not ns:
            QMessageBox.warning(self, f"{ICON_WARN} Falta namespace", "Escribi el namespace del context")
            return
        self.result_ctx = {
            "name": f"{self._cluster_name}-{ns}",
            "context": {
                "cluster": self._cluster_name,
                "user": self._user_name,
                "namespace": ns,
            },
        }
        self.accept()


class DiscoveryDialog(QDialog):
    """Dialogo de Discovery: muestra todos los namespaces del cluster con pods/services."""

    def __init__(self, summary, context_name, host, parent=None):
        super().__init__(parent)
        self.selected_namespace = None
        self._summary = summary

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_SEARCH}  Discovery del cluster")
        self.resize(700, 600)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 2 - BANNER DE ENTORNO:
        banner = QFrame()
        banner.setStyleSheet(
            "QFrame { background-color: #2a2a3a; border: 2px solid #f5c518; "
            "border-radius: 6px; padding: 8px; }"
        )
        banner_layout = QVBoxLayout(banner)
        banner_layout.setSpacing(2)
        banner_layout.setContentsMargins(10, 6, 10, 6)

        lbl_title = QLabel(f"{ICON_CLUSTER}  ENTORNO")
        lbl_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #f5c518; letter-spacing: 1px;")
        banner_layout.addWidget(lbl_title)

        if host:
            lbl_host = QLabel(f"  {host}")
            lbl_host.setStyleSheet("font-size: 18px; font-weight: bold; color: #e0e0e0;")
            banner_layout.addWidget(lbl_host)

        lbl_ctx = QLabel(f"  Context: {context_name}")
        lbl_ctx.setStyleSheet("font-size: 13px; color: #aaa;")
        banner_layout.addWidget(lbl_ctx)
        layout.addWidget(banner)

        # 3 - RESUMEN GENERAL:
        total_pods = sum(s[1] for s in summary)
        total_svcs = sum(s[2] for s in summary)
        lbl_summary = QLabel(
            f"{ICON_SEARCH}  {len(summary)} namespaces  |  {total_pods} pods  |  {total_svcs} services"
        )
        lbl_summary.setStyleSheet("font-size: 14px; color: #f5c518; font-weight: bold; padding: 4px 0;")
        layout.addWidget(lbl_summary)

        # 4 - TABLA DE NAMESPACES:
        self.table = QTableWidget(len(summary), 4)
        self.table.setHorizontalHeaderLabels(["Namespace", "Pods", "Services", "Preview pods"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_namespace_double_click)

        for i, (ns, n_pods, n_svcs, pod_names) in enumerate(summary):
            # 4a - NAMESPACE:
            item_ns = QTableWidgetItem(ns)
            if n_pods > 0:
                item_ns.setForeground(QColor("#f5c518"))
            else:
                item_ns.setForeground(QColor("#666"))
            self.table.setItem(i, 0, item_ns)

            # 4b - PODS COUNT:
            item_pods = QTableWidgetItem(str(n_pods))
            if n_pods > 0:
                item_pods.setForeground(QColor("#2ecc71"))
            else:
                item_pods.setForeground(QColor("#666"))
            self.table.setItem(i, 1, item_pods)

            # 4c - SERVICES COUNT:
            item_svcs = QTableWidgetItem(str(n_svcs))
            if n_svcs > 0:
                item_svcs.setForeground(QColor("#3b8ad4"))
            else:
                item_svcs.setForeground(QColor("#666"))
            self.table.setItem(i, 2, item_svcs)

            # 4d - PREVIEW DE PODS (primeros 5):
            preview = ", ".join(pod_names) if pod_names else "(vacio)"
            item_preview = QTableWidgetItem(preview)
            item_preview.setForeground(QColor("#888"))
            self.table.setItem(i, 3, item_preview)

        layout.addWidget(self.table, stretch=1)

        # 5 - BOTONES:
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_select = QPushButton(f"{ICON_OK}  Seleccionar namespace")
        btn_select.setStyleSheet("QPushButton { background-color: #2ecc71; color: #1a1a1a; font-weight: bold; padding: 6px 12px; }")
        btn_select.clicked.connect(self._on_select_clicked)
        btn_row.addWidget(btn_select)

        btn_close = QPushButton("Cerrar")
        btn_close.setStyleSheet("QPushButton { background-color: #444; color: #e0e0e0; }")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _on_namespace_double_click(self, index):
        # 1 - DOBLE CLIC EN UNA FILA: SELECCIONO EL NAMESPACE Y CIERRO:
        row = index.row()
        ns = self.table.item(row, 0).text()
        if self._summary[row][1] > 0 or self._summary[row][2] > 0:
            self.selected_namespace = ns
            self.accept()

    def _on_select_clicked(self):
        # 1 - BOTON SELECCIONAR: TOMA LA FILA ACTUAL:
        row = self.table.currentRow()
        if row < 0:
            return
        ns = self.table.item(row, 0).text()
        self.selected_namespace = ns
        self.accept()


class _LogsStreamTask(QRunnable):
    # TASK: sigue los logs de un pod (follow=True) y pone cada linea en una
    # cola para que el dialogo la consuma con un QTimer. El worker NO toca
    # ningun objeto de Qt: si el dialogo se cierra, solo escribe en la cola
    # (antes emitia senales Qt cross-thread y crasheaba al cerrar la ventana):

    # registro global de tasks vivos (evita que el GC recolecte el QRunnable
    # mientras el thread pool todavia lo esta ejecutando: crash clasico):
    _ALIVE = set()

    def __init__(self, v1, pod_name, namespace, container, out_queue):
        super().__init__()
        self._v1 = v1
        self._pod_name = pod_name
        self._ns = namespace
        self._container = container
        self._out = out_queue
        self._stop = False
        self._resp = None
        self.setAutoDelete(False)
        _LogsStreamTask._ALIVE.add(self)

    def stop(self):
        # 1 - SOLO MARCO EL CORTE. NO toco el socket desde aca: si el worker
        #     esta bloqueado en un read del SSL y cierro el socket desde el
        #     hilo de la UI, la app se cuelga (eso era el freeze al cerrar).
        #     El worker es el UNICO que toca la conexion, y se da cuenta del
        #     corte en el proximo chunk o en el timeout de lectura (30s max):
        self._stop = True

    def run(self):
        # Estructura: loop de reconexion. Cada intento pide el stream con
        # read-timeout de 30s; si el pod esta callado, el read corta por
        # timeout y reconecto pidiendo SOLO lo generado desde la ultima
        # linea recibida (sin duplicar el tail inicial).
        last_ts = None
        try:
            while not self._stop:
                try:
                    # 1 - PIDO LOS LOGS CON FOLLOW. SOLO LAS ULTIMAS 200
                    #     LINEAS: traer el log completo de un pod verboso
                    #     es una locura de memoria y de render:
                    kwargs = {
                        "name": self._pod_name,
                        "namespace": self._ns,
                        "container": self._container or None,
                        "follow": True,
                        "timestamps": True,
                        "_preload_content": False,
                        "_request_timeout": (10, 30),
                    }
                    if last_ts is None:
                        kwargs["tail_lines"] = 200
                    else:
                        # 1a - RECONEXION: solo lo generado desde la ultima
                        #      linea recibida (sin duplicar):
                        elapsed = int((datetime.now(timezone.utc) - last_ts).total_seconds()) + 1
                        kwargs["since_seconds"] = max(1, elapsed)
                    self._resp = self._v1.read_namespaced_pod_log(**kwargs)
                    buf = b""
                    for chunk in self._resp.stream(4096):
                        if self._stop:
                            break
                        buf += chunk
                        # 2 - ENCOLO CADA LINEA COMPLETA:
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            line = raw.decode("utf-8", "replace").rstrip("\r")
                            ts = _parse_line_ts(line)
                            if ts is not None:
                                last_ts = ts
                            self._out.put(("line", line))
                    try:
                        # 2a - EL WORKER CIERRA SU PROPIA CONEXION:
                        self._resp.close()
                    except Exception:
                        pass
                    if self._stop:
                        break
                    self._out.put(("status", "reconectando..."))
                except ApiException as e:
                    # 2b - 403/401/etc: reintentar no va a cambiar el RBAC:
                    try:
                        _log.error("LogsStream ApiException %s: %s", e.status, _api_error_message(e))
                    except Exception:
                        pass
                    if not self._stop:
                        self._out.put(("status", f"api|{e.status}|{_api_error_message(e)}"))
                    break
                except Exception as e:
                    if self._stop:
                        break
                    if _is_read_timeout(e):
                        # 2c - POD CALLADO: reconecto (el loop de arriba):
                        continue
                    try:
                        _log.error("LogsStream '%s/%s': %s", self._ns, self._pod_name, "".join(traceback.format_exception(type(e), e, e.__traceback__)))
                    except Exception:
                        pass
                    self._out.put(("status", f"error|{_short_error(e)}"))
                    break
            if self._stop:
                self._out.put(("status", "cerrado"))
            else:
                self._out.put(("status", "fin"))
        finally:
            # 3 - ME SACO DEL REGISTRO (el thread pool ya termino conmigo):
            _LogsStreamTask._ALIVE.discard(self)


class _LogLineRow(QFrame):
    """Cuadradito de UNA linea de log: fecha-hora a la izquierda, mensaje a la derecha.

    Estados visuales (borde izquierdo de 4px para no mover el layout):
      - normal:  gris
      - marked:  ROJO (linea marcada por el usuario con un clic)
      - new:     VERDE (lineas que llegaron DESPUES de la marcada)
    """

    def __init__(self, ts, msg, raw="", on_click=None, parent=None):
        super().__init__(parent)
        self.setObjectName("log_row")
        self._state = "normal"
        self._on_click = on_click
        self._raw = raw
        self._apply_style()
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 4, 3)
        lay.setSpacing(10)

        # 1 - FECHA-HORA (columna fija, amarillo, monospace):
        lbl_ts = QLabel(ts or "")
        lbl_ts.setStyleSheet(
            "color: #f5c518; font-family: Consolas, monospace; font-size: 12px;"
            " border: none; background: transparent;"
        )
        lbl_ts.setMinimumWidth(110)
        lbl_ts.setMaximumWidth(150)
        lay.addWidget(lbl_ts)

        # 2 - MENSAJE (seleccionable, monospace, con wrap):
        lbl_msg = QLabel(msg)
        lbl_msg.setTextFormat(Qt.PlainText)
        lbl_msg.setWordWrap(True)
        lbl_msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_msg.setStyleSheet(
            "color: #e0e0e0; font-family: Consolas, 'Courier New', monospace; font-size: 12px;"
            " border: none; background: transparent;"
        )
        lay.addWidget(lbl_msg, stretch=1)

        # 3 - BOTON PORTAPAPELES (a la derecha): copia la linea completa
        #     (hora + mensaje) sin marcar la fila:
        btn_copy = QPushButton(ICON_DETAIL)
        btn_copy.setFixedSize(26, 22)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setToolTip("Copiar esta linea al portapapeles (hora + mensaje)")
        btn_copy.setStyleSheet(
            "QPushButton { background-color: #2a2a2a; color: #f5c518;"
            " border: 1px solid #555; border-radius: 4px; font-size: 12px; padding: 1px 6px; }"
            "QPushButton:hover { background-color: #3d3320; border-color: #f5c518; }"
        )
        btn_copy.clicked.connect(lambda checked=False, text=self._raw: QGuiApplication.clipboard().setText(text))
        lay.addWidget(btn_copy)

    def set_normal(self):
        # 1 - VUELVO AL ESTADO NORMAL:
        self._state = "normal"
        self._apply_style()

    def set_marked(self):
        # 1 - MARCO LA LINEA EN ROJO (es la marca "lo nuevo empieza aca"):
        self._state = "marked"
        self._apply_style()

    def set_new(self):
        # 1 - LA PINTO COMO LINEA NUEVA (verde, llego despues de la marca):
        self._state = "new"
        self._apply_style()

    def _apply_style(self):
        # 1 - PINTO LA FILA SEGUN EL ESTADO (el borde izquierdo es SIEMPRE
        #     de 4px: cambia el color, no el ancho, para que no salte nada):
        styles = {
            "normal": "background-color: #222; border: 1px solid #555; border-left: 4px solid #444;",
            "marked": "background-color: #2a1515; border: 1px solid #e74c3c; border-left: 4px solid #e74c3c;",
            "new":    "background-color: #16211a; border: 1px solid #2f5a3d; border-left: 4px solid #2ecc71;",
        }
        self.setStyleSheet(f"QFrame#log_row {{ {styles[self._state]} border-radius: 6px; }}")

    def mousePressEvent(self, event):
        # 1 - CLIC EN LA FILA = MARCAR/DESMARCAR (si tiene callback):
        if self._on_click:
            self._on_click()
        super().mousePressEvent(event)


class PodLogsDialog(QDialog):
    """Popup con los logs de un pod en tiempo real (stream follow).

    Cada linea se muestra en un cuadradito separado: fecha-hora a la
    izquierda y el mensaje a la derecha. Incluye selector de container,
    pausar, copiar todo y limpiar.
    """

    MAX_ROWS = 300

    def __init__(self, v1, pod, namespace, identity, parent=None):
        super().__init__(parent)
        # 0 - LOG DE APERTURA (lo primero de todo, antes de tocar nada):
        try:
            _log.info("LOGS: abro popup de logs pod='%s' ns='%s'", getattr(pod.metadata, "name", "?"), namespace)
        except Exception:
            pass
        self._pod = pod
        self._pod_name = pod.metadata.name if pod.metadata else "?"
        self._ns = namespace or "default"
        self._v1 = v1
        self._task = None
        self._paused = False
        self._rows = []
        self._raw_lines = []
        self._n = 0
        self._marked_row = None
        self._follow = True

        self.setWindowTitle(f"{ICON_LOGS}  Logs: {self._pod_name}  ({self._ns})")
        self.resize(1100, 700)
        self.setStyleSheet("QDialog { background-color: #1a1a1a; }")

        layout = QVBoxLayout(self)

        # 1 - HEADER: pod + identidad (user@cluster/context):
        header = QHBoxLayout()
        lbl_title = QLabel(f"{ICON_LOGS}  {self._pod_name}")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #f5c518;")
        header.addWidget(lbl_title)
        header.addStretch()
        lbl_id = QLabel(identity)
        lbl_id.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        header.addWidget(lbl_id)
        layout.addLayout(header)

        # 2 - BARRA: selector de container + pausar + copiar + limpiar:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Container:"))
        self.cmb_container = QComboBox()
        containers = [c.name for c in (pod.spec.containers or [])] if pod.spec and pod.spec.containers else []
        self.cmb_container.addItems(containers or ["(default)"])
        self.cmb_container.currentIndexChanged.connect(self._on_container_changed)
        bar.addWidget(self.cmb_container)

        self.btn_pause = QPushButton(f"{ICON_WARN}  Pausar")
        self.btn_pause.setToolTip(
            "Pausa SOLO el render en pantalla (la conexion sigue viva).\n"
            "Para cortar la conexion, cerrá la ventana con la X."
        )
        self.btn_pause.clicked.connect(self._toggle_pause)
        bar.addWidget(self.btn_pause)

        btn_copy = QPushButton(f"{ICON_DETAIL}  Copiar todo")
        btn_copy.clicked.connect(self._copy_all)
        bar.addWidget(btn_copy)

        # 2a - BOTON CLS: limpia SOLO la vista local (no toca el pod ni el
        #      stream: las lineas nuevas siguen llegando desde cero):
        btn_clear = QPushButton(f"{ICON_TRASH}  CLS")
        btn_clear.setToolTip("CLS: limpia SOLO la vista local (el stream del pod sigue corriendo)")
        btn_clear.clicked.connect(self._clear_rows)
        bar.addWidget(btn_clear)

        bar.addStretch()
        self.lbl_count = QLabel("0 lineas")
        self.lbl_count.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        bar.addWidget(self.lbl_count)
        layout.addLayout(bar)

        # 3 - SCROLL CON LAS LINEAS DE LOG (cada una en su cuadradito):
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        holder = QWidget()
        self.logs_layout = QVBoxLayout(holder)
        self.logs_layout.setContentsMargins(4, 4, 4, 4)
        self.logs_layout.setSpacing(3)
        self.logs_layout.addStretch()
        self.scroll.setWidget(holder)
        layout.addWidget(self.scroll, stretch=1)

        # 3a - AUTO-FOLLOW: mientras el usuario este mirando el final,
        #      cada linea nueva empuja la vista abajo del todo. Si scrollea
        #      hacia arriba (para leer algo), dejo de seguirlo; vuelve a
        #      seguir cuando baje de nuevo al final:
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_moved)

        # 4 - ESTADO DEL STREAM:
        self.lbl_status = QLabel(f"{ICON_INFO}  Conectando al stream de logs...")
        self.lbl_status.setStyleSheet("color: #f5c518; font-size: 12px; padding: 2px;")
        layout.addWidget(self.lbl_status)

        # 5 - COLA + TIMER: el worker encola las lineas (sin tocar Qt) y un
        #      timer las consume en el hilo de la UI. Si uso senales Qt
        #      cross-thread y el dialogo se destruye con lineas pendientes,
        #      la app crashea al cerrar la ventana de logs:
        self._queue = queue.Queue()
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(50)
        self._drain_timer.timeout.connect(self._drain_queue)
        self._drain_timer.start()

        # 6 - OVERLAY DE CARGA (el mismo spinner amarillo del resto de la
        #     app): visible hasta que llegan las lineas o termina el stream:
        self._overlay = _LoadingOverlay(self)
        self._overlay.start("Cargando logs del pod...")

        self._start_stream()

    def _drain_queue(self):
        # 1 - CONSUMO LA COLA DEL STREAM (max 25 items por tick: meter 200
        #      filas de golpe congelaba la UI mientras cargaba):
        for _ in range(25):
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "line":
                    self._on_line(payload)
                else:
                    self._on_status(payload)
            except Exception as e:
                # un item roto no tiene que matar el drenaje ni la app:
                try:
                    _log.error("LOGS: error procesando item de cola (%s): %s", kind, e)
                except Exception:
                    pass

    def _start_stream(self):
        # 1 - CORTO EL STREAM ANTERIOR Y ARRANCO UNO NUEVO (container actual):
        self._stop_task()
        container = self.cmb_container.currentText() if self.cmb_container.count() else None
        if container == "(default)":
            container = None
        self._task = _LogsStreamTask(self._v1, self._pod_name, self._ns, container, self._queue)
        QThreadPool.globalInstance().start(self._task)
        # 1a - VUELVO A MOSTRAR EL OVERLAY DE CARGA hasta que lleguen lineas:
        try:
            self._overlay.start("Cargando logs del pod...")
        except Exception:
            pass

    def _stop_task(self):
        # 1 - CIERRO EL STREAM ACTIVO (si hay):
        if self._task:
            self._task.stop()
            self._task = None

    def _on_scroll_moved(self, value):
        # 1 - ACTUALIZO EL AUTO-FOLLOW SEGUN DONDE ESTE EL USUARIO:
        #     abajo del todo = sigo empujando la vista con cada linea nueva;
        #     scrolleo hacia arriba = dejo de seguir (esta leyendo algo):
        sb = self.scroll.verticalScrollBar()
        self._follow = value >= sb.maximum() - 40

    def _on_container_changed(self, _idx):
        # 1 - CAMBIO DE CONTAINER: REINICIO EL STREAM:
        self._clear_rows()
        self._start_stream()

    def _toggle_pause(self):
        # 1 - PAUSO/REANUDO EL RENDER (el stream sigue vivo):
        self._paused = not self._paused
        self.btn_pause.setText(f"{ICON_OK}  Seguir" if self._paused else f"{ICON_WARN}  Pausar")

    def _on_line(self, raw):
        # 1 - SI ESTA PAUSADO, DESCARTO LA LINEA (el stream sigue):
        if self._paused:
            return

        # 1a - CON LA PRIMERA LINEA QUE LLEGA, CORTO EL OVERLAY DE CARGA:
        if self._n == 0:
            try:
                self._overlay.stop()
            except Exception:
                pass

        # 2 - SEPARO FECHA-HORA DEL MENSAJE Y AGREGO EL CUADRADITO:
        ts, msg = _split_log_line(raw)

        # 2a - SI EL MENSAJE ES JSON, LO MUESTRO PRETTY (incluye JSON
        #      anidado dentro del campo 'message'):
        pretty = _pretty_json(msg)
        if pretty:
            msg = pretty

        row = _LogLineRow(ts, msg, raw=raw)
        row._on_click = lambda r=row: self._on_row_clicked(r)
        self.logs_layout.insertWidget(self.logs_layout.count() - 1, row)
        self._rows.append(row)
        self._raw_lines.append(raw)
        self._n += 1
        self.lbl_count.setText(f"{self._n} lineas")

        # 2a - SI HAY UNA LINEA MARCADA, ESTA NUEVA SE PINTA VERDE:
        if self._marked_row is not None:
            row.set_new()

        # 2b - CAP: BORRO LAS LINEAS MAS VIEJAS SI ME PASE:
        while len(self._rows) > self.MAX_ROWS:
            old = self._rows.pop(0)
            # si la linea marcada salio por el limite, pierde la marca:
            if old is self._marked_row:
                self._marked_row = None
            self.logs_layout.removeWidget(old)
            old.deleteLater()
        while len(self._raw_lines) > self.MAX_ROWS:
            self._raw_lines.pop(0)

        # 2c - AUTO-FOLLOW: SIEMPRE ABAJO DEL TODO, salvo que el usuario
        #      haya scrolleado para arriba o haya marcado una linea:
        if self._follow:
            sb = self.scroll.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_status(self, s):
        # 1 - ACTUALIZO LA BARRA DE ESTADO SEGUN LO QUE PASO:
        if s == "reconectando...":
            # 1a - POD CALLADO: el worker reconecta solo (sin duplicar lineas):
            self.lbl_status.setText(f"{ICON_INFO}  Reconectando al stream de logs...")
            self.lbl_status.setStyleSheet("color: #f5c518; font-size: 12px; padding: 2px;")
            return
        try:
            self._overlay.stop()
        except Exception:
            pass
        if s.startswith("api|"):
            _, code, msg = s.split("|", 2)
            self.lbl_status.setText(f"{ICON_WARN}  Error de la API (codigo {code}): {msg}")
            self.lbl_status.setStyleSheet("color: #e74c3c; font-size: 12px; padding: 2px;")
        elif s == "fin":
            self.lbl_status.setText(f"{ICON_INFO}  Stream terminado (el pod cerro el log)")
        else:
            self.lbl_status.setText(f"{ICON_INFO}  Stream cerrado")

    def _on_row_clicked(self, row):
        # 1 - SI LA LINEA YA ESTABA MARCADA, QUITO LA MARCA:
        if self._marked_row is row:
            self._unmark()
            return

        # 1a - EL USUARIO ESTA MIRANDO/INTERACTUANDO: corto el auto-follow
        #      para que las lineas nuevas no le muevan la vista:
        self._follow = False

        # 2 - REINICIO: la marca anterior y las lineas "nuevas" vuelven a normal:
        for r in self._rows:
            if r is not row and r._state in ("new", "marked"):
                r.set_normal()

        # 3 - MARCO LA ELEGIDA EN ROJO: lo que llegue despues se pinta verde:
        self._marked_row = row
        row.set_marked()
        self.lbl_status.setText(
            f"{ICON_INFO}  Linea marcada: lo que llegue de ahora en mas se resalta en verde"
        )
        self.lbl_status.setStyleSheet("color: #f5c518; font-size: 12px; padding: 2px;")

    def _unmark(self):
        # 1 - QUITO LA MARCA Y DEVUELVO TODAS LAS LINEAS A NORMAL:
        if self._marked_row is not None:
            self._marked_row.set_normal()
        self._marked_row = None
        for r in self._rows:
            if r._state == "new":
                r.set_normal()
        self.lbl_status.setText(f"{ICON_INFO}  Marca quitada")

    def _copy_all(self):
        # 1 - COPIO TODAS LAS LINEAS VISIBLES AL PORTAPAPELES:
        QGuiApplication.clipboard().setText("\n".join(self._raw_lines))

    def _clear_rows(self):
        # 1 - CLS: LIMPIO SOLO LA VISTA LOCAL (el stream del pod sigue vivo):
        for r in self._rows:
            self.logs_layout.removeWidget(r)
            r.deleteLater()
        self._rows = []
        self._raw_lines = []
        self._marked_row = None
        self._n = 0
        self.lbl_count.setText("0 lineas")
        self.lbl_status.setText(f"{ICON_INFO}  Vista limpia (el stream sigue corriendo)")

    def _shutdown_stream(self):
        # 1 - CIERRE INTERNO: corto el timer y el stream (idempotente, con
        #     try/except: NADA de lo que pase aqui puede explotar la app):
        try:
            self._drain_timer.stop()
        except Exception as e:
            try:
                _log.error("LOGS: error parando timer: %s", e)
            except Exception:
                pass
        try:
            self._stop_task()
        except Exception as e:
            try:
                _log.error("LOGS: error parando stream: %s", e)
            except Exception:
                pass

    def closeEvent(self, e):
        # 1 - LOG ANTES DE CUALQUIER COSA (si crashea, queda registrado):
        try:
            _log.info("LOGS: cierro popup de logs pod='%s' ns='%s' (lineas=%s)", self._pod_name, self._ns, self._n)
        except Exception:
            pass
        try:
            # 2 - corto el timer, cierro el stream y vacio la cola (el
            #     worker puede seguir un rato pero solo escribe en la
            #     cola: ya no toca ningun objeto de la UI):
            self._drain_timer.stop()
        except Exception as e:
            try:
                _log.error("LOGS: error parando timer en cierre: %s", e)
            except Exception:
                pass
        try:
            self._stop_task()
        except Exception as e:
            try:
                _log.error("LOGS: error parando stream en cierre: %s", e)
            except Exception:
                pass
        try:
            # 3 - VACIO LA COLA: nada pendiente va a renderizar despues:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        except Exception as e:
            try:
                _log.error("LOGS: error vaciando cola en cierre: %s", e)
            except Exception:
                pass
        super().closeEvent(e)

    def done(self, r):
        # 1 - CIERRE POR CUALQUIER VIA (Esc/reject/accept): corto todo antes:
        try:
            self._drain_timer.stop()
        except Exception:
            pass
        try:
            self._stop_task()
        except Exception:
            pass
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass
        super().done(r)


class PodDetailWindow(QDialog):
    """Ventana modal con todos los detalles de un Pod."""

    def __init__(self, pod, parent=None, context_name=None, cluster_server=None):
        super().__init__(parent)

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_POD}  Detalle del Pod: {pod.metadata.name}")
        self.resize(700, 800)

        # 2 - LAYOUT PRINCIPAL CON SCROLL:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll.setWidget(scroll_content)
        main_layout = QVBoxLayout(scroll_content)

        outer_layout = QVBoxLayout(self)
        outer_layout.addWidget(scroll)

        # 3 - BOTON CERRAR:
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        outer_layout.addWidget(btn_close)

        # 3a - BANNER DE ENTORNO (cluster + context + server bien visible):
        self._add_env_banner(main_layout, pod, context_name, cluster_server)

        # 4 - POBLA TODAS LAS SECCIONES (orden por importancia):
        #    Primero lo mas importante: datos basicos, containers, volumes, env vars.
        #    Despues lo secundario: labels, annotations, conditions.
        self._add_datos_basicos(main_layout, pod)
        self._add_containers(main_layout, pod)
        self._add_volumes(main_layout, pod)
        self._add_env_vars(main_layout, pod)
        self._add_labels(main_layout, pod)
        self._add_annotations(main_layout, pod)
        self._add_conditions(main_layout, pod)

    def _add_env_banner(self, layout, pod, context_name, cluster_server):
        # 1 - EXTRAIGO HOST Y PUERTO DEL SERVER DEL CLUSTER:
        host = ""
        if cluster_server:
            try:
                host = urlparse(cluster_server).hostname or ""
            except Exception:
                pass

        # 2 - BANNER CON FONDO DESTACADO (cluster + context + namespace):
        banner = QFrame()
        banner.setStyleSheet(
            "QFrame { background-color: #2a2a3a; border: 2px solid #f5c518; "
            "border-radius: 6px; padding: 8px; }"
        )
        banner_layout = QVBoxLayout(banner)
        banner_layout.setSpacing(2)
        banner_layout.setContentsMargins(10, 6, 10, 6)

        # 2a - TITULO "ENTORNO" EN AMARILLO:
        lbl_title = QLabel(f"{ICON_CLUSTER}  ENTORNO")
        lbl_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #f5c518; letter-spacing: 1px;")
        banner_layout.addWidget(lbl_title)

        # 2b - CLUSTER HOST EN GRANDE:
        if host:
            lbl_cluster = QLabel(f"  {host}")
            lbl_cluster.setStyleSheet("font-size: 18px; font-weight: bold; color: #e0e0e0;")
            banner_layout.addWidget(lbl_cluster)

        # 2c - CONTEXT Y NAMESPACE EN LINEA:
        info_parts = []
        if context_name:
            info_parts.append(f"Context: {context_name}")
        if pod.metadata and pod.metadata.namespace:
            info_parts.append(f"Namespace: {pod.metadata.namespace}")
        if info_parts:
            lbl_info = QLabel(f"  {'  |  '.join(info_parts)}")
            lbl_info.setStyleSheet("font-size: 13px; color: #aaa;")
            banner_layout.addWidget(lbl_info)

        layout.addWidget(banner)

    def _add_section_title(self, layout, title):
        lbl = QLabel(title)
        lbl.setObjectName("detail_value")
        lbl.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #f5c518; "
            "border-bottom: 2px solid #f5c518; padding: 8px 0 4px 0; margin-top: 10px;"
        )
        layout.addWidget(lbl)

    def _add_row(self, layout, label, value):
        row_layout = QHBoxLayout()
        lbl = QLabel(f"{label}:")
        lbl.setStyleSheet("font-weight: bold; color: #e0e0e0; min-width: 140px;")
        row_layout.addWidget(lbl)
        # 1 - SI EL VALOR ES UNA IP, LA MUESTRO COMO BOTON CLIQUEABLE
        #     (clic = copiar al portapapeles). Si no, label normal:
        if _looks_like_ip(value):
            row_layout.addWidget(_make_ip_button(str(value), tooltip_prefix=label))
            row_layout.addStretch()
        else:
            val = QLabel(str(value))
            val.setWordWrap(True)
            val.setStyleSheet("color: #f5c518;")
            row_layout.addWidget(val, stretch=1)
        layout.addLayout(row_layout)

    def _add_datos_basicos(self, layout, pod):
        self._add_section_title(layout, f"{ICON_INFO}  Datos basicos")

        meta = pod.metadata
        status = pod.status
        spec = pod.spec

        # 1 - NOMBRE EN GRANDE Y NEGRITA (lo mas importante):
        name_label = QLabel(f"{ICON_POD}  {meta.name}")
        name_label.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #f5c518; "
            "padding: 6px 0 2px 0;"
        )
        layout.addWidget(name_label)

        # 2 - DATOS CLAVE JUSTO DEBAJO DEL NOMBRE (lo mas relevante):
        self._add_row(layout, "Pod IP", status.pod_ip if status and status.pod_ip else "-")
        self._add_row(layout, "Phase", status.phase if status and status.phase else "-")
        self._add_row(layout, "QoS class", status.qos_class if status and status.qos_class else "-")
        self._add_row(layout, "Start time", status.start_time.strftime("%Y-%m-%d %H:%M:%S") if status and status.start_time else "-")

        # 3 - DATOS SECUNDARIOS DEBAJO:
        self._add_row(layout, "Namespace", meta.namespace)
        self._add_row(layout, "Node", spec.node_name if spec and spec.node_name else "-")
        self._add_row(layout, "Host IP", status.host_ip if status and status.host_ip else "-")
        self._add_row(layout, "Restart policy", spec.restart_policy if spec and spec.restart_policy else "-")
        self._add_row(layout, "Service account", spec.service_account if spec and spec.service_account else "-")
        self._add_row(layout, "UID", meta.uid)
        self._add_row(layout, "Creado", meta.creation_timestamp.strftime("%Y-%m-%d %H:%M:%S") if meta.creation_timestamp else "-")
        self._add_row(layout, "Priority", spec.priority if spec and spec.priority is not None else "-")
        self._add_row(layout, "DNS policy", spec.dns_policy if spec and spec.dns_policy else "-")

    def _add_labels(self, layout, pod):
        self._add_section_title(layout, f"\U0001F3F7  Labels")
        meta = pod.metadata
        if meta.labels:
            for k, v in meta.labels.items():
                self._add_row(layout, k, v)
        else:
            layout.addWidget(QLabel("(sin labels)"))

    def _add_annotations(self, layout, pod):
        self._add_section_title(layout, f"\U0001F4DD  Annotations")
        meta = pod.metadata
        if meta.annotations:
            for k, v in meta.annotations.items():
                self._add_row(layout, k, v)
        else:
            layout.addWidget(QLabel("(sin annotations)"))

    def _add_conditions(self, layout, pod):
        self._add_section_title(layout, f"{ICON_OK}  Conditions")
        status = pod.status
        if status and status.conditions:
            for cond in status.conditions:
                val = "true" if cond.status == "True" else "false"
                self._add_row(layout, cond.type, val)
        else:
            layout.addWidget(QLabel("(sin conditions)"))

    def _add_containers(self, layout, pod):
        self._add_section_title(layout, f"{ICON_POD}  Containers")
        spec = pod.spec
        status = pod.status

        if not spec or not spec.containers:
            layout.addWidget(QLabel("(sin containers)"))
            return

        # 1 - MAPEO DE ESTADOS DE CONTAINERS POR NOMBRE:
        cs_map = {}
        if status and status.container_statuses:
            for cs in status.container_statuses:
                cs_map[cs.name] = cs

        for c in spec.containers:
            cs = cs_map.get(c.name, None)

            # 2 - GRUPO PARA CADA CONTAINER:
            group = QGroupBox(f"{ICON_POD}  {c.name}")
            form = QFormLayout(group)

            form.addRow("Image:", QLabel(c.image or "-"))

            # 3 - ESTADO DEL CONTAINER:
            if cs:
                form.addRow("Ready:", QLabel("true" if cs.ready else "false"))
                form.addRow("Restart count:", QLabel(str(cs.restart_count)))
                if cs.state:
                    if cs.state.running:
                        form.addRow("State:", QLabel(f"Running (started: {cs.state.running.started_at.strftime('%Y-%m-%d %H:%M:%S') if cs.state.running.started_at else '-'})"))
                    elif cs.state.waiting:
                        form.addRow("State:", QLabel(f"Waiting: {cs.state.waiting.reason or ''} - {cs.state.waiting.message or ''}"))
                    elif cs.state.terminated:
                        form.addRow("State:", QLabel(f"Terminated: {cs.state.terminated.reason or ''} (exit code: {cs.state.terminated.exit_code})"))
                if cs.last_state:
                    if cs.last_state.terminated:
                        form.addRow("Last state:", QLabel(f"Terminated: {cs.last_state.terminated.reason or ''} (exit code: {cs.last_state.terminated.exit_code})"))
                    else:
                        form.addRow("Last state:", QLabel("-"))
            else:
                form.addRow("Status:", QLabel("(sin datos)"))

            # 4 - COMANDO Y ARGS:
            if c.command:
                form.addRow("Command:", QLabel(" ".join(c.command)))
            if c.args:
                form.addRow("Args:", QLabel(" ".join(c.args)))

            # 5 - PUERTOS:
            if c.ports:
                ports_str = ", ".join(f"{p.container_port}/{p.protocol}" + (f" (name: {p.name})" if p.name else "") for p in c.ports)
                form.addRow("Ports:", QLabel(ports_str))
            else:
                form.addRow("Ports:", QLabel("-"))

            # 6 - RESOURCES (CPU / Memoria):
            if c.resources and (c.resources.requests or c.resources.limits):
                req_parts = []
                lim_parts = []
                if c.resources.requests:
                    for k, v in c.resources.requests.items():
                        req_parts.append(f"{k}={v}")
                if c.resources.limits:
                    for k, v in c.resources.limits.items():
                        lim_parts.append(f"{k}={v}")
                form.addRow("Requests:", QLabel(", ".join(req_parts) if req_parts else "-"))
                form.addRow("Limits:", QLabel(", ".join(lim_parts) if lim_parts else "-"))
            else:
                form.addRow("Resources:", QLabel("-"))

            # 7 - VOLUME MOUNTS:
            if c.volume_mounts:
                vm_str = ", ".join(f"{vm.name} -> {vm.mount_path}" + (f" (ro)" if vm.read_only else "") for vm in c.volume_mounts)
                form.addRow("Volume mounts:", QLabel(vm_str))
            else:
                form.addRow("Volume mounts:", QLabel("-"))

            # 8 - PROBES:
            if c.liveness_probe:
                form.addRow("Liveness probe:", QLabel(str(c.liveness_probe._type if hasattr(c.liveness_probe, '_type') else c.liveness_probe)))
            if c.readiness_probe:
                form.addRow("Readiness probe:", QLabel(str(c.readiness_probe._type if hasattr(c.readiness_probe, '_type') else c.readiness_probe)))

            # 9 - IMAGE PULL POLICY:
            form.addRow("Image pull policy:", QLabel(c.image_pull_policy or "-"))

            layout.addWidget(group)

    def _add_volumes(self, layout, pod):
        self._add_section_title(layout, f"\U0001F4BF  Volumes")
        spec = pod.spec

        if not spec or not spec.volumes:
            layout.addWidget(QLabel("(sin volumes)"))
            return

        for v in spec.volumes:
            group = QGroupBox(v.name)
            form = QFormLayout(group)

            # 1 - DETECTO EL TIPO DE VOLUME:
            if v.config_map:
                form.addRow("Tipo:", QLabel("ConfigMap"))
                form.addRow("ConfigMap name:", QLabel(v.config_map.name or "-"))
            elif v.secret:
                form.addRow("Tipo:", QLabel("Secret"))
                form.addRow("Secret name:", QLabel(v.secret.secret_name or "-"))
                form.addRow("Optional:", QLabel(str(v.secret.optional)))
            elif v.empty_dir:
                form.addRow("Tipo:", QLabel("EmptyDir"))
                form.addRow("Medium:", QLabel(v.empty_dir.medium or "default"))
            elif v.persistent_volume_claim:
                form.addRow("Tipo:", QLabel("PersistentVolumeClaim"))
                form.addRow("PVC name:", QLabel(v.persistent_volume_claim.claim_name or "-"))
            elif v.host_path:
                form.addRow("Tipo:", QLabel("HostPath"))
                form.addRow("Path:", QLabel(v.host_path.path or "-"))
            else:
                form.addRow("Tipo:", QLabel("(otros)"))

            layout.addWidget(group)

    def _add_env_vars(self, layout, pod):
        self._add_section_title(layout, f"\U0001F511  Environment Variables")
        spec = pod.spec

        if not spec or not spec.containers:
            layout.addWidget(QLabel("(sin containers)"))
            return

        for c in spec.containers:
            if not c.env:
                continue

            group = QGroupBox(f"{ICON_USER}  {c.name}")
            form = QFormLayout(group)

            for env in c.env:
                # 1 - SI VIENE DE UN SECRET/CONFIGMAP, MUESTRO LA REFERENCIA:
                if env.value_from:
                    if env.value_from.secret_key_ref:
                        ref = env.value_from.secret_key_ref
                        form.addRow(f"{env.name}", QLabel(f"[Secret: {ref.name}/{ref.key}]"))
                    elif env.value_from.config_map_key_ref:
                        ref = env.value_from.config_map_key_ref
                        form.addRow(f"{env.name}", QLabel(f"[ConfigMap: {ref.name}/{ref.key}]"))
                    elif env.value_from.field_ref:
                        ref = env.value_from.field_ref
                        form.addRow(f"{env.name}", QLabel(f"[FieldRef: {ref.field_path}]"))
                    else:
                        form.addRow(f"{env.name}", QLabel("[ref]"))
                else:
                    # 2 - VALOR DIRECTO (puede contener tokens/sensibles):
                    form.addRow(f"{env.name}", QLabel(env.value or "-"))

            layout.addWidget(group)


def main():
    # 1 - CREO LA APLICACION QT:
    app = QApplication(sys.argv)

    # 2 - CREO Y MUESTRO LA VENTANA:
    window = KubeconfigViewerWindow()
    window.show()

    # 3 - EJECUTO EL EVENT LOOP:
    app.exec()

    # 4 - CIERRE TOTAL: corto los streams que queden vivos, espero un
    #     momento a que los workers terminen y FUERZO la salida (os._exit)
    #     para que no quede ningun thread colgado ni crash de
    #     finalizacion del interprete con QRunnables a medio correr:
    try:
        for t in list(_LogsStreamTask._ALIVE):
            t.stop()
        QThreadPool.globalInstance().clear()
        QThreadPool.globalInstance().waitForDone(2000)
    except Exception:
        pass
    try:
        _log.info("=== MiniLens cerro limpio ===")
        for h in _log.handlers:
            h.flush()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
