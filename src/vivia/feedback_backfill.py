"""Rejoue dans Phoenix les votes 👍/👎 deja presents dans Open WebUI (0.10+). Idempotent.

La fonction `phoenix_feedback` ne voit que les votes donnes pendant qu'elle est active.
Ici on relit tous les feedbacks via l'API admin et on les poste avec la meme traduction
(`annotation`) : l'`identifier` est l'id du feedback, donc relancer met a jour au lieu
d'empiler. Seuls les tours deja traces par `phoenix_tracing` ont un span a annoter.
"""

import argparse
import importlib.util
import tomllib
from collections import Counter
from pathlib import Path

from vivia.configure.client import ROOT, OpenWebUI

FUNCTION = ROOT / "openwebui" / "functions" / "phoenix_feedback.py"


def load_function():
    """Importe la fonction Open WebUI par son chemin (elle vit hors du package)."""
    spec = importlib.util.spec_from_file_location("phoenix_feedback", FUNCTION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def feedbacks(api: OpenWebUI) -> list[dict]:
    return api.call("GET", "/api/v1/evaluations/feedbacks/all")


def backfill(items: list[dict], project: str, endpoint: str, dry_run: bool = False) -> Counter:
    fn = load_function()
    stats: Counter = Counter()
    for feedback in items:
        item = fn.annotation(feedback, project)
        if not item:
            stats["ignore"] += 1  # arene, brouillon sans vote, ids manquants
        elif dry_run:
            stats["a_envoyer"] += 1
        else:
            status = fn.post(endpoint, item)
            if 200 <= status < 300:
                stats["annote"] += 1
            elif status == 404:
                stats["sans_span"] += 1  # tour non trace par phoenix_tracing
            else:
                stats["erreur"] += 1
                print(f"  ! feedback {item['identifier']} -> HTTP {status}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=ROOT / "vivia.toml")
    parser.add_argument(
        "--endpoint", default="http://localhost:6006", help="Phoenix, vu depuis l'hote"
    )
    parser.add_argument("--project", help="defaut : valve project_name de phoenix_feedback")
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien envoyer")
    args = parser.parse_args()

    cfg = tomllib.loads(args.config.read_text())
    users = args.config.with_name("vivia.users.toml")
    if not users.exists():
        raise SystemExit(f"{users} absent (copier vivia.users.toml.example)")
    cfg |= tomllib.loads(users.read_text())

    project = args.project
    if not project:
        declared = next((f for f in cfg.get("functions", []) if f["id"] == "phoenix_feedback"), {})
        project = declared.get("valves", {}).get("project_name", "open-webui")

    api = OpenWebUI(cfg["openwebui"]["url"], cfg["admin"])
    items = feedbacks(api)
    print(f"> {len(items)} feedbacks, projet Phoenix '{project}', {args.endpoint}")
    stats = backfill(items, project, args.endpoint, args.dry_run)
    print(", ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "rien a faire")


if __name__ == "__main__":
    main()
