"""Retro-doc des tables SDA/SDE : `select` choisit les tables, `run` les documente.

Tout vit dans artifacts/retrodoc/ : selection.json, glossaire.json (a fournir),
facts/ (faits du code), draft/ (texte du LLM), doc/ (JSON final), overrides/ (corrections).
"""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from vivia.configure.client import ROOT
from vivia.retrodoc import collect, llm
from vivia.retrodoc.doc import Redaction, build

STORE = ROOT / "artifacts" / "retrodoc"


def load(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def document(table: str, fw: dict, glossary: dict) -> None:
    """Faits -> texte LLM (reutilise si le SQL et le schema n'ont pas change) -> doc final."""
    facts = collect.facts(table, fw, glossary)
    save(STORE / "facts" / f"{table}.json", facts)
    key = fingerprint(facts)
    draft = load(STORE / "draft" / f"{table}.json", {})
    if draft.get("meta", {}).get("empreinte") != key:
        text = llm.enrich(Redaction, llm.render("system.j2"), llm.render("table.j2", **facts))
        meta = {"empreinte": key, "modele": llm.MODEL, "date": date.today().isoformat()}
        draft = {"meta": meta, "redaction": text.model_dump()}
        save(STORE / "draft" / f"{table}.json", draft)
    override = load(STORE / "overrides" / f"{table}.json", {})
    save(STORE / "doc" / f"{table}.json", build(facts, draft, override))


def fingerprint(facts: dict) -> str:
    """Empreinte de ce qui change le texte : SQL, schema, sources, glossaire (pas les stats)."""
    cols = [(c["nom"], c["type"], c["commentaire"]) for c in facts["colonnes"]]
    stable = facts | {"colonnes": cols, "exemples": None, "echantillon": None}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser(prog="vivia-retrodoc", description=__doc__)
    parser.add_argument("step", choices=["select", "run"])
    parser.add_argument("tables", nargs="*", help="run : SCHEMA.TABLE (defaut : selection.json)")
    parser.add_argument("-n", type=int, default=200, help="select : nombre de tables")
    parser.add_argument("-j", type=int, default=1, help="run : tables traitees en parallele")
    args = parser.parse_args()

    fw = collect.framework()
    if args.step == "select":
        save(STORE / "selection.json", collect.strategic(fw, args.n))
        return

    glossary = load(STORE / "glossaire.json", {})
    tables = [t.upper() for t in args.tables] or list(load(STORE / "selection.json", {}))

    def run(table: str) -> str:
        try:
            document(table, fw, glossary)
            return "ok"
        except Exception as err:
            return f"ERREUR {type(err).__name__}: {err}"

    with ThreadPoolExecutor(args.j) as pool:
        for table, status in zip(tables, pool.map(run, tables), strict=True):
            print(f"{table}: {status}")


if __name__ == "__main__":
    main()
