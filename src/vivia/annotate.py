"""Rattrapage des votes 👍/👎 d'Open WebUI en annotations Phoenix, sur le bon span.

En temps reel, la fonction d'evenement `phoenix_feedback` le fait a chaque vote. Ce
script rejoue tous les votes existants (anterieurs a la fonction, ou perdus si Phoenix
etait arrete) avec la meme logique, lue dans le meme fichier. Le filtre
`phoenix_tracing.py` derive ses identifiants de span par hachage, sans etat partage :
le meme quadruplet (projet, utilisateur, chat, message) redonne toujours le meme span.
`identifier` rend l'envoi idempotent : Phoenix met a jour l'annotation existante.
"""

import importlib.util
import sys
import tomllib
from pathlib import Path

from vivia.configure import ROOT, OpenWebUI

# La fonction tourne dans Open WebUI, hors de ce package : on charge son fichier pour
# n'avoir qu'une seule definition du calcul de span et du format d'annotation.
_spec = importlib.util.spec_from_file_location(
    "phoenix_feedback", ROOT / "openwebui" / "functions" / "phoenix_feedback.py"
)
feedback_function = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feedback_function)
NAMESPACE = feedback_function.NAMESPACE
span_id = feedback_function.span_id
annotation = feedback_function.annotation


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "vivia.toml"
    cfg = tomllib.loads(path.read_text())
    # Le nom du projet vient des valves du filtre : une seule source de verite.
    valves = next(
        (f.get("valves") or {} for f in cfg.get("functions", []) if f["id"] == "phoenix_tracing"),
        {},
    )
    project = valves.get("project_name", "open-webui")
    # L'URL des valves (`http://phoenix:6006`) adresse le reseau Docker ; ce
    # script tourne sur l'hote, d'ou une entree de configuration distincte.
    phoenix = (cfg.get("phoenix", {}).get("url") or "http://127.0.0.1:6006").rstrip("/")

    api = OpenWebUI(cfg["openwebui"]["url"], cfg["admin"])
    feedbacks = api.call("GET", "/api/v1/evaluations/feedbacks/all/export")
    print(f"> {len(feedbacks)} feedback(s), projet {project}")

    payload = [a for f in feedbacks if (a := annotation(f, project))]
    skipped = len(feedbacks) - len(payload)
    if skipped:
        print(f"  {skipped} ignore(s) : sans vote ou sans chat/message")
    if not payload:
        print("done")
        return

    missing = 0
    for item in payload:
        status = feedback_function.post(phoenix, item)
        label = f"{item['result']['label']:>4} -> span {item['span_id']}"
        if status == 404:
            missing += 1
            print(f"  {label} : absent de Phoenix, ignore")
        elif 200 <= status < 300:
            print(f"  {label}")
        else:
            print(f"  ! POST /v1/span_annotations -> HTTP {status}")
            raise SystemExit(1)
    print(f"done ({len(payload) - missing} annotation(s), {missing} span(s) introuvable(s))")


if __name__ == "__main__":
    main()
