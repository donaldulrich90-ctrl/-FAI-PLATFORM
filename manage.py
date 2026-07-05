#!/usr/bin/env python
"""Point d'entrée Django pour Faso ISP Manager."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "faso_isp_manager.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Impossible d'importer Django. Installez les dépendances (pip install -r requirements.txt)."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
