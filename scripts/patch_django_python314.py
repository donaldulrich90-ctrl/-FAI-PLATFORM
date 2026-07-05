"""
Corrige Django < 6 sur Python 3.14+ : BaseContext.__copy__ utilisait copy(super()),
ce qui casse l'admin et les tags {% include %} / submit_row.

Après chaque pip install -U django, relancer :
  .venv\\Scripts\\python scripts\\patch_django_python314.py

Recommandé : utiliser Python 3.12 ou 3.13 (support officiel Django 5.1).
"""
from __future__ import annotations

import pathlib
import sys


def main() -> int:
    try:
        import django
    except ImportError:
        print("Django non installé.", file=sys.stderr)
        return 1

    p = pathlib.Path(django.__file__).resolve().parent / "template" / "context.py"
    text = p.read_text(encoding="utf-8")
    if "duplicate = BaseContext()" in text and "def __copy__(self):" in text:
        print("Déjà corrigé :", p)
        return 0
    old = """    def __copy__(self):
        duplicate = copy(super())
        duplicate.dicts = self.dicts[:]
        return duplicate"""
    new = """    def __copy__(self):
        # Python 3.14+ : copy(super()) invalide (aligné sur django/django main).
        duplicate = BaseContext()
        duplicate.__class__ = self.__class__
        duplicate.__dict__ = copy(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate"""
    if old not in text:
        print("Motif __copy__ introuvable — vérifiez la version Django :", p, file=sys.stderr)
        return 1
    p.write_text(text.replace(old, new), encoding="utf-8")
    print("Correctif appliqué :", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
