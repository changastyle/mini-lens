from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 1 - CONFIGURO LA VENTANA PRINCIPAL:
        self.setWindowTitle("MiniLens")
        self.resize(800, 600)

        # 2 - CREO EL WIDGET CENTRAL Y EL LAYOUT PRINCIPAL:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 3 - CREO LA BARRA SUPERIOR CON EL BOTON DE CARGAR KUBECONFIG:
        top_bar = QHBoxLayout()
        self.btn_load_kubeconfig = QPushButton("Cargar kubeconfig", self)
        self.btn_load_kubeconfig.clicked.connect(self.on_load_kubeconfig)
        top_bar.addWidget(self.btn_load_kubeconfig)
        top_bar.addStretch()

        # 4 - CREO UNA ETIQUETA PARA MOSTRAR EL ESTADO DE LA CONEXION:
        self.lbl_status = QLabel("Sin conexion", self)
        self.lbl_status.setAlignment(Qt.AlignCenter)

        # 5 - ENSAMBLO TODO EN EL LAYOUT PRINCIPAL:
        layout.addLayout(top_bar)
        layout.addWidget(self.lbl_status)
        layout.addStretch()

        # 6 - GUARDO LA RUTA DEL KUBECONFIG CARGADO (POR AHORA VACIA):
        self.kubeconfig_path = None

    def on_load_kubeconfig(self):
        # 1 - ABRO EL DIALOGO PARA SELECCIONAR UN ARCHIVO:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar kubeconfig",
            "",
            "Todos los archivos (*);;Archivos YAML (*.yaml *.yml)",
        )

        # 2 - SI EL USUARIO CANCELA, NO HAGO NADA:
        if not file_path:
            return

        # 3 - GUARDO LA RUTA Y MUESTRO UN MENSAJE INFORMATIVO:
        self.kubeconfig_path = file_path
        self.lbl_status.setText(f"Kubeconfig seleccionado:\n{file_path}")
        QMessageBox.information(
            self,
            "Kubeconfig cargado",
            f"Archivo seleccionado:\n{file_path}\n\n"
            "En el siguiente paso leeremos los contexts y conectaremos al cluster.",
        )
