"""Skills : chaque fichier Markdown d'un dossier devient un skill Open WebUI.

Open WebUI 0.10 ne gere qu'un contenu par skill (pas de fichiers annexes) : `SKILL.md` et
chaque `references/*.md` sont donc des skills distincts, nommes par leur frontmatter
(`name`, `description`). Attaches a un modele (`meta.skillIds`), ils apparaissent dans
<available_skills> et le modele charge celui qu'il lui faut avec l'outil integre `view_skill`.
"""

from pathlib import Path

from vivia.configure.client import ROOT, OpenWebUI

PUBLIC_READ = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def read_skill(path: Path) -> dict:
    """Frontmatter `cle: valeur` entre deux `---`, puis le corps Markdown."""
    text = path.read_text()
    head, sep, body = text.removeprefix("---\n").partition("\n---\n")
    if not text.startswith("---\n") or not sep:
        raise ValueError(f"{path}: frontmatter --- name/description --- manquant")
    meta = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    return {
        "id": meta["name"],
        "name": meta["name"],
        "description": meta.get("description", ""),
        "content": body.strip() + "\n",
    }


def skill_files(folder: Path) -> list[Path]:
    """SKILL.md d'abord, puis les autres .md du dossier et de ses sous-dossiers."""
    return sorted(folder.rglob("*.md"), key=lambda p: (p.name != "SKILL.md", p))


def sync_skills(api: OpenWebUI, entries: list[dict]) -> None:
    for entry in entries:
        grants = PUBLIC_READ if entry.get("public", False) else []
        for path in skill_files(ROOT / entry["path"]):
            skill = read_skill(path)
            payload = skill | {"meta": {"tags": []}, "is_active": True, "access_grants": grants}
            current = api.get(f"/api/v1/skills/id/{skill['id']}")
            endpoint = (
                f"/api/v1/skills/id/{skill['id']}/update"
                if current is not None
                else "/api/v1/skills/create"
            )
            api.try_call("POST", endpoint, payload)
            print(f"  skill {skill['id']} ({len(skill['content'].split())} mots)")
