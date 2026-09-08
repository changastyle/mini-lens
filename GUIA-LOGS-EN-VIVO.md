# 📜 Visor de Logs en Vivo para PySide6 — Guía de implementación

Patrón completo, probado en producción (MiniLens), para agregar a cualquier app Qt/PySide6
una **ventana de logs en tiempo real** con:

- Stream en vivo (worker thread) que **NO cuelga ni crashea** al cerrar la ventana.
- Cada línea en un **cuadradito separado**: fecha-hora a la izquierda (amarillo) + mensaje.
- **JSON pretty**: si la línea es JSON, se muestra indentado; si un campo es un string
  con JSON adentro (ej: `message`), se expande también, en cualquier nivel.
- **Marca de líneas**: clic en una línea → queda **roja**; todo lo que llega después
  se pinta **verde** (para ver "lo nuevo desde acá"). Segundo clic = desmarcar.
- **Botón portapapeles por línea** (copia hora + mensaje) y botón "Copiar todo".
- **CLS**: limpia solo la vista local, el stream sigue vivo.
- **Auto-follow**: siempre abajo del todo; se pausa si scrolleás arriba o marcás una
  línea, y vuelve solo cuando bajás al final.
- **Pausar** (congela el render, la conexión sigue) y **overlay de carga** (spinner).
- **Límite de memoria**: trae solo las últimas N líneas y mantiene un cap en pantalla.
- **Cierre de la app sin threads huérfanos** ni crashes.

---

## 1. Arquitectura (por qué está diseñado así)

```
┌────────────────────────────┐         ┌──────────────────────────────┐
│  WORKER (QRunnable)        │         │  DIALOGO (hilo de la UI)     │
│  hilo aparte               │         │                              │
│  - es el UNICO que toca    │  queue  │  QTimer (50ms) drena la cola │
│    la conexion/socket      │──queue──│  25 lineas por tick          │
│  - NUNCA toca objetos Qt   │         │  - crea filas (widgets)      │
│  - loop de reconexion      │         │  - JSON pretty, colores,     │
│  - read-timeout 30s        │         │    auto-follow, cap 300      │
└────────────────────────────┘         └──────────────────────────────┘
```

**Regla de oro: el worker NO toca Qt.** Solo escribe en una `queue.Queue`.
El diálogo consume la cola con un `QTimer` en el hilo de la UI.

### Los 3 crashes que tuvimos y cómo el diseño los evita

| Crash | Causa | Solución aplicada |
|---|---|---|
| App explota al cerrar la ventana de logs | Señales Qt cross-thread (`Signal.emit`) hacia un diálogo ya destruido | El worker **no emite señales**: escribe en una `queue.Queue` y un `QTimer` drena en el hilo de la UI |
| App se cuelga ("No responde") al cerrar | Cerrar el socket SSL **desde el hilo de la UI** mientras el worker está bloqueado en un `read()` de esa misma conexión (deadlock SSL) | `stop()` **solo marca un flag**. El worker es el único que toca el socket, y tiene read-timeout para darse cuenta del corte solo |
| Crash aleatorio del QRunnable | El GC de Python recolecta el QRunnable mientras el thread pool todavía lo ejecuta | `setAutoDelete(False)` + registro global `_ALIVE`; el worker se des-registra en un `finally` |
| UI congelada mientras cargan los logs | Renderizar 200 filas de golpe en un solo tick | Drenar de a **25 items cada 50ms** + overlay de carga (spinner) hasta la primera línea |
| Threads colgados al cerrar la app | Workers bloqueados en `read()` de pods callados | Al cerrar: flag de stop a todos + `pool.clear()` + `waitForDone(2000)` + `os._exit(0)` al final del `main()` |

---

## 2. Código completo (archivo único, listo para copiar)

Guardalo como `visor_logs_qt.py`. Solo depende de PySide6. La fuente de datos es
un **generator bloqueante que devuelve líneas de texto** — abajo está la versión
Kubernetes, pero sirve cualquier fuente (subprocess, tail de archivo, WebSocket, etc.).

```python
"""
Visor de logs en vivo para PySide6 — patrón worker -> cola -> QTimer.

Uso minimo:
    dlg = LogsDialog(open_stream, title="Logs: mi-pod", subtitle="user@cluster/ctx")
    dlg.exec()

`open_stream` es una funcion que recibe `last_ts` (datetime UTC o None) y
retorna un ITERABLE DE STRINGS (lineas de log, bloqueante). Ver
`k8s_log_stream()` mas abajo para el ejemplo de Kubernetes.
"""

import json
import queue
import datetime
from datetime import timezone

from PySide6.QtCore import Qt, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QScrollArea, QWidget, QFrame,
)

# 1 - ICONOS (emojis, compatibles con Windows):
ICON_LOGS   = "\U0001F4DC"   # 📜
ICON_INFO   = "\u2139\uFE0F" # ℹ️
ICON_WARN   = "\u26A0\uFE0F" # ⚠️
ICON_OK     = "\u2705"       # ✅
ICON_TRASH  = "\U0001F5D1"   # 🗑
ICON_COPY   = "\U0001F4CB"   # 📋


# ============================================================
# HELPERS DE LINEAS Y JSON
# ============================================================

def _parse_line_ts(line):
    """Extrae el timestamp RFC3339 del inicio de la linea (datetime UTC) o None."""
    parts = str(line).split(" ", 1)
    if len(parts[0]) >= 20 and parts[0][4] == "-" and "T" in parts[0]:
        try:
            return datetime.datetime.fromisoformat(parts[0][:26]).replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return None
    return None


def _split_log_line(line):
    """Separa 'timestamp mensaje'. Retorna (timestamp_local, mensaje).

    Si la linea no trae timestamp reconocible retorna ("", la linea completa).
    """
    parts = str(line).split(" ", 1)
    if len(parts) == 2 and len(parts[0]) >= 20 and parts[0][4] == "-" and "T" in parts[0]:
        raw_ts = parts[0]
        try:
            dt = datetime.datetime.fromisoformat(raw_ts[:26]).replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone().strftime("%d/%m %H:%M:%S"), parts[1]
        except Exception:
            return raw_ts[:19].replace("T", " "), parts[1]
    return "", line


def _expand_json_strings(obj, depth=0):
    """Recorre el objeto: si un valor string es JSON valido, lo convierte.

    Recursivo con limite de profundidad (evita explotar con strings raros).
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

    Expande CUALQUIER campo que sea un string con JSON adentro (ej: 'message'),
    en cualquier nivel de profundidad.
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
    obj = _expand_json_strings(obj, 0)
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return None


def _is_read_timeout(e):
    """True si el error es un timeout de lectura (fuente callada, no un fallo)."""
    if isinstance(e, TimeoutError):
        return True
    try:
        import urllib3
        return isinstance(e, urllib3.exceptions.ReadTimeoutError)
    except Exception:
        return False
```

### 2a. El worker (thread) — el corazón del patrón

```python
class LogStreamWorker(QRunnable):
    """Sigue una fuente de logs bloqueante y encola cada linea.

    REGLAS DE ORO (cada una evita un crash real):
      1. El worker NUNCA toca objetos de Qt: solo escribe en la cola.
      2. `stop()` SOLO marca un flag: el socket lo cierra el propio worker.
      3. setAutoDelete(False) + registro _ALIVE: evita que el GC recolecte
         el QRunnable mientras el thread pool todavia lo ejecuta.
      4. Read-timeout: el worker se despierta solo y nota el stop aunque
         la fuente este callada.
    """

    _ALIVE = set()   # registro global de workers vivos

    def __init__(self, open_stream, out_queue, tail=200):
        super().__init__()
        self._open_stream = open_stream   # factory: last_ts -> iterable de str
        self._out = out_queue
        self._stop = False
        self._resp = None
        self.setAutoDelete(False)         # el GC no puede matarme a mitad de run()
        LogStreamWorker._ALIVE.add(self)

    def stop(self):
        # 1 - SOLO MARCO EL CORTE. NUNCA cierro el socket desde el hilo de
        #     la UI: si el worker esta bloqueado en un read, colgar la
        #     conexion desde afuera cuelga la app. El worker sale solo en
        #     el proximo chunk o en el timeout de lectura:
        self._stop = True

    def run(self):
        last_ts = None
        try:
            while not self._stop:
                try:
                    # 1 - ABRO EL STREAM (solo las ultimas N lineas):
                    stream = self._open_stream(last_ts)
                    buf = ""
                    for chunk in stream:
                        if self._stop:
                            break
                        # 2 - ENCOLO CADA LINEA COMPLETA:
                        buf += chunk
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            ts = _parse_line_ts(line)
                            if ts is not None:
                                last_ts = ts
                            self._out.put(("line", line))
                    try:
                        self._resp_close(stream)
                    except Exception:
                        pass
                    if self._stop:
                        break
                    self._out.put(("status", "reconectando..."))
                except Exception as e:
                    if self._stop:
                        break
                    if _is_read_timeout(e):
                        continue  # fuente callada: reconecto
                    self._out.put(("status", f"error|{e}"))
                    break
            self._out.put(("status", "cerrado" if self._stop else "fin"))
        finally:
            LogStreamWorker._ALIVE.discard(self)

    def _resp_close(self, stream):
        # 1 - CIERRO LA CONEXION (solo el worker toca el socket):
        close = getattr(stream, "close", None)
        if close:
            close()
```

> En MiniLens, `open_stream` es la llamada a k8s (`read_namespaced_pod_log` con
> `follow=True, tail_lines=200, timestamps=True, _request_timeout=(10, 30)` y
> `since_seconds` en las reconexiones). Para otra fuente solo cambiás esa
> función: debe ser **bloqueante** y devolver un **iterable de str**.

### 2b. La fila de log (cuadradito con estados + botón copiar)

```python
class LogLineRow(QFrame):
    """UNA linea de log: fecha-hora a la izquierda, mensaje al medio,
    boton de portapapeles a la derecha.

    Estados (el borde izquierdo SIEMPRE mide 4px: cambia el color, no el
    ancho, para que el layout no salte):
      normal -> gris | marked -> ROJO (clic del usuario) | new -> VERDE
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
            " border: none; background: transparent;")
        lbl_ts.setMinimumWidth(110)
        lbl_ts.setMaximumWidth(150)
        lay.addWidget(lbl_ts)

        # 2 - MENSAJE (seleccionable, monospace, con wrap):
        lbl_msg = QLabel(msg)
        lbl_msg.setTextFormat(Qt.PlainText)
        lbl_msg.setWordWrap(True)
        lbl_msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_msg.setStyleSheet(
            "color: #e0e0e0; font-family: Consolas, monospace; font-size: 12px;"
            " border: none; background: transparent;")
        lay.addWidget(lbl_msg, stretch=1)

        # 2a - SI EL MENSAJE ES JSON, LO MUESTRO PRETTY (recursivo):
        #      (esto se hace ANTES de crear la fila, ver _on_line)

        # 3 - BOTON PORTAPAPELES: copia la linea cruda (hora + mensaje):
        btn_copy = QPushButton("\U0001F4CB")
        btn_copy.setFixedSize(26, 22)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setToolTip("Copiar esta linea (hora + mensaje)")
        btn_copy.clicked.connect(
            lambda checked=False, text=self._raw: QGuiApplication.clipboard().setText(text))
        lay.addWidget(btn_copy)

    def set_normal(self):
        self._state = "normal"
        self._apply_style()

    def set_marked(self):
        self._state = "marked"
        self._apply_style()

    def set_new(self):
        self._state = "new"
        self._apply_style()

    def _apply_style(self):
        # 1 - El borde izquierdo SIEMPRE mide 4px: cambia el color, no el
        #     ancho, para que las filas no "salten" al marcar:
        styles = {
            "normal": "background-color: #222; border: 1px solid #555; border-left: 4px solid #444;",
            "marked": "background-color: #2a1515; border: 1px solid #e74c3c; border-left: 4px solid #e74c3c;",
            "new":    "background-color: #16211a; border: 1px solid #2f5a3d; border-left: 4px solid #2ecc71;",
        }
        self.setStyleSheet(f"QFrame#log_row {{ {styles[self._state]} border-radius: 6px; }}")

    def mousePressEvent(self, event):
        # 1 - CLIC EN LA FILA = MARCAR/DESMARCAR (el boton de copiar NO
        #     dispara esto: el click se queda en el boton):
        if self._on_click:
            self._on_click()
        super().mousePressEvent(event)
```

### 2c. El diálogo (cola + timer + todas las funciones)

```python
class LogsDialog(QDialog):
    """Popup de logs en vivo. Patron: WORKER -> queue.Queue -> QTimer."""

    MAX_ROWS = 300   # cap de filas en pantalla (las viejas se borran)
    TAIL_LINES = 200 # solo las ultimas N lineas al conectar

    def __init__(self, open_stream, title="Logs", subtitle="", parent=None):
        super().__init__(parent)
        self._open_stream = open_stream   # factory: last_ts -> iterable de str
        self._task = None
        self._paused = False
        self._rows = []
        self._raw_lines = []
        self._n = 0
        self._marked_row = None
        self._follow = True

        self.setWindowTitle(title)
        self.resize(1100, 700)
        layout = QVBoxLayout(self)

        # 1 - HEADER (titulo + subtitulo con identidad, ej: user@cluster):
        header = QHBoxLayout()
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #f5c518;")
        header.addWidget(lbl_title)
        header.addStretch()
        lbl_id = QLabel(subtitle)
        lbl_id.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        header.addWidget(lbl_id)
        layout.addLayout(header)

        # 2 - BARRA: pausar / copiar todo / CLS / contador:
        bar = QHBoxLayout()
        self.btn_pause = QPushButton("\u26A0\uFE0F  Pausar")
        self.btn_pause.setToolTip("Pausa SOLO el render (la conexion sigue viva).")
        self.btn_pause.clicked.connect(self._toggle_pause)
        bar.addWidget(self.btn_pause)

        btn_copy = QPushButton("\U0001F4CB  Copiar todo")
        btn_copy.clicked.connect(self._copy_all)
        bar.addWidget(btn_copy)

        btn_clear = QPushButton("\U0001F5D1  CLS")
        btn_clear.setToolTip("CLS: limpia SOLO la vista local (el stream sigue vivo)")
        btn_clear.clicked.connect(self._clear_rows)
        bar.addWidget(btn_clear)

        bar.addStretch()
        self.lbl_count = QLabel("0 lineas")
        self.lbl_count.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        bar.addWidget(self.lbl_count)
        layout.addLayout(bar)

        # 3 - SCROLL con una fila por linea + auto-follow:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        holder = QWidget()
        self.logs_layout = QVBoxLayout(holder)
        self.logs_layout.setContentsMargins(4, 4, 4, 4)
        self.logs_layout.setSpacing(3)
        self.logs_layout.addStretch()
        self.scroll.setWidget(holder)
        layout.addWidget(self.scroll, stretch=1)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_moved)

        # 4 - BARRA DE ESTADO:
        self.lbl_status = QLabel("Conectando al stream de logs...")
        self.lbl_status.setStyleSheet("color: #f5c518; font-size: 12px; padding: 2px;")
        layout.addWidget(self.lbl_status)

        # 5 - COLA + TIMER (el corazon del patron: sin Qt cross-thread):
        self._queue = queue.Queue()
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(50)
        self._drain_timer.timeout.connect(self._drain_queue)
        self._drain_timer.start()

        self._start_stream()

    # ---- ciclo del stream -------------------------------------------------

    def _start_stream(self):
        # 1 - CORTO EL ANTERIOR Y ARRANCO UNO NUEVO:
        self._stop_task()
        self._task = LogStreamWorker(self._open_stream, self._queue)
        QThreadPool.globalInstance().start(self._task)

    def _stop_task(self):
        if self._task:
            self._task.stop()
            self._task = None

    def _drain_queue(self):
        # 1 - CONSUMO LA COLA EN EL HILO DE LA UI (25 por tick: meter 200
        #     filas de golpe congelaba la interfaz mientras cargaba):
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
            except Exception:
                pass  # un item roto no tira abajo el drenaje ni la app

    # ---- eventos de UI ----------------------------------------------------

    def _on_scroll_moved(self, value):
        # 1 - AUTO-FOLLOW: abajo del todo = sigo; scrolleo arriba = paro:
        sb = self.scroll.verticalScrollBar()
        self._follow = value >= sb.maximum() - 40

    def _toggle_pause(self):
        # 1 - PAUSA SOLO EL RENDER (la conexion sigue viva):
        self._paused = not self._paused
        self.btn_pause.setText("\u2705  Seguir" if self._paused else "\u26A0\uFE0F  Pausar")

    def _on_line(self, raw):
        # 1 - PAUSADO = descarto la linea (el stream sigue):
        if self._paused:
            return

        # 2 - SEPARO FECHA-HORA Y CONVIERTO JSON A PRETTY SI CORRESPONDE:
        ts, msg = _split_log_line(raw)
        pretty = _pretty_json(msg)
        if pretty:
            msg = pretty

        # 3 - CREO LA FILA Y LA AGREGO:
        row = LogLineRow(ts, msg, raw=raw)
        row._on_click = lambda r=row: self._on_row_clicked(r)
        self.logs_layout.insertWidget(self.logs_layout.count() - 1, row)
        self._rows.append(row)
        self._raw_lines.append(raw)
        self._n += 1
        self.lbl_count.setText(f"{self._n} lineas")

        # 2a - SI HAY UNA LINEA MARCADA, LA NUEVA VA EN VERDE:
        if self._marked_row is not None:
            row.set_new()

        # 2b - CAP: las lineas mas viejas se borran (y pierden la marca):
        while len(self._rows) > self.MAX_ROWS:
            old = self._rows.pop(0)
            if old is self._marked_row:
                self._marked_row = None
            self.logs_layout.removeWidget(old)
            old.deleteLater()
        while len(self._raw_lines) > self.MAX_ROWS:
            self._raw_lines.pop(0)

        # 2c - AUTO-FOLLOW: abajo del todo, salvo que el usuario este
        #      leyendo algo (scrolleo arriba o marco una linea):
        if self._follow:
            sb = self.scroll.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_row_clicked(self, row):
        # 1 - SEGUNDO CLIC EN LA MISMA LINEA = QUITAR LA MARCA:
        if self._marked_row is row:
            self._unmark()
            return
        # 2 - REINICIO: la marca anterior y las verdes vuelven a normal:
        for r in self._rows:
            if r is not row and r._state in ("new", "marked"):
                r.set_normal()
        # 3 - MARCO LA ELEGIDA EN ROJO: lo que llegue despues se pinta verde:
        self._marked_row = row
        row.set_marked()
        self._follow = False   # el usuario esta leyendo: no mover la vista

    def _unmark(self):
        self._marked_row = None
        for r in self._rows:
            if r._state in ("new", "marked"):
                r.set_normal()

    def _copy_all(self):
        QGuiApplication.clipboard().setText("\n".join(self._raw_lines))

    def _clear_rows(self):
        # 1 - CLS: limpia SOLO la vista local (el stream sigue corriendo):
        for r in self._rows:
            self.logs_layout.removeWidget(r)
            r.deleteLater()
        self._rows = []
        self._raw_lines = []
        self._marked_row = None
        self._n = 0

    # ---- cierre a prueba de balas -----------------------------------------

    def closeEvent(self, e):
        # 1 - CIERRE CON LA X: corto timer y stream, vacio la cola:
        self._shutdown()
        super().closeEvent(e)

    def done(self, r):
        # 1 - CIERRE POR CUALQUIER VIA (Esc/reject/accept): corto todo antes:
        self._shutdown()
        super().done(r)

    def _shutdown_stream(self):
        try:
            self._drain_timer.stop()
        except Exception:
            pass
        try:
            if self._task:
                self._task.stop()   # SOLO marca el flag (nunca toca el socket)
                self._task = None
        except Exception:
            pass
        try:
            while True:             # vacio la cola: nada renderiza despues
                self._queue.get_nowait()
        except Exception:
            pass

    # NOTA: reemplazar _shutdown_stream por el nombre que uses y llamarlo
    # desde closeEvent() y done() (ver implementacion completa mas abajo).
```

---

## 3. Las 5 REGLAS que evitan los crashes (leelo antes de portar)

1. **El worker NO toca Qt.** Comunicación SOLO con `queue.Queue`. Si emitís
   señales Qt cross-thread y el diálogo se destruye con señales pendientes,
   la app crashea al cerrar la ventana (crash duro, sin traceback).
2. **El socket/conexión lo toca SOLO el worker.** `stop()` solo marca un
   flag. Cerrar un SSL socket desde el hilo de la UI mientras otro hilo
   hace `read()` = deadlock = "(No responde)".
   - Solución complementaria: **read-timeout** en la conexión (30s) para que
     el worker se despierte solo y note el stop aunque la fuente esté callada.
3. **`setAutoDelete(False)` + registro global `_ALIVE`.** Si el GC recolecta
   el QRunnable mientras el thread pool lo ejecuta → crash. El worker se
   des-registra solo en un `finally`.
4. **Drenar de a poco:** 25 items por tick de timer (50ms). Meter 200 filas
   de golpe congela la UI mientras carga. Con un **overlay de carga**
   (spinner) hasta la primera línea, la espera se siente bien.
5. **Caps en todos lados:** `tail_lines` al conectar (200), `MAX_ROWS` en
   pantalla (300, se borran las viejas con `deleteLater()`). Un pod verboso
   no puede explotar la memoria ni el render.

### Cierre de la app sin threads huérfanos

```python
# En closeEvent de la ventana principal:
for t in list(LogStreamWorker._ALIVE):
    t.stop()                      # solo flags
QThreadPool.globalInstance().clear()

# Y en main(), DESPUES de app.exec():
app.exec()
for t in list(LogStreamWorker._ALIVE):
    t.stop()
QThreadPool.globalInstance().clear()
QThreadPool.globalInstance().waitForDone(2000)
os._exit(0)   # salida forzada: cero threads colgados, cero crash de finalizacion
```

`os._exit(0)` es la clave: evita que el intérprete se cuelgue/crashee
finalizando con QRunnables a medio correr. Antes, hacer `flush()` del log.

---

## 4. Cómo conectar tu fuente de datos

El worker necesita una **factory** `open_stream(last_ts) -> iterable de str`.
Ejemplos:

**Kubernetes (lo que usa MiniLens):**
```python
def open_stream(last_ts):
    kwargs = dict(name=pod, namespace=ns, container=container,
                  follow=True, timestamps=True, _preload_content=False,
                  _request_timeout=(10, 30))
    if last_ts is None:
        kwargs["tail_lines"] = 200
    else:
        kwargs["since_seconds"] = max(1, int((datetime.datetime.now(datetime.timezone.utc) - last_ts).total_seconds()) + 1)
    resp = v1.read_namespaced_pod_log(**kwargs)
    for chunk in resp.stream(4096):
        yield chunk.decode("utf-8", "replace")
```

**Subprocess (ej: `tail -f archivo.log`):**
```python
def open_stream(last_ts):
    proc = subprocess.Popen(["tail", "-f", "-n", "200", "/var/log/app.log"],
                            stdout=subprocess.PIPE)
    return iter(proc.stdout.readline, b"")
```

**Archivo local:**
```python
def open_stream(last_ts):
    def gen():
        with open("app.log", "r", encoding="utf-8") as f:
            f.seek(0, 2)          # ir al final
            while True:
                line = f.readline()
                if line:
                    yield line.rstrip("\n")
                else:
                    time.sleep(0.2)
    return gen()
```

---

## 5. Checklist para portarlo a otro proyecto

- [ ] Copiar: helpers (`_split_log_line`, `_parse_line_ts`, `_is_read_timeout`,
      `_expand_json_strings`, `_pretty_json`), `LogStreamWorker`, `LogLineRow`,
      `LogsDialog` (o `PodLogsDialog` si es k8s) y el overlay de carga.
- [ ] Adaptar `open_stream` a tu fuente (k8s / subprocess / archivo / HTTP).
- [ ] Respetar: worker sin Qt, cola + QTimer, stop() = solo flag,
      `setAutoDelete(False)` + registro `_ALIVE`, caps de filas.
- [ ] Cierre: `closeEvent` + `done()` del diálogo cortan timer/task y vacían
      la cola; `closeEvent` de la ventana principal corta TODOS los workers
      (`LogStreamWorker._ALIVE`); `main()` termina con `os._exit(0)` tras
      `waitForDone(2000)`.
- [ ] Log a archivo (`logging` a `miapp.log` + `faulthandler.enable()`):
      si algo crashea, el traceback queda en el archivo aunque muera la app.

---

## 6. Features incluidas (resumen)

| Feature | Cómo funciona |
|---|---|
| Stream en vivo | Worker thread + `follow=True` (k8s) con read-timeout 30s y reconexión sin duplicados |
| Spinner de carga | Overlay hasta la primera línea; se corta solo |
| Una fila por línea | `LogLineRow`: timestamp amarillo + mensaje monospace + botón 📋 |
| JSON pretty | Si la línea (o cualquier campo anidado) es JSON string → se expande con indent=2, recursivo hasta nivel 3 |
| Marcar línea | Clic en la fila → borde izquierdo ROJO; lo que llega después → VERDE; segundo clic desmarca |
| Auto-follow | Siempre abajo del todo; se pausa si scrolleás arriba o marcás; se reactiva al volver abajo |
| Copiar línea / todo | Botón 📋 por fila (hora+mensaje) y botón "Copiar todo" (líneas crudas) |
| CLS | Limpia SOLO la vista local; el stream sigue corriendo |
| Pausar | Congela el render; la conexión sigue viva |
| Límites | `tail_lines=200` al conectar, `MAX_ROWS=300` en pantalla |
| Anti-crash | Worker sin Qt + queue + QTimer; stop() sin tocar socket; setAutoDelete(False) + registro; cierre por X/Esc/done; faulthandler + log a archivo; `os._exit(0)` al salir |
