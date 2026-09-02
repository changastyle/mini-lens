"""
Test: verifica que MiniLens puede leer un kubeconfig correctamente.
No necesita PySide6 ni conexión al cluster. Solo parsea el YAML y muestra
la información por consola.

Uso:
    python test_kubeconfig.py
"""

import os
import sys
import yaml


# 1 - RUTA AL KUBECONFIG DE PRUEBA:
KUBECONFIG_PATH = os.path.join(
    os.path.dirname(__file__), ".vscode", "test", "kubeconfig-openshift-indramind.yaml"
)


def main():
    # 2 - VERIFICO QUE EL ARCHIVO EXISTE:
    if not os.path.exists(KUBECONFIG_PATH):
        print(f"[ERROR] No se encontro el archivo: {KUBECONFIG_PATH}")
        sys.exit(1)

    print(f"[OK] Archivo encontrado: {KUBECONFIG_PATH}")
    print()

    # 3 - LEO EL ARCHIVO YAML:
    with open(KUBECONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 4 - VERIFICO QUE TENGA LA ESTRUCTURA DE UN KUBECONFIG:
    if config.get("apiVersion") != "v1":
        print(f"[WARN] apiVersion inesperado: {config.get('apiVersion')}")
    else:
        print(f"[OK] apiVersion: {config['apiVersion']}")

    if config.get("kind") != "Config":
        print(f"[WARN] kind inesperado: {config.get('kind')}")
    else:
        print(f"[OK] kind: {config['kind']}")

    print()

    # 5 - LISTO LOS CLUSTERS:
    clusters = config.get("clusters", [])
    print(f"=== CLUSTERS ({len(clusters)}) ===")
    for c in clusters:
        name = c.get("name", "(sin nombre)")
        server = c.get("cluster", {}).get("server", "(sin server)")
        skip_tls = c.get("cluster", {}).get("insecure-skip-tls-verify", False)
        print(f"  - {name}")
        print(f"      server: {server}")
        print(f"      insecure-skip-tls-verify: {skip_tls}")
    print()

    # 6 - LISTO LOS USERS (sin mostrar el token completo):
    users = config.get("users", [])
    print(f"=== USERS ({len(users)}) ===")
    for u in users:
        name = u.get("name", "(sin nombre)")
        token = u.get("user", {}).get("token", "")
        # Mostrar solo los primeros 8 caracteres del token por seguridad:
        masked = token[:8] + "..." if token else "(sin token)"
        print(f"  - {name}")
        print(f"      token: {masked}")
    print()

    # 7 - LISTO LOS CONTEXTS:
    contexts = config.get("contexts", [])
    print(f"=== CONTEXTS ({len(contexts)}) ===")
    for ctx in contexts:
        name = ctx.get("name", "(sin nombre)")
        c = ctx.get("context", {})
        cluster = c.get("cluster", "(sin cluster)")
        namespace = c.get("namespace", "(sin namespace)")
        user = c.get("user", "(sin user)")
        print(f"  - {name}")
        print(f"      cluster:   {cluster}")
        print(f"      namespace: {namespace}")
        print(f"      user:      {user}")
    print()

    # 8 - MUESTRO EL CURRENT-CONTEXT:
    current = config.get("current-context", "(no definido)")
    print(f"=== CURRENT-CONTEXT ===")
    print(f"  {current}")
    print()

    # 9 - VERIFICO QUE EL CURRENT-CONTEXT EXISTA EN LA LISTA:
    context_names = [ctx.get("name") for ctx in contexts]
    if current in context_names:
        print("[OK] current-context es valido (existe en la lista de contexts)")
    else:
        print(f"[ERROR] current-context '{current}' no existe en la lista de contexts")

    print()
    print("[DONE] Test completado.")


if __name__ == "__main__":
    main()
