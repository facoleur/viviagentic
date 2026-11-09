"""Sections de configuration `[api."<chemin>"]`."""

from vivia.configure.client import OpenWebUI, deep_merge


def sync_api(api: OpenWebUI, sections: dict[str, dict]) -> None:
    """Patch declaratif : l'etat courant est relu, fusionne, puis repousse entier.

    Ces endpoints exigent le formulaire complet (un champ absent => 422), d'ou
    la relecture ; le chemin de lecture est le chemin d'ecriture sans `/update`.
    """
    for path, patch in sections.items():
        current = api.get(f"/api/v1/{path.removesuffix('/update')}") or {}
        api.try_call("POST", f"/api/v1/{path}", deep_merge(current, patch))
        print(f"  {path}")
