"""Applique `vivia.toml` a Open WebUI via son API REST. Idempotent.

Un module par type de ressource ; `main` les applique dans l'ordre des dependances :
les skills et les fonctions existent avant que les modeles ne les referencent.
"""

import sys
import tomllib
from pathlib import Path

from vivia.configure.client import ROOT, OpenWebUI, deep_merge
from vivia.configure.functions import sync_functions
from vivia.configure.models import sync_models, upsert_model
from vivia.configure.settings import sync_api
from vivia.configure.skills import sync_skills
from vivia.configure.users import sync_users

__all__ = [
    "ROOT",
    "OpenWebUI",
    "deep_merge",
    "main",
    "sync_api",
    "sync_functions",
    "sync_models",
    "sync_skills",
    "sync_users",
    "upsert_model",
]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "vivia.toml"
    cfg = tomllib.loads(path.read_text())

    # Comptes et groupes : non commites (mots de passe en clair), dans un fichier a cote.
    users_path = path.with_name("vivia.users.toml")
    if not users_path.exists():
        sys.exit(f"{users_path} absent (copier vivia.users.toml.example)")
    cfg |= tomllib.loads(users_path.read_text())

    api = OpenWebUI(cfg["openwebui"]["url"], cfg["admin"])
    print(f"> {cfg['openwebui']['url']} (admin {cfg['admin']['email']})")

    sync_users(api, cfg.get("users", []), cfg.get("groups", []))
    sync_api(api, cfg.get("api", {}))
    sync_skills(api, cfg.get("skills", []))
    sync_functions(api, cfg.get("functions", []))
    sync_models(api, cfg.get("models", []), cfg["openwebui"].get("only_declared_models", False))
    print("done")


if __name__ == "__main__":
    main()
