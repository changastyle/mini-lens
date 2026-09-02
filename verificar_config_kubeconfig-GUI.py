"""
Test GUI: verifica la lectura del kubeconfig con layout de 3 columnas.

Columna 1: Clusters
Columna 2: Contexts (al clickear un cluster)
Columna 3: Detalle del context (namespace, user, pods)
Abajo:     Users

Incluye:
- Drag & drop de archivos kubeconfig
- Opcion de copiar a ~/.kube/config
- Tema negro/amarillo
- Iconos y textos explicativos
- Fuentes grandes

Uso:
    python verificar_config_kubeconfig-GUI.py
"""

import os
import sys
import shutil
import traceback

import yaml
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
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
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QDragEnterEvent, QDropEvent, QColor, QPalette, QGuiApplication


# 1 - RUTA AL KUBECONFIG DE PRUEBA POR DEFECTO:
DEFAULT_KUBECONFIG = os.path.join(
    os.path.dirname(__file__), ".vscode", "test", "kubeconfig-openshift-indramind.yaml"
)

# 2 - RUTA AL KUBECONFIG DEL USUARIO (~/.kube/config):
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
    margin-top: 14px;
    padding-top: 10px;
    font-size: 15px;
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
        self.setWindowTitle(f"{ICON_CLUSTER} MiniLens - Verificar kubeconfig (GUI)")
        self.resize(1100, 800)

        # 2 - APLICO EL TEMA:
        app = QApplication.instance()
        app.setStyleSheet(STYLESHEET)

        # 3 - GUARDO EL CONFIG PARSEADO:
        self.config = None
        self.current_context_name = None

        # 4 - WIDGET CENTRAL Y LAYOUT:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        # 5 - BARRA SUPERIOR CON BOTONES:
        top_bar = QHBoxLayout()
        self.btn_load = QPushButton(f"{ICON_FILE}  Cargar kubeconfig")
        self.btn_load.clicked.connect(self.on_load)
        top_bar.addWidget(self.btn_load)

        self.btn_load_default = QPushButton(f"{ICON_INFO}  Cargar de prueba")
        self.btn_load_default.clicked.connect(self.on_load_default)
        top_bar.addWidget(self.btn_load_default)

        self.btn_copy_user = QPushButton(f"{ICON_USER}  Copiar a ~/.kube/config")
        self.btn_copy_user.clicked.connect(self.on_copy_to_user_config)
        self.btn_copy_user.setEnabled(False)
        top_bar.addWidget(self.btn_copy_user)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        # 6 - ZONA DE DRAG & DROP:
        self.dropzone = DropZone()
        self.dropzone.set_parent_window(self)
        layout.addWidget(self.dropzone)

        # 7 - METADATOS:
        meta_group = QGroupBox(f"{ICON_INFO}  Metadatos del kubeconfig")
        meta_form = QFormLayout(meta_group)
        self.lbl_file_path = QLabel("-")
        self.lbl_file_path.setWordWrap(True)
        self.lbl_api_version = QLabel("-")
        self.lbl_kind = QLabel("-")
        self.lbl_current_context = QLabel("-")
        meta_form.addRow("Archivo:", self.lbl_file_path)
        meta_form.addRow("apiVersion:", self.lbl_api_version)
        meta_form.addRow("kind:", self.lbl_kind)
        meta_form.addRow("current-context:", self.lbl_current_context)
        layout.addWidget(meta_group)

        # 8 - AREA DE 3 COLUMNAS (splitter horizontal):
        splitter = QSplitter(Qt.Horizontal)

        # 8a - COLUMNA 1: CLUSTERS:
        col1_group = QGroupBox(f"{ICON_CLUSTER}  Clusters")
        col1_layout = QVBoxLayout(col1_group)
        col1_help = QLabel(
            "Un CLUSTER es el servidor de Kubernetes al que te conectas. "
            "Define la URL del API y los certificados de seguridad."
        )
        col1_help.setObjectName("help")
        col1_help.setWordWrap(True)
        col1_layout.addWidget(col1_help)
        self.list_clusters = QListWidget()
        self.list_clusters.currentItemChanged.connect(self.on_cluster_selected)
        col1_layout.addWidget(self.list_clusters)
        splitter.addWidget(col1_group)

        # 8b - COLUMNA 2: CONTEXTS:
        col2_group = QGroupBox(f"{ICON_CONTEXT}  Contexts")
        col2_layout = QVBoxLayout(col2_group)
        col2_help = QLabel(
            "Un CONTEXT es una combinacion de CLUSTER + USER + NAMESPACE. "
            "Es como decir \"conectate a este cluster con este usuario en este namespace\". "
            "El current-context es el que esta activo ahora."
        )
        col2_help.setObjectName("help")
        col2_help.setWordWrap(True)
        col2_layout.addWidget(col2_help)
        self.list_contexts = QListWidget()
        self.list_contexts.currentItemChanged.connect(self.on_context_selected)
        col2_layout.addWidget(self.list_contexts)
        splitter.addWidget(col2_group)

        # 8c - COLUMNA 3: DETALLE DEL CONTEXT:
        col3_group = QGroupBox(f"{ICON_DETAIL}  Detalle del context")
        col3_layout = QVBoxLayout(col3_group)

        detail_help = QLabel(
            "Aqui ves los datos del context seleccionado: a que namespace apunta, "
            "con que user y a que cluster."
        )
        detail_help.setObjectName("help")
        detail_help.setWordWrap(True)
        col3_layout.addWidget(detail_help)

        self.detail_form = QFormLayout()
        self.lbl_ctx_name = QLabel("-")
        self.lbl_ctx_namespace = QLabel("-")
        self.lbl_ctx_user = QLabel("-")
        self.lbl_ctx_cluster = QLabel("-")
        for lbl in [self.lbl_ctx_name, self.lbl_ctx_namespace, self.lbl_ctx_user, self.lbl_ctx_cluster]:
            lbl.setObjectName("detail_value")
        self.detail_form.addRow("Context:", self.lbl_ctx_name)
        self.detail_form.addRow("Namespace:", self.lbl_ctx_namespace)
        self.detail_form.addRow("User:", self.lbl_ctx_user)
        self.detail_form.addRow("Cluster:", self.lbl_ctx_cluster)
        col3_layout.addLayout(self.detail_form)

        # 3a - HEADER CON TITULO DE PODS + BOTON REFRESCAR (chico, derecha):
        pods_header = QHBoxLayout()
        self.lbl_pods_title = QLabel(f"{ICON_POD}  Pods del namespace:")
        self.lbl_pods_title.setObjectName("detail_value")
        pods_header.addWidget(self.lbl_pods_title, stretch=1)

        self.btn_test_connection = QPushButton(f"{ICON_OK}")
        self.btn_test_connection.setMaximumWidth(40)
        self.btn_test_connection.setToolTip("Test conexion - Listar Pods")
        self.btn_test_connection.clicked.connect(self.on_test_connection)
        self.btn_test_connection.setEnabled(False)
        pods_header.addWidget(self.btn_test_connection)
        col3_layout.addLayout(pods_header)

        self.table_pods = QTableWidget(0, 5)
        self.table_pods.setHorizontalHeaderLabels(["NAME", "STATUS", "READY", "IP", ""])
        self.table_pods.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_pods.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_pods.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_pods.doubleClicked.connect(self.on_pod_double_click)
        col3_layout.addWidget(self.table_pods)

        # 3b - SECCION DE SERVICES:
        svc_header = QHBoxLayout()
        self.lbl_services_title = QLabel("\U0001F310  Services del namespace:")
        self.lbl_services_title.setObjectName("detail_value")
        svc_header.addWidget(self.lbl_services_title, stretch=1)
        col3_layout.addLayout(svc_header)

        svc_help = QLabel(
            "Un SERVICE es una direccion estable que apunta a uno o mas pods. "
            "Tiene una Cluster IP (interna del cluster) y puertos expuestos."
        )
        svc_help.setObjectName("help")
        svc_help.setWordWrap(True)
        col3_layout.addWidget(svc_help)

        self.table_services = QTableWidget(0, 5)
        self.table_services.setHorizontalHeaderLabels(["NAME", "TYPE", "CLUSTER IP", "PORTS", ""])
        self.table_services.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_services.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        col3_layout.addWidget(self.table_services)

        # 3c - ESTADO DE CONEXION DEBAJO DE LA TABLA + BOTON COPIAR:
        conn_status_layout = QHBoxLayout()
        self.lbl_connection_status = QLabel("-")
        self.lbl_connection_status.setWordWrap(True)
        conn_status_layout.addWidget(self.lbl_connection_status, stretch=1)

        self.btn_copy_error = QPushButton("Copiar")
        self.btn_copy_error.setMaximumWidth(80)
        self.btn_copy_error.clicked.connect(self.on_copy_error)
        self.btn_copy_error.setVisible(False)
        conn_status_layout.addWidget(self.btn_copy_error)

        col3_layout.addLayout(conn_status_layout)

        splitter.addWidget(col3_group)

        # 8d - PROPORCIONES DE LAS COLUMNAS:
        splitter.setSizes([300, 300, 450])
        layout.addWidget(splitter, stretch=1)

        # 9 - AREA INFERIOR: USERS:
        users_group = QGroupBox(f"{ICON_USER}  Users")
        users_layout = QVBoxLayout(users_group)
        users_help = QLabel(
            "Un USER define COMO te autenticas: con un token, con un certificado "
            "cliente, o con usuario/contrasena. Los tokens se muestran enmascarados por seguridad."
        )
        users_help.setObjectName("help")
        users_help.setWordWrap(True)
        users_layout.addWidget(users_help)
        self.table_users = QTableWidget(0, 4)
        self.table_users.setHorizontalHeaderLabels(["Name", "Token", "Client Cert", "Auth Type"])
        self.table_users.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        users_layout.addWidget(self.table_users)
        layout.addWidget(users_group)

        # 10 - ETIQUETA DE ESTADO:
        self.lbl_status = QLabel(f"{ICON_WARN}  Sin kubeconfig cargado")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_status)

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

    def on_load_default(self):
        # 1 - CARGO EL KUBECONFIG DE PRUEBA:
        if not os.path.exists(DEFAULT_KUBECONFIG):
            QMessageBox.warning(
                self,
                f"{ICON_WARN} No encontrado",
                f"No se encontro el archivo de prueba:\n{DEFAULT_KUBECONFIG}",
            )
            return
        self.load_kubeconfig(DEFAULT_KUBECONFIG)

    def on_copy_to_user_config(self):
        # 1 - VERIFICO QUE HAYA UN KUBECONFIG CARGADO:
        if not self.config or not hasattr(self, "_loaded_file_path"):
            return

        # 2 - PREGUNTO AL USUARIO SI QUIERE COPIAR:
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

        # 3 - CREO EL DIRECTORIO ~/.kube SI NO EXISTE:
        kube_dir = os.path.dirname(USER_KUBECONFIG)
        try:
            os.makedirs(kube_dir, exist_ok=True)
            shutil.copy2(self._loaded_file_path, USER_KUBECONFIG)
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

        # 2 - GUARDO LA RUTA DEL ARCHIVO CARGADO:
        self._loaded_file_path = file_path

        # 3 - METADATOS:
        self.lbl_file_path.setText(file_path)
        self.lbl_api_version.setText(str(self.config.get("apiVersion", "-")))
        self.lbl_kind.setText(str(self.config.get("kind", "-")))
        self.current_context_name = self.config.get("current-context", "-")
        self.lbl_current_context.setText(str(self.current_context_name))

        # 4 - LIMPIO LAS LISTAS Y TABLAS:
        self.list_clusters.clear()
        self.list_contexts.clear()
        self.table_pods.setRowCount(0)
        self.table_users.setRowCount(0)

        # 5 - POBLA COLUMNA 1: CLUSTERS:
        for c in self.config.get("clusters", []):
            name = c.get("name", "(sin nombre)")
            item = QListWidgetItem(f"{ICON_CLUSTER}  {name}")
            item.setData(Qt.UserRole, c)
            self.list_clusters.addItem(item)

        # 6 - POBLA AREA INFERIOR: USERS:
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

        # 7 - HABILITO EL BOTON DE COPIAR:
        self.btn_copy_user.setEnabled(True)

        # 8 - ESTADO FINAL:
        n_clusters = len(self.config.get("clusters", []))
        n_users = len(users)
        n_contexts = len(self.config.get("contexts", []))
        self.lbl_status.setText(
            f"{ICON_OK}  Kubeconfig cargado: "
            f"{n_clusters} cluster(s), {n_users} user(s), {n_contexts} context(s)"
        )

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

        # 4 - LIMPIO LAS TABLAS DE PODS Y SERVICES:
        self.table_pods.setRowCount(0)
        self.table_services.setRowCount(0)
        self.lbl_connection_status.setText("-")
        self.lbl_pods_title.setText(f"{ICON_POD}  Pods del namespace:")
        self.lbl_services_title.setText("\U0001F310  Services del namespace:")

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

            # 9 - MUESTRO EL RESULTADO EN LOS TITULOS Y DEBAJO DE LA TABLA:
            n_pods = len(pods)
            n_svcs = len(services)
            self.lbl_pods_title.setText(
                f"{ICON_POD}  Pods del namespace:  ({n_pods})"
            )
            self.lbl_services_title.setText(
                f"\U0001F310  Services del namespace:  ({n_svcs})"
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
        detail_window = PodDetailWindow(pod, self)
        detail_window.exec()


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
