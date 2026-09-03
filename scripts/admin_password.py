"""Genera el valor de ADMIN_PASSWORD_HASH para el panel de administración.

La contraseña nunca se guarda en texto plano, ni en el .env ni en el panel del
hosting: se guarda su hash. Este script hace esa conversión.

    python -m scripts.admin_password                  # pide la clave y no la muestra
    python -m scripts.admin_password --generar        # inventa una clave segura

Después hay que pegar la línea resultante en el archivo .env, o cargar la
variable en el hosting (en Render: Environment → Add Environment Variable).
"""

import argparse
import getpass
import sys

from app.services.admin_auth import hash_para_configurar
from app.services.auth import generate_password

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

LINE = "-" * 72
LARGO_MINIMO = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el hash de la clave del panel de administración.")
    parser.add_argument(
        "--generar",
        action="store_true",
        help="Inventa una contraseña segura en vez de pedirla.",
    )
    args = parser.parse_args()

    if args.generar:
        password = generate_password(16)
        print(f"\n{LINE}\n  CONTRASEÑA GENERADA\n{LINE}\n")
        print(f"    {password}\n")
        print("  Guárdala en tu gestor de contraseñas AHORA: no se puede recuperar,")
        print("  porque lo que se almacena es solo su hash.\n")
    else:
        # getpass no muestra lo que se escribe: la clave no queda en el historial
        # de la terminal ni a la vista de quien pase por detrás.
        password = getpass.getpass("  Contraseña para el panel de administración: ")
        repetir = getpass.getpass("  Repítela: ")

        if password != repetir:
            sys.exit("\n  Las dos contraseñas no coinciden. No se generó nada.")
        if len(password) < LARGO_MINIMO:
            sys.exit(
                f"\n  Muy corta: mínimo {LARGO_MINIMO} caracteres.\n"
                "  Esta clave abre el panel de TODOS tus clientes, no la de uno solo."
            )

    print(f"{LINE}\n  PEGA ESTA LÍNEA EN TU ARCHIVO .env\n{LINE}\n")
    print(f"ADMIN_PASSWORD_HASH={hash_para_configurar(password)}\n")
    print("  En el hosting, cárgala como variable de entorno con ese mismo nombre.")
    print("  Mientras esté vacía, el panel de administración responde 404.\n")


if __name__ == "__main__":
    main()
