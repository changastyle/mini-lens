import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    # 1 - CREO LA APLICACION QT:
    app = QApplication(sys.argv)

    # 2 - CREO Y MUESTRO LA VENTANA PRINCIPAL:
    window = MainWindow()
    window.show()

    # 3 - EJECUTO EL EVENT LOOP:
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
