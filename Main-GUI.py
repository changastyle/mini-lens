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
import traceback
import tempfile

import yaml
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from database import db as dbmod
from PySide6.QtWidgets import (
    QApplication,
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
    QRadioButton,
)
from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtGui import QFont, QIcon, QDragEnterEvent, QDropEvent, QColor, QPalette, QGuiApplication, QPainter, QBrush, QPen
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
    background-color: #2a2a2a;
    border: 1px solid #444;
    border-radius: 4px;
    font-size: 14px;
    padding: 4px;
}
QListWidget::item {
    padding: 6px;
    border-radius: 3px;
}
QListWidget::item:selected {
    background-color: #f5c518;
    color: #1a1a1a;
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

        # 2 - TIPO + CLUSTER IP (grande, como IP de un servidor):
        svc_type = (svc.spec.type if svc.spec else None) or "ClusterIP"
        cluster_ip = (svc.spec.cluster_ip if svc.spec else None) or "-"

        ip_box = QFrame()
        ip_box.setStyleSheet(
            "QFrame { background-color: #1a1a1a; border: 1px solid #555; "
            "border-radius: 6px; padding: 4px; }"
        )
        ip_layout = QVBoxLayout(ip_box)
        ip_layout.setContentsMargins(8, 6, 8, 6)
        type_lbl = QLabel(f"Tipo: {svc_type}")
        type_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        ip_layout.addWidget(type_lbl)
        ip_lbl = QLabel(f"IP:  {cluster_ip}")
        ip_lbl.setStyleSheet("color: #f5c518; font-size: 15px; font-weight: bold;")
        ip_layout.addWidget(ip_lbl)
        layout.addWidget(ip_box)

        # 3 - PUERTOS DEL SERVICE (badges amarillos = puertos abiertos):
        ports_row = QHBoxLayout()
        ports_lbl = QLabel(f"{ICON_PORT} Puertos abiertos:")
        ports_lbl.setStyleSheet("color: #aaa; font-size: 12px;")
        ports_row.addWidget(ports_lbl)

        if svc.spec and svc.spec.ports:
            for p in svc.spec.ports:
                port_text = f"{p.port}/{p.protocol or 'TCP'}"
                if p.target_port and str(p.target_port) != str(p.port):
                    port_text += f" \u2192 {p.target_port}"
                port_badge = QLabel(f" {port_text} ")
                port_badge.setStyleSheet(
                    "background-color: #f5c518; color: #1a1a1a; "
                    "border-radius: 4px; font-size: 12px; font-weight: bold; padding: 3px 6px;"
                )
                ports_row.addWidget(port_badge)
        else:
            ports_row.addWidget(QLabel("-"))
        ports_row.addStretch()
        layout.addLayout(ports_row)

        # 4 - SEPARADOR:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #555;")
        layout.addWidget(sep)

        # 5 - PODS DETRAS DEL SERVICE (desglose como procesos del servidor):
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

        # 6 - BOTONES DE ACCION:
        actions = QHBoxLayout()
        if cluster_ip and cluster_ip != "-":
            btn = QPushButton("Copiar IP")
            btn.setMaximumWidth(100)
            btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(cluster_ip))
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)

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

        # 3 - PUERTOS DEL CONTAINER + IP DEL POD:
        ports = _get_pod_ports(pod)
        pod_ip = (pod.status.pod_ip if pod.status else None) or "-"
        detail_parts = []
        if ports:
            detail_parts.append("ports: " + ", ".join(ports))
        detail_parts.append(f"ip: {pod_ip}")
        detail_lbl = QLabel(" | ".join(detail_parts))
        detail_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        detail_lbl.setWordWrap(True)
        row_layout.addWidget(detail_lbl)

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
    """Barra vertical izquierda con clusters anclados (estilo OpenLens)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hotbar")
        self.setFixedWidth(64)
        self._items = {}
        self._selected_id = None
        self._on_item_click = None
        self._on_item_unpin = None
        self._on_item_edit = None

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

    def set_callbacks(self, on_click, on_unpin, on_edit=None):
        self._on_item_click = on_click
        self._on_item_unpin = on_unpin
        self._on_item_edit = on_edit

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


class KubeconfigViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 1 - CONFIGURO LA VENTANA:
        self.setWindowTitle(f"{ICON_CLUSTER} MiniLens - Kubernetes Explorer")
        self.resize(1500, 950)

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
        self.btn_load = QPushButton(f"{ICON_FILE}  Cargar kubeconfig")
        self.btn_load.clicked.connect(self.on_load)
        top_bar.addWidget(self.btn_load)

        self.btn_copy_user = QPushButton(f"{ICON_USER}  Copiar a ~/.kube/config")
        self.btn_copy_user.clicked.connect(self.on_copy_to_user_config)
        self.btn_copy_user.setEnabled(False)
        top_bar.addWidget(self.btn_copy_user)

        top_bar.addStretch()
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
        for lbl in [self.lbl_file_path, self.lbl_api_version, self.lbl_kind, self.lbl_current_context]:
            lbl.setStyleSheet("font-size: 12px; color: #f5c518;")
        meta_form.addRow("Archivo:", self.lbl_file_path)
        meta_form.addRow("apiVersion:", self.lbl_api_version)
        meta_form.addRow("kind:", self.lbl_kind)
        meta_form.addRow("current-context:", self.lbl_current_context)
        top_row.addWidget(meta_group, stretch=1)

        # 9c - IMPORT PANEL (clusters del kubeconfig cargado, con boton pin):
        import_group = QGroupBox(f"{ICON_PIN}  Clusters para anclar")
        import_group.setMaximumHeight(120)
        import_layout = QVBoxLayout(import_group)
        import_layout.setContentsMargins(6, 4, 6, 4)
        import_layout.setSpacing(2)
        self.import_scroll = QScrollArea()
        self.import_scroll.setWidgetResizable(True)
        self.import_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.import_container = QWidget()
        self.import_layout_inner = QVBoxLayout(self.import_container)
        self.import_layout_inner.setContentsMargins(0, 0, 0, 0)
        self.import_layout_inner.setSpacing(2)
        self.import_scroll.setWidget(self.import_container)
        import_layout.addWidget(self.import_scroll)
        top_row.addWidget(import_group, stretch=1)

        layout.addLayout(top_row)

        # 10 - AREA PRINCIPAL: Clusters+Contexts (~30%) | Detalle/Mapa (~70%):
        splitter = QSplitter(Qt.Horizontal)

        # 10a - IZQUIERDA: Clusters + Contexts apilados:
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        col1_group = QGroupBox(f"{ICON_CLUSTER}  Clusters")
        col1_layout = QVBoxLayout(col1_group)
        col1_layout.setContentsMargins(6, 6, 6, 6)
        self.list_clusters = QListWidget()
        self.list_clusters.currentItemChanged.connect(self.on_cluster_selected)
        col1_layout.addWidget(self.list_clusters)
        left_layout.addWidget(col1_group, stretch=1)

        col2_group = QGroupBox(f"{ICON_CONTEXT}  Contexts")
        col2_layout = QVBoxLayout(col2_group)
        col2_layout.setContentsMargins(6, 6, 6, 6)
        self.list_contexts = QListWidget()
        self.list_contexts.currentItemChanged.connect(self.on_context_selected)
        col2_layout.addWidget(self.list_contexts)
        left_layout.addWidget(col2_group, stretch=2)

        splitter.addWidget(left_panel)

        # 10b - DERECHA: Detalle del context:
        col3_group = QGroupBox(f"{ICON_DETAIL}  Detalle del context")
        col3_layout = QVBoxLayout(col3_group)
        col3_layout.setContentsMargins(6, 6, 6, 6)
        col3_layout.setSpacing(4)

        # Context info compacto en una linea:
        ctx_bar = QHBoxLayout()
        self.lbl_ctx_name = QLabel("-")
        self.lbl_ctx_namespace = QLabel("-")
        self.lbl_ctx_user = QLabel("-")
        self.lbl_ctx_cluster = QLabel("-")
        for lbl in [self.lbl_ctx_name, self.lbl_ctx_namespace, self.lbl_ctx_user, self.lbl_ctx_cluster]:
            lbl.setObjectName("detail_value")
            lbl.setStyleSheet("font-size: 12px; color: #f5c518; font-weight: bold;")

        def _mini(label_text, value_lbl):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 8, 0)
            h.setSpacing(4)
            t = QLabel(label_text)
            t.setStyleSheet("color: #aaa; font-size: 11px;")
            h.addWidget(t)
            h.addWidget(value_lbl)
            return w

        ctx_bar.addWidget(_mini("NS:", self.lbl_ctx_namespace))
        ctx_bar.addWidget(_mini("Ctx:", self.lbl_ctx_name))
        ctx_bar.addWidget(_mini("User:", self.lbl_ctx_user), stretch=1)

        self.btn_test_connection = QPushButton(f"{ICON_OK}")
        self.btn_test_connection.setMaximumWidth(36)
        self.btn_test_connection.setMaximumHeight(28)
        self.btn_test_connection.setToolTip("Refrescar Pods y Services")
        self.btn_test_connection.clicked.connect(self.on_test_connection)
        self.btn_test_connection.setEnabled(False)
        ctx_bar.addWidget(self.btn_test_connection)
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

        self.table_pods = QTableWidget(0, 5)
        self.table_pods.setHorizontalHeaderLabels(["NAME", "STATUS", "READY", "IP", ""])
        self.table_pods.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_pods.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_pods.doubleClicked.connect(self.on_pod_double_click)
        list_layout.addWidget(self.table_pods, stretch=1)

        self.lbl_services_title = QLabel(f"{ICON_CLUSTER}  Services")
        self.lbl_services_title.setObjectName("detail_value")
        list_layout.addWidget(self.lbl_services_title)

        self.table_services = QTableWidget(0, 5)
        self.table_services.setHorizontalHeaderLabels(["NAME", "TYPE", "CLUSTER IP", "PORTS", ""])
        self.table_services.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_services.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
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
        self.resource_tabs.setCurrentIndex(1)

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
        col3_layout.addLayout(conn_status_layout)

        splitter.addWidget(col3_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([360, 1000])
        layout.addWidget(splitter, stretch=1)

        # 11 - USERS (compacto):
        users_group = QGroupBox(f"{ICON_USER}  Users")
        users_group.setMaximumHeight(140)
        users_layout = QVBoxLayout(users_group)
        users_layout.setContentsMargins(6, 4, 6, 4)
        self.table_users = QTableWidget(0, 4)
        self.table_users.setHorizontalHeaderLabels(["Name", "Token", "Client Cert", "Auth Type"])
        self.table_users.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_users.verticalHeader().setDefaultSectionSize(22)
        users_layout.addWidget(self.table_users)
        layout.addWidget(users_group)

        # 12 - ETIQUETA DE ESTADO:
        self.lbl_status = QLabel(f"{ICON_WARN}  Arrastra un kubeconfig para empezar")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setMaximumHeight(24)
        layout.addWidget(self.lbl_status)

        # 13 - CARGO HOTBAR DESDE LA DB:
        self._refresh_hotbar()

    def on_load(self):
        # 1 - ABRO EL DIALOGO PARA SELECCIONAR UN ARCHIVO:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar kubeconfig",
            "",
            "Archivos YAML (*.yaml *.yml);;Todos los archivos (*)",
        )
        if not file_path:
            return
        self.load_kubeconfig(file_path)

    def on_copy_to_user_config(self):
        # 1 - VERIFICO QUE HAYA UN KUBECONFIG CARGADO:
        if not self.config or not self._current_kubeconfig_id:
            return

        # 2 - OBTENGO EL YAML CONTENT DESDE LA DB:
        kc = dbmod.get_kubeconfig(self._current_kubeconfig_id)
        if not kc:
            return
        yaml_content = kc.get("yaml_content", "")
        if not yaml_content:
            return

        # 3 - PREGUNTO AL USUARIO SI QUIERE COPIAR:
        reply = QMessageBox.question(
            self,
            f"{ICON_INFO} Copiar kubeconfig",
            f"Quieres copiar el kubeconfig cargado a:\n\n"
            f"  {USER_KUBECONFIG}\n\n"
            f"Si el archivo ya existe, se reemplazara.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 4 - CREO EL DIRECTORIO ~/.kube SI NO EXISTE Y ESCRIBO:
        kube_dir = os.path.dirname(USER_KUBECONFIG)
        try:
            os.makedirs(kube_dir, exist_ok=True)
            with open(USER_KUBECONFIG, "w", encoding="utf-8") as f:
                f.write(yaml_content)
            QMessageBox.information(
                self,
                f"{ICON_OK} Copiado",
                f"Kubeconfig copiado a:\n{USER_KUBECONFIG}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                f"{ICON_WARN} Error",
                f"No se pudo copiar:\n{e}",
            )

    def load_kubeconfig(self, file_path):
        # 1 - LEO EL ARCHIVO YAML:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
        except Exception as e:
            QMessageBox.critical(self, f"{ICON_WARN} Error", f"No se pudo leer el archivo:\n{e}")
            return

        # 2 - GUARDO EN LA BASE DE DATOS:
        try:
            self._current_kubeconfig_id = dbmod.import_kubeconfig(file_path)
        except Exception as e:
            QMessageBox.critical(self, f"{ICON_WARN} Error DB", f"No se pudo guardar en la base de datos:\n{e}")
            return

        # 3 - GUARDO LA RUTA DEL ARCHIVO CARGADO:
        self._loaded_file_path = file_path

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

        # 6 - POBLA COLUMNA 1: CLUSTERS:
        for c in self.config.get("clusters", []):
            name = c.get("name", "(sin nombre)")
            item = QListWidgetItem(f"{ICON_CLUSTER}  {name}")
            item.setData(Qt.UserRole, c)
            self.list_clusters.addItem(item)

        # 7 - POBLA AREA INFERIOR: USERS:
        users = self.config.get("users", [])
        self.table_users.setRowCount(len(users))
        for i, u in enumerate(users):
            name = u.get("name", "-")
            user_data = u.get("user", {})
            token = user_data.get("token", "")
            masked = token[:8] + "..." if token else "-"
            has_cert = "[oculto]" if user_data.get("client-certificate-data") else "-"
            if token:
                auth_type = "Token"
            elif user_data.get("client-certificate-data"):
                auth_type = "Client Certificate"
            elif user_data.get("username"):
                auth_type = "User/Password"
            else:
                auth_type = "-"
            self.table_users.setItem(i, 0, QTableWidgetItem(f"{ICON_USER}  {name}"))
            self.table_users.setItem(i, 1, QTableWidgetItem(masked))
            self.table_users.setItem(i, 2, QTableWidgetItem(has_cert))
            self.table_users.setItem(i, 3, QTableWidgetItem(auth_type))

        # 8 - HABILITO EL BOTON DE COPIAR:
        self.btn_copy_user.setEnabled(True)

        # 9 - POBLA EL IMPORT PANEL CON LOS CLUSTERS DEL KUBECONFIG:
        self._populate_import_panel()

        # 10 - REFRESCO LA HOTBAR:
        self._refresh_hotbar()

        # 11 - ESTADO FINAL:
        n_clusters = len(self.config.get("clusters", []))
        n_users = len(users)
        n_contexts = len(self.config.get("contexts", []))
        self.lbl_status.setText(
            f"{ICON_OK}  Kubeconfig cargado: "
            f"{n_clusters} cluster(s), {n_users} user(s), {n_contexts} context(s)"
        )

    def _populate_import_panel(self):
        # 1 - LIMPIO EL PANEL DE IMPORT:
        while self.import_layout_inner.count():
            item = self.import_layout_inner.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # 2 - SI NO HAY KUBECONFIG_ID, SALGO:
        if not self._current_kubeconfig_id:
            return

        # 3 - OBTENGO LOS CLUSTERS DE LA DB:
        clusters = dbmod.get_clusters(self._current_kubeconfig_id)
        for c in clusters:
            row = QFrame()
            row.setObjectName("import_cluster_row")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(4)

            name_lbl = QLabel(f"{ICON_CLUSTER}  {c['name']}")
            name_lbl.setStyleSheet("font-size: 12px; color: #e0e0e0;")
            row_layout.addWidget(name_lbl, stretch=1)

            if c["pinned"]:
                # 3a - YA ESTA ANCLADO: muestro boton quitar:
                btn = QPushButton(f"{ICON_TRASH}")
                btn.setMaximumWidth(30)
                btn.setMaximumHeight(24)
                btn.setToolTip("Quitar de la hotbar")
                btn.clicked.connect(lambda checked, cid=c["id"]: self._unpin_cluster(cid))
                row_layout.addWidget(btn)
            else:
                # 3b - NO ESTA ANCLADO: muestro boton pin:
                btn = QPushButton(f"{ICON_PIN}")
                btn.setMaximumWidth(30)
                btn.setMaximumHeight(24)
                btn.setToolTip("Anclar a la hotbar")
                btn.clicked.connect(lambda checked, cid=c["id"]: self._pin_cluster(cid))
                row_layout.addWidget(btn)

            self.import_layout_inner.addWidget(row)

        self.import_layout_inner.addStretch()

    def _pin_cluster(self, cluster_id):
        # 1 - ANCLO EL CLUSTER EN LA DB:
        dbmod.pin_cluster(cluster_id)
        # 2 - REFRESCO LA HOTBAR Y EL IMPORT PANEL:
        self._refresh_hotbar()
        self._populate_import_panel()

    def _unpin_cluster(self, cluster_id):
        # 1 - DESANCO EL CLUSTER EN LA DB:
        dbmod.unpin_cluster(cluster_id)
        # 2 - REFRESCO LA HOTBAR Y EL IMPORT PANEL:
        self._refresh_hotbar()
        self._populate_import_panel()

    def _refresh_hotbar(self):
        # 1 - OBTENGO LOS CLUSTERS ANCLADOS DESDE LA DB:
        pinned = dbmod.get_pinned_clusters()
        self.hotbar.refresh(pinned)

    def on_hotbar_item_clicked(self, cluster_id):
        # 1 - MARCO EL ITEM COMO SELECCIONADO:
        self.hotbar.select(cluster_id)

        # 2 - OBTENGO EL CLUSTER DESDE LA DB:
        c = dbmod.get_cluster(cluster_id)
        if not c:
            return

        # 3 - CARGO EL KUBECONFIG DESDE LA DB (yaml_content):
        yaml_content = c.get("yaml_content", "")
        if not yaml_content:
            return

        # 4 - PARSEO EL YAML:
        self.config = yaml.safe_load(yaml_content)
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

        for cl in self.config.get("clusters", []):
            name = cl.get("name", "(sin nombre)")
            item = QListWidgetItem(f"{ICON_CLUSTER}  {name}")
            item.setData(Qt.UserRole, cl)
            self.list_clusters.addItem(item)

        users = self.config.get("users", [])
        self.table_users.setRowCount(len(users))
        for i, u in enumerate(users):
            name = u.get("name", "-")
            user_data = u.get("user", {})
            token = user_data.get("token", "")
            masked = token[:8] + "..." if token else "-"
            has_cert = "[oculto]" if user_data.get("client-certificate-data") else "-"
            if token:
                auth_type = "Token"
            elif user_data.get("client-certificate-data"):
                auth_type = "Client Certificate"
            elif user_data.get("username"):
                auth_type = "User/Password"
            else:
                auth_type = "-"
            self.table_users.setItem(i, 0, QTableWidgetItem(f"{ICON_USER}  {name}"))
            self.table_users.setItem(i, 1, QTableWidgetItem(masked))
            self.table_users.setItem(i, 2, QTableWidgetItem(has_cert))
            self.table_users.setItem(i, 3, QTableWidgetItem(auth_type))

        self.btn_copy_user.setEnabled(True)

        # 8 - POBLA EL IMPORT PANEL:
        self._populate_import_panel()

        # 9 - SELECCIONO EL CLUSTER EN LA LISTA Y BUSCO SU CONTEXT:
        cluster_name = c.get("name", "")
        for i in range(self.list_clusters.count()):
            item = self.list_clusters.item(i)
            if item.text().replace(f"{ICON_CLUSTER}  ", "") == cluster_name:
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

        # 5 - REFRESCO LA HOTBAR Y EL IMPORT PANEL:
        self._refresh_hotbar()
        self._populate_import_panel()

    def on_cluster_selected(self, current, previous):
        # 1 - SI NO HAY ITEM SELECCIONADO, LIMPIO:
        if not current:
            return

        # 2 - OBTENGO EL NOMBRE DEL CLUSTER SELECCIONADO (sin el icono):
        raw_text = current.text()
        cluster_name = raw_text.replace(f"{ICON_CLUSTER}  ", "")

        # 3 - LIMPIO LA COLUMNA 2 (CONTEXTS) Y LA COLUMNA 3 (DETALLE):
        self.list_contexts.clear()
        self.table_pods.setRowCount(0)
        self.lbl_ctx_name.setText("-")
        self.lbl_ctx_namespace.setText("-")
        self.lbl_ctx_user.setText("-")
        self.lbl_ctx_cluster.setText("-")

        # 4 - FILTRO LOS CONTEXTS QUE PERTENECEN A ESTE CLUSTER:
        for ctx in self.config.get("contexts", []):
            ctx_data = ctx.get("context", {})
            if ctx_data.get("cluster") == cluster_name:
                name = ctx.get("name", "(sin nombre)")
                item = QListWidgetItem(f"{ICON_CONTEXT}  {name}")
                item.setData(Qt.UserRole, ctx)
                # 5 - MARCO EL CURRENT-CONTEXT EN NEGRITA:
                if name == self.current_context_name:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setText(f"{ICON_CONTEXT}  {name}  (actual)")
                self.list_contexts.addItem(item)

    def on_context_selected(self, current, previous):
        # 1 - SI NO HAY ITEM SELECCIONADO, LIMPIO:
        if not current:
            return

        # 2 - OBTENGO EL CONTEXT SELECCIONADO:
        ctx = current.data(Qt.UserRole)
        ctx_data = ctx.get("context", {})
        name = ctx.get("name", "-")

        # 3 - MUESTRO EL DETALLE EN LA COLUMNA 3:
        self.lbl_ctx_name.setText(name)
        self.lbl_ctx_namespace.setText(str(ctx_data.get("namespace", "-")))
        self.lbl_ctx_user.setText(str(ctx_data.get("user", "-")))
        self.lbl_ctx_cluster.setText(str(ctx_data.get("cluster", "-")))

        # 4 - LIMPIO LAS TABLAS DE PODS Y SERVICES + MAPA:
        self.table_pods.setRowCount(0)
        self.table_services.setRowCount(0)
        self._clear_map()
        self.lbl_connection_status.setText("-")
        self.lbl_pods_title.setText(f"{ICON_POD}  Recursos del namespace:")
        self.lbl_pods_list_title.setText(f"{ICON_POD}  Pods:")
        self.lbl_services_title.setText(f"{ICON_CLUSTER}  Services:")

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

    def on_test_connection(self):
        # 1 - VERIFICO QUE HAYA UN CONTEXT SELECCIONADO:
        if not hasattr(self, "selected_context_name") or not self.selected_context_name:
            return

        # 2 - VERIFICO QUE HAYA UN NAMESPACE:
        if not self.selected_namespace:
            self.lbl_connection_status.setText(f"{ICON_WARN}  El context no tiene namespace definido")
            return

        # 3 - DESHABILITO EL BOTON Y MUESTRO ESTADO:
        self.btn_test_connection.setEnabled(False)
        self.lbl_connection_status.setText(f"{ICON_INFO}  Conectando al cluster...")
        self.table_pods.setRowCount(0)
        QApplication.processEvents()

        try:
            # 4 - CARGO EL KUBECONFIG CON EL CONTEXT SELECCIONADO:
            #    Esto le dice al Kubernetes Python Client:
            #    - Usa este archivo YAML como configuracion
            #    - Usa este context (cluster + user + namespace)
            config.load_kube_config(
                config_file=self._loaded_file_path,
                context=self.selected_context_name,
            )

            # 5 - CREO EL CLIENTE DE LA API CoreV1:
            #    CoreV1Api es la API que maneja pods, services, namespaces, etc.
            v1 = client.CoreV1Api()

            # 6 - LLAMO A LA API PARA LISTAR PODS DEL NAMESPACE:
            #    list_namespaced_pod(namespace=...) hace una peticion GET a:
            #    /api/v1/namespaces/{namespace}/pods
            pod_list = v1.list_namespaced_pod(namespace=self.selected_namespace)

            # 7 - TRANSFORMO LA RESPUESTA (PodList) A FILAS DE LA TABLA:
            pods = pod_list.items
            self._pods_cache = {pod.metadata.name: pod for pod in pods}
            self.table_pods.setRowCount(len(pods))

            for i, pod in enumerate(pods):
                # 7a - NOMBRE DEL POD:
                name = pod.metadata.name

                # 7b - ESTADO DEL POD (phase):
                status = pod.status.phase if pod.status and pod.status.phase else "Unknown"

                # 7c - CONTAINERS READY (ej: "1/1"):
                if pod.status and pod.status.container_statuses:
                    ready = sum(1 for cs in pod.status.container_statuses if cs.ready)
                    total = len(pod.status.container_statuses)
                    ready_str = f"{ready}/{total}"
                else:
                    ready_str = "-"

                # 7d - IP DEL POD:
                pod_ip = pod.status.pod_ip if pod.status and pod.status.pod_ip else "-"

                self.table_pods.setItem(i, 0, QTableWidgetItem(f"{ICON_POD}  {name}"))
                self.table_pods.setItem(i, 1, QTableWidgetItem(status))
                self.table_pods.setItem(i, 2, QTableWidgetItem(ready_str))
                self.table_pods.setItem(i, 3, QTableWidgetItem(pod_ip))

                # 7e - BOTON COPIAR IP EN LA COLUMNA 4:
                if pod_ip != "-":
                    btn_copy_ip = QPushButton("Copiar IP")
                    btn_copy_ip.setMaximumWidth(80)
                    btn_copy_ip.clicked.connect(lambda checked, ip=pod_ip: self._copy_to_clipboard(ip))
                    self.table_pods.setCellWidget(i, 4, btn_copy_ip)

            # 8 - LISTO LOS SERVICES DEL NAMESPACE:
            #    list_namespaced_service(namespace=...) hace GET a:
            #    /api/v1/namespaces/{namespace}/services
            svc_list = v1.list_namespaced_service(namespace=self.selected_namespace)
            services = svc_list.items
            self.table_services.setRowCount(len(services))

            for i, svc in enumerate(services):
                # 8a - NOMBRE DEL SERVICE:
                svc_name = svc.metadata.name

                # 8b - TIPO (ClusterIP, NodePort, LoadBalancer):
                svc_type = svc.spec.type or "ClusterIP"

                # 8c - CLUSTER IP:
                cluster_ip = svc.spec.cluster_ip or "-"

                # 8d - PUERTOS (ej: "8080/TCP, 443/TCP"):
                if svc.spec.ports:
                    ports_str = ", ".join(
                        f"{p.port}/{p.protocol}" + (f" -> {p.target_port}" if p.target_port and str(p.target_port) != str(p.port) else "")
                        for p in svc.spec.ports
                    )
                else:
                    ports_str = "-"

                self.table_services.setItem(i, 0, QTableWidgetItem(f"\U0001F310  {svc_name}"))
                self.table_services.setItem(i, 1, QTableWidgetItem(svc_type))
                self.table_services.setItem(i, 2, QTableWidgetItem(cluster_ip))
                self.table_services.setItem(i, 3, QTableWidgetItem(ports_str))

                # 8e - BOTON COPIAR CLUSTER IP:
                if cluster_ip != "-":
                    btn_copy_svc_ip = QPushButton("Copiar IP")
                    btn_copy_svc_ip.setMaximumWidth(80)
                    btn_copy_svc_ip.clicked.connect(lambda checked, ip=cluster_ip: self._copy_to_clipboard(ip))
                    self.table_services.setCellWidget(i, 4, btn_copy_svc_ip)

            # 9 - GUARDO CACHE Y RENDERIZO EL MAPA GRAFICO:
            self._services_cache = services
            self._render_service_map(services, pods)

            # 10 - MUESTRO EL RESULTADO EN LOS TITULOS:
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

        except ApiException as e:
            # 9a - ERROR DE LA API DE KUBERNETES (ej: 401, 403, 404):
            self.lbl_connection_status.setText(
                f"{ICON_WARN}  Error de la API (codigo {e.status}): {e.reason}"
            )
            self.btn_copy_error.setVisible(True)

        except Exception as e:
            # 9b - OTRO ERROR (ej: no se puede conectar al servidor):
            self.lbl_connection_status.setText(
                f"{ICON_WARN}  Error de conexion: {e}"
            )
            self.btn_copy_error.setVisible(True)

        else:
            # 10a - SI TODO SALIO BIEN, OCULTO EL BOTON DE COPIAR:
            self.btn_copy_error.setVisible(False)

        finally:
            # 10b - REHABILITO EL BOTON:
            self.btn_test_connection.setEnabled(True)


    def on_pod_double_click(self, index):
        # 1 - OBTENGO EL NOMBRE DEL POD DE LA FILA SELECCIONADA:
        row = index.row()
        name_item = self.table_pods.item(row, 0)
        if not name_item:
            return

        # 2 - EXTRAIGO EL NOMBRE (sin el icono):
        pod_name = name_item.text().replace(f"{ICON_POD}  ", "")

        # 3 - BUSCO EL POD EN EL CACHE:
        pod = self._pods_cache.get(pod_name)
        if not pod:
            return

        # 4 - ABRO LA VENTANA DE DETALLE DEL POD:
        self._open_pod_detail(pod)

    def _open_pod_detail(self, pod):
        # 1 - ABRO LA VENTANA DE DETALLE DEL POD:
        detail_window = PodDetailWindow(pod, self)
        detail_window.exec()

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


class PodDetailWindow(QDialog):
    """Ventana modal con todos los detalles de un Pod."""

    def __init__(self, pod, parent=None):
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
        val = QLabel(str(value))
        val.setWordWrap(True)
        val.setStyleSheet("color: #f5c518;")
        row_layout.addWidget(lbl)
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
