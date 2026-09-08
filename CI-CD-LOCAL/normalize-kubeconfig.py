"""
NORMALIZE-KUBECONFIG.PY
Acomoda un kubeconfig YAML:
  1 - Claves duplicadas (ej: dos bloques 'users:') -> se acomodan
      (listas se unen, dicts se mezclan) en lugar de pisarse.
  2 - Contexts sin namespace -> se les asigna 'default'
      (o el que pases por --namespace).
  3 - Reporta lo que NO se puede arreglar automaticamente: contexts que
      apuntan a clusters/users inexistentes, clusters sin server,
      users sin credenciales.

Uso (con el python del venv, que tiene PyYAML):
    venv\\Scripts\\python.exe CI-CD-LOCAL\\normalize-kubeconfig.py <kubeconfig.yaml>
    venv\\Scripts\\python.exe CI-CD-LOCAL\\normalize-kubeconfig.py <kubeconfig.yaml> --in-place
    venv\\Scripts\\python.exe CI-CD-LOCAL\\normalize-kubeconfig.py <kubeconfig.yaml> --namespace default

Por defecto NO toca el archivo original: crea <nombre>-fixed.yaml.
Con --in-place sobreescribe el original (dejando un .bak de respaldo).
"""

import argparse
import os
import shutil
import sys

import yaml

# 1 - LOADER QUE DETECTA CLAVES DUPLICADAS:
DUP_KEYS = []

class DuplicateKeyLoader(yaml.SafeLoader):
    pass

def _construct_mapping(loader, node, deep=False):
    # 1 - CONSTRUYO EL MAPPING; SI HAY CLAVES DUPLICADAS LAS ACOMODO
    #     (listas se unen, dicts se mezclan) en lugar de pisar la primera:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        value = loader.construct_object(value_node, deep=deep)
        if key in mapping:
            DUP_KEYS.append(str(key))
            prev = mapping[key]
            if isinstance(prev, list) and isinstance(value, list):
                value = prev + value
            elif isinstance(prev, dict) and isinstance(value, dict):
                merged = dict(prev)
                merged.update(value)
                value = merged
        mapping[key] = value
    return mapping

DuplicateKeyLoader.add_constructor("tag:yaml.org,2002:map", _construct_mapping)


def validate(config):
    """Retorna lista de problemas que NO se pueden arreglar automaticamente."""
    issues = []
    clusters = config.get("clusters") or []
    users = config.get("users") or []
    contexts = config.get("contexts") or []

    cluster_names = {c.get("name") for c in clusters}
    user_names = {u.get("name") for u in users}

    # 1 - CADA CLUSTER DEBE TENER SERVER:
    for c in clusters:
        if not (c.get("cluster") or {}).get("server"):
            issues.append(f"ERROR: el cluster '{c.get('name')}' no define 'server'")

    # 2 - CADA USER DEBERIA TENER ALGUNA CREDENCIAL:
    for u in users:
        ud = u.get("user") or {}
        if not any([ud.get("token"), ud.get("client-certificate-data"), ud.get("username"), ud.get("exec")]):
            issues.append(f"AVISO: el user '{u.get('name')}' no tiene credenciales (token/cert/exec)")

    # 3 - CADA CONTEXT DEBE REFERENCIAR CLUSTER Y USER EXISTENTES:
    for c in contexts:
        name = c.get("name", "(sin nombre)")
        cd = c.get("context") or {}
        if cd.get("cluster") not in cluster_names:
            issues.append(f"ERROR: el context '{name}' referencia al cluster '{cd.get('cluster')}' que NO existe")
        if cd.get("user") and cd.get("user") not in user_names:
            issues.append(f"ERROR: el context '{name}' referencia al user '{cd.get('user')}' que NO existe")

    # 4 - CURRENT-CONTEXT VALIDO:
    cc = config.get("current-context")
    if cc and cc not in {c.get("name") for c in contexts}:
        issues.append(f"AVISO: current-context '{cc}' no existe en la lista de contexts")

    return issues


def main():
    # 1 - ARGUMENTOS:
    ap = argparse.ArgumentParser(description="Acomoda un kubeconfig YAML")
    ap.add_argument("archivo", help="ruta al kubeconfig")
    ap.add_argument("--in-place", action="store_true", help="sobreescribe el original (deja un .bak)")
    ap.add_argument("--namespace", default="default", help="namespace para contexts sin namespace (default: 'default')")
    args = ap.parse_args()

    if not os.path.exists(args.archivo):
        print(f"ERROR: no existe {args.archivo}")
        sys.exit(1)

    # 2 - CARGO CON DETECCION DE DUPLICADOS:
    DUP_KEYS.clear()
    with open(args.archivo, "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=DuplicateKeyLoader)

    # 3 - ACOMODO CLAVES DUPLICADAS:
    if DUP_KEYS:
        print(f"[AUTO-FIX] claves duplicadas acomodadas: {', '.join(sorted(set(DUP_KEYS)))}")

    # 4 - ACOMODO CONTEXTS SIN NAMESPACE:
    for c in config.get("contexts") or []:
        cd = c.get("context") or {}
        c["context"] = cd
        if not cd.get("namespace"):
            cd["namespace"] = args.namespace
            print(f"[AUTO-FIX] context '{c.get('name')}': namespace '{args.namespace}' asignado")

    # 5 - VALIDO LO QUE QUEDA (no auto-acomodable):
    issues = validate(config)
    for i in issues:
        print(i)

    # 6 - GUARDO:
    if args.in_place:
        shutil.copy2(args.archivo, args.archivo + ".bak")
        out = args.archivo
    else:
        base, ext = os.path.splitext(args.archivo)
        out = f"{base}-fixed{ext or '.yaml'}"

    with open(out, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)

    print()
    print(f"OK: kubeconfig acomodado guardado en: {out}")
    if issues:
        print("OJO: quedan problemas que no se pueden arreglar automaticamente (ver arriba).")


if __name__ == "__main__":
    main()
