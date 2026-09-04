"""
Modulo de base de datos SQLite para MiniLens.

Guarda:
- kubeconfigs (archivo YAML completo + metadatos)
- clusters (extraidos del kubeconfig, con flag de "pinned" a la hotbar)
- contexts (extraidos del kubeconfig, asociados a clusters)

Esquema:

  kubeconfigs(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    file_path   TEXT,
    yaml_content TEXT NOT NULL,
    api_version TEXT,
    kind        TEXT,
    current_context TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
  )

  clusters(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kubeconfig_id   INTEGER NOT NULL,
    name            TEXT NOT NULL,
    server          TEXT,
    pinned          INTEGER DEFAULT 0,
    color           TEXT DEFAULT '#3b8ad4',
    position        INTEGER DEFAULT 0,
    FOREIGN KEY (kubeconfig_id) REFERENCES kubeconfigs(id) ON DELETE CASCADE
  )

  contexts(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kubeconfig_id   INTEGER NOT NULL,
    cluster_id      INTEGER,
    name            TEXT NOT NULL,
    namespace       TEXT,
    user            TEXT,
    cluster_name    TEXT,
    is_current      INTEGER DEFAULT 0,
    FOREIGN KEY (kubeconfig_id) REFERENCES kubeconfigs(id) ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
  )
"""

import os
import sys
import sqlite3
import yaml

# 1 - RUTA A LA BASE DE DATOS:
#    Si la app esta empaquetada con PyInstaller (--onefile / --onedir),
#    __file__ apunta a una carpeta temporal que se borra al cerrar.
#    En ese caso, uso la ruta del .exe (sys.executable) para que la DB
#    viva al lado del ejecutable y persista entre ejecuciones.
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.dirname(__file__))

DB_DIR = os.path.join(_APP_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "minilens.db")


def _get_conn():
    # 1 - CREO EL DIRECTORIO SI NO EXISTE:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    # 1 - CREO LAS TABLAS SI NO EXISTEN:
    conn = _get_conn()
    cur = conn.cursor()

    # 1a - TABLA kubeconfigs:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kubeconfigs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT NOT NULL,
            file_path       TEXT,
            yaml_content    TEXT NOT NULL,
            api_version     TEXT,
            kind            TEXT,
            current_context TEXT,
            created_at      TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 1b - TABLA clusters:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            kubeconfig_id   INTEGER NOT NULL,
            name            TEXT NOT NULL,
            server          TEXT,
            pinned          INTEGER DEFAULT 0,
            color           TEXT DEFAULT '#3b8ad4',
            position        INTEGER DEFAULT 0,
            FOREIGN KEY (kubeconfig_id) REFERENCES kubeconfigs(id) ON DELETE CASCADE
        )
    """)

    # 1c - TABLA contexts:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contexts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            kubeconfig_id   INTEGER NOT NULL,
            cluster_id      INTEGER,
            name            TEXT NOT NULL,
            namespace       TEXT,
            user            TEXT,
            cluster_name    TEXT,
            is_current      INTEGER DEFAULT 0,
            FOREIGN KEY (kubeconfig_id) REFERENCES kubeconfigs(id) ON DELETE CASCADE,
            FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE SET NULL
        )
    """)

    # 1d - TABLA colors (paleta de colores guardados por el usuario):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS colors (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            hex             TEXT NOT NULL UNIQUE,
            name            TEXT,
            created_at      TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 1e - MIGRACION: agregar columnas alias, short_alias, icon a clusters si no existen:
    existing_cols = [row[1] for row in cur.execute("PRAGMA table_info(clusters)").fetchall()]
    for col, col_def in [
        ("alias", "TEXT"),
        ("short_alias", "TEXT"),
        ("icon", "TEXT"),
    ]:
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE clusters ADD COLUMN {col} {col_def}")

    # 1f - COLORES POR DEFECTO si la tabla colors esta vacia:
    count = cur.execute("SELECT COUNT(*) FROM colors").fetchone()[0]
    if count == 0:
        default_colors = [
            ("#3b8ad4", "Azul"),
            ("#1a8a6a", "Verde Teal"),
            ("#c77a1f", "Naranja"),
            ("#6a1b9a", "Purpura"),
            ("#1e3a8a", "Azul Oscuro"),
            ("#b91c1c", "Rojo"),
            ("#0e7490", "Cyan Oscuro"),
            ("#9d174d", "Magenta"),
        ]
        for hex_val, name in default_colors:
            cur.execute("INSERT OR IGNORE INTO colors (hex, name) VALUES (?, ?)", (hex_val, name))

    conn.commit()
    conn.close()


def import_kubeconfig(file_path):
    """
    Lee un archivo kubeconfig YAML, lo guarda en la DB y extrae clusters + contexts.
    Si ya existe un kubeconfig con el mismo filename, lo reemplaza.
    Retorna el kubeconfig_id.
    """
    # 1 - LEO EL ARCHIVO:
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    parsed = yaml.safe_load(raw)

    if not parsed:
        raise ValueError("El archivo no contiene YAML valido")

    filename = os.path.basename(file_path)
    api_version = str(parsed.get("apiVersion", ""))
    kind = str(parsed.get("kind", ""))
    current_context = str(parsed.get("current-context", ""))

    conn = _get_conn()
    cur = conn.cursor()

    # 2 - SI YA EXISTE UN KUBECONFIG CON EL MISMO FILENAME, LO BORRO:
    cur.execute("SELECT id FROM kubeconfigs WHERE filename = ?", (filename,))
    existing = cur.fetchone()
    if existing:
        cur.execute("DELETE FROM kubeconfigs WHERE id = ?", (existing["id"],))

    # 3 - INSERTO EL KUBECONFIG:
    cur.execute(
        "INSERT INTO kubeconfigs (filename, file_path, yaml_content, api_version, kind, current_context) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (filename, file_path, raw, api_version, kind, current_context),
    )
    kubeconfig_id = cur.lastrowid

    # 4 - EXTRAIGO Y GUARDO CLUSTERS:
    clusters_map = {}
    for c in parsed.get("clusters", []):
        name = c.get("name", "(sin nombre)")
        cluster_data = c.get("cluster", {})
        server = cluster_data.get("server", "")
        cur.execute(
            "INSERT INTO clusters (kubeconfig_id, name, server) VALUES (?, ?, ?)",
            (kubeconfig_id, name, server),
        )
        clusters_map[name] = cur.lastrowid

    # 5 - EXTRAIGO Y GUARDO CONTEXTS:
    for ctx in parsed.get("contexts", []):
        name = ctx.get("name", "(sin nombre)")
        ctx_data = ctx.get("context", {})
        cluster_name = ctx_data.get("cluster", "")
        namespace = ctx_data.get("namespace", "")
        user = ctx_data.get("user", "")
        cluster_id = clusters_map.get(cluster_name)
        is_current = 1 if name == current_context else 0
        cur.execute(
            "INSERT INTO contexts (kubeconfig_id, cluster_id, name, namespace, user, cluster_name, is_current) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kubeconfig_id, cluster_id, name, namespace, user, cluster_name, is_current),
        )

    conn.commit()
    conn.close()
    return kubeconfig_id


def get_all_kubeconfigs():
    """Retorna lista de dicts con todos los kubeconfigs guardados."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM kubeconfigs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_kubeconfig(kubeconfig_id):
    """Retorna el dict de un kubeconfig especifico."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM kubeconfigs WHERE id = ?", (kubeconfig_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_clusters(kubeconfig_id):
    """Retorna lista de clusters de un kubeconfig."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM clusters WHERE kubeconfig_id = ? ORDER BY id", (kubeconfig_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contexts(kubeconfig_id):
    """Retorna lista de contexts de un kubeconfig."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM contexts WHERE kubeconfig_id = ? ORDER BY id", (kubeconfig_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pinned_clusters():
    """Retorna todos los clusters anclados a la hotbar (de cualquier kubeconfig), ordenados por position."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT c.*, k.filename, k.yaml_content, k.file_path "
        "FROM clusters c JOIN kubeconfigs k ON c.kubeconfig_id = k.id "
        "WHERE c.pinned = 1 ORDER BY c.position"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def pin_cluster(cluster_id, color="#3b8ad4"):
    """Ancla un cluster a la hotbar."""
    conn = _get_conn()
    # 1 - CALCULO LA POSICION (ultimo + 1):
    max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM clusters WHERE pinned = 1").fetchone()[0]
    conn.execute(
        "UPDATE clusters SET pinned = 1, color = ?, position = ? WHERE id = ?",
        (color, max_pos + 1, cluster_id),
    )
    conn.commit()
    conn.close()


def unpin_cluster(cluster_id):
    """Desancla un cluster de la hotbar."""
    conn = _get_conn()
    conn.execute("UPDATE clusters SET pinned = 0, position = 0 WHERE id = ?", (cluster_id,))
    conn.commit()
    conn.close()


def delete_kubeconfig(kubeconfig_id):
    """Borra un kubeconfig y todos sus clusters/contexts asociados."""
    conn = _get_conn()
    conn.execute("DELETE FROM kubeconfigs WHERE id = ?", (kubeconfig_id,))
    conn.commit()
    conn.close()


def get_cluster(cluster_id):
    """Retorna un cluster especifico con su kubeconfig asociado."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT c.*, k.filename, k.yaml_content, k.file_path "
        "FROM clusters c JOIN kubeconfigs k ON c.kubeconfig_id = k.id "
        "WHERE c.id = ?", (cluster_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_cluster_appearance(cluster_id, alias=None, short_alias=None, color=None, icon=None):
    """Actualiza alias, short_alias, color e icon de un cluster anclado."""
    conn = _get_conn()
    fields = []
    values = []
    if alias is not None:
        fields.append("alias = ?")
        values.append(alias)
    if short_alias is not None:
        fields.append("short_alias = ?")
        values.append(short_alias)
    if color is not None:
        fields.append("color = ?")
        values.append(color)
    if icon is not None:
        fields.append("icon = ?")
        values.append(icon)
    if fields:
        values.append(cluster_id)
        conn.execute(f"UPDATE clusters SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()


def get_colors():
    """Retorna todos los colores guardados por el usuario."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM colors ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_color(hex_val, name=""):
    """Guarda un nuevo color en la paleta del usuario."""
    conn = _get_conn()
    conn.execute("INSERT OR IGNORE INTO colors (hex, name) VALUES (?, ?)", (hex_val, name))
    conn.commit()
    conn.close()


def delete_color(color_id):
    """Borra un color de la paleta del usuario."""
    conn = _get_conn()
    conn.execute("DELETE FROM colors WHERE id = ?", (color_id,))
    conn.commit()
    conn.close()
