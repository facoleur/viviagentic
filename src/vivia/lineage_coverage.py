"""Couverture du lignage colonne sur toutes les operations ELT (lecture seule).

Pour chaque operation de V_M_OPERATION : analyse avec le dictionnaire ALL_TAB_COLUMNS (qui
developpe les `*`), temps, colonnes cibles rattachees a une source, tables hors dictionnaire,
ecart avec V_M_TRAC_DATA. Une ligne JSON par operation dans artifacts/lineage_coverage/, puis
un resume : de quoi decider si le lignage colonne est assez fiable pour construire le graphe.
"""

import argparse
import json
import re
import signal
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager

from sqlglot import exp
from sqlglot.schema import ensure_schema

from lineage import lineage
from vivia.configure.client import ROOT
from vivia.oracle import client
from vivia.tools.explore import framework, queries
from vivia.tools.explore.operations import fetch_operations, in_list

OUT = ROOT / "artifacts" / "lineage_coverage"
ALL = 10_000_000
LOAD_SECONDS = 600
# SQL qu'on ne sait pas analyser : a signaler, jamais a ignorer en silence.
UNSUPPORTED = {
    "plsql": re.compile(r"^\s*(BEGIN|DECLARE)\b|EXECUTE\s+IMMEDIATE", re.I),
    "with_function": re.compile(r"\bWITH\s+(FUNCTION|PROCEDURE)\b", re.I),
    "insert_all": re.compile(r"^\s*INSERT\s+(ALL|FIRST)\b", re.I),
}
NOISE = {"DUAL", "ROWNUM", "LEVEL", "ROWID", "SYSDATE"}  # lus par le SQL, jamais dans TRAC_DATA
_state: dict = {}


class Timeout(Exception):
    pass


@contextmanager
def time_limit(seconds: float):
    """Interrompt l'analyse au bout de `seconds` (Unix ; sans delai ailleurs)."""
    if not hasattr(signal, "setitimer"):
        yield
        return

    def stop(*_):
        raise Timeout

    previous = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def init(columns: dict, trac: dict[str, set[str]]) -> None:
    """Etat d'un process : dictionnaire {schema: {table: {colonne: type}}} et TRAC_DATA."""
    sys.setrecursionlimit(5000)  # les CTE tres imbriquees depassent la limite par defaut
    owners: dict[str, list[str]] = {}
    for owner, tables in columns.items():
        for table in tables:
            owners.setdefault(table, []).append(owner)
    _state.update(schema=ensure_schema(columns, dialect="oracle"), owners=owners, trac=trac)


def target_of(cible: str | None) -> str:
    """SCHEMA.TABLE de la cible : tel quel si qualifie, sinon l'unique schema qui la porte
    (de preference *TRG). Vide si l'operation n'a pas de table cible."""
    name = (cible or "").strip().upper()
    if not name or "." in name:
        return name
    owners = _state["owners"].get(name, [])
    owners = [o for o in owners if o.endswith("TRG")] or owners
    return f"{owners[0]}.{name}" if len(owners) == 1 else name


def trac_name(table: str) -> str:
    """Nom TRAC_DATA d'une table lue : sans schema, ni prefixe V_ de vue, ni suffixe $..."""
    bare = table.rsplit(".", 1)[-1].upper()
    return re.sub(r"\$.*", "", bare.removeprefix("V_"))


def short_error(err: Exception) -> str:
    """Nom et description de l'erreur, sans coordonnees ni repr de token : regroupable."""
    errors = getattr(err, "errors", None)
    text = errors[0]["description"] if errors else str(err)
    text = re.sub(r"<Token token_type: TokenType\.(\w+).*?>", r"<\1>", text)
    return f"{type(err).__name__}: {' '.join(text.split())}"[:160]


def error_context(err: Exception) -> str | None:
    """SQL autour de l'erreur d'analyse, sur une ligne, l'endroit fautif entre « »."""
    errors = getattr(err, "errors", None)
    if not errors:
        return None
    e = errors[0]
    text = f"{e['start_context'][-70:]}«{e['highlight']}»{e['end_context'][:40]}"
    return " ".join(text.split())


def op_id(op: tuple) -> str:
    return f"{op[0]}.{op[1]}.{op[2]}"


def analyze(job: tuple) -> dict:
    """Une operation -> une ligne de rapport. Ne leve jamais : tout echec devient un statut."""
    try:
        return _analyze(job)
    except Exception as err:
        return {"op": op_id(job[0]), "cible": job[0][4], "statut": "erreur",
                "message": short_error(err)}  # fmt: skip


def _analyze(job: tuple) -> dict:
    op, limit = job
    cible, sql = op[4], op[5] or ""
    out = {"op": op_id(op), "cible": cible, "lignes": sql.count("\n") + 1}
    if kind := next((k for k, rx in UNSUPPORTED.items() if rx.search(sql)), None):
        return out | {"statut": f"non_analysable:{kind}"}
    target = target_of(cible) or None  # sans cible : seuls les INSERT/MERGE nomment leur table
    start = time.perf_counter()
    try:
        with time_limit(limit):
            edges = lineage(sql, columns=True, schema=_state["schema"], target=target)
    except Timeout:
        return out | {"statut": "timeout", "secondes": limit}
    except Exception as err:
        return out | {
            "statut": "erreur",
            "message": short_error(err),
            "contexte": error_context(err),
            "secondes": _since(start),
        }

    # Par nom de colonne : l'INSERT peut nommer sa table sans schema alors que la cible est
    # resolue avec (INSERT INTO T vs SDETRG.T), les noms de table ne se comparent donc pas.
    sources: dict[str, set[str]] = {}
    for e in edges:
        sources.setdefault(e["target"].rsplit(".", 1)[-1], set()).add(e["source"])
    names = []
    if target:
        names = _state["schema"].column_names(exp.to_table(target, dialect="oracle"))
    wanted = names or list(sources)
    star = [c for c in wanted if any(s.endswith(".*") for s in sources.get(c, ()))]
    none = [c for c in wanted if c not in sources]
    dl = [c for c in wanted if c.startswith("DL_")]
    tables = {s.rsplit(".", 1)[0] for srcs in sources.values() for s in srcs}
    unknown = sorted(
        t for t in tables if t.rsplit(".", 1)[-1] not in _state["owners"] and t.upper() not in NOISE
    )
    declared = _state["trac"].get(trac_name(cible), set()) if cible else set()
    used = {trac_name(t) for t in tables if not t.split(".")[0].endswith("STG")}
    return out | {
        "statut": "ok" if edges else ("vide" if target else "sans_cible"),
        "secondes": _since(start),
        "colonnes": len(wanted),
        "exactes": len(wanted) - len(star) - len(none),
        "etoile": len(star),
        "sans_source": len(none),
        "dl": len(dl),  # colonnes techniques de chargement (DL_), souvent des constantes
        "dl_avec_source": len([c for c in dl if c not in none and c not in star]),
        "inconnues": unknown,
        "hors_trac": sorted(used - declared - NOISE) if declared else None,
    }


def _since(start: float) -> float:
    return round(time.perf_counter() - start, 2)


def summarize(rows: list[dict]) -> str:
    n = len(rows)
    count = Counter(r["statut"].split(":")[0] for r in rows)
    lines = [f"{n} operations"] + [f"  {k:15} {v:6}  {v / n:4.0%}" for k, v in count.most_common()]
    unsupported = Counter(r["statut"] for r in rows if r["statut"].startswith("non_analysable"))
    lines += [f"    {k} : {v}" for k, v in unsupported.most_common()]

    ok = [r for r in rows if r["statut"] in ("ok", "vide")]
    total = sum(r["colonnes"] for r in ok) or 1
    lines += ["", f"Colonnes cibles des operations analysees : {total}"]
    for key, label in (("exactes", "avec source"), ("etoile", "derriere un * non developpe"),
                       ("sans_source", "sans source (constante ou echec)")):  # fmt: skip
        part = sum(r[key] for r in ok)
        lines.append(f"  {label:36} {part:7}  {part / total:4.0%}")
    dl = sum(r.get("dl", 0) for r in ok)
    metier, metier_ok = total - dl, sum(r["exactes"] - r.get("dl_avec_source", 0) for r in ok)
    lines.append(f"  dont colonnes DL_ (chargement) : {dl} ; hors DL_ : {metier_ok}/{metier} "
                 f"avec source ({metier_ok / max(metier, 1):.0%})")  # fmt: skip
    full = sum(1 for r in ok if r["colonnes"] and r["exactes"] == r["colonnes"])
    lines.append(f"  operations dont toutes les colonnes ont une source : {full}/{len(ok)}")

    times = sorted(r["secondes"] for r in rows if "secondes" in r)
    if times:
        p95 = times[int(len(times) * 0.95) - 1]
        lines += ["", f"Temps par operation : mediane {statistics.median(times)} s, "
                  f"p95 {p95} s, max {times[-1]} s"]  # fmt: skip
    slow = sorted((r for r in rows if "secondes" in r), key=lambda r: -r["secondes"])[:5]
    lines += [f"  {r['secondes']:>7} s  {r['lignes']:>5} lignes  {r['op']}" for r in slow]

    failed = [r for r in rows if r["statut"] == "erreur"]
    errors = Counter(r["message"] for r in failed)
    example = {r["message"]: r.get("contexte") for r in failed if r.get("contexte")}
    lines += ["", "Erreurs les plus frequentes (avec un extrait du SQL) :"]
    for message, count in errors.most_common(8):
        lines.append(f"  {count:4} x {message}")
        if message in example:
            lines.append(f"         ex. {example[message]}")
    unknown = Counter(t for r in ok for t in r["inconnues"])
    lines += ["", "Tables lues absentes du dictionnaire :"]
    lines += [f"  {v:4} x {k}" for k, v in unknown.most_common(10)]

    checked = [r for r in ok if r["hors_trac"] is not None]
    clean = sum(1 for r in checked if not r["hors_trac"])
    lines += ["", f"Sources lues absentes de V_M_TRAC_DATA : {len(checked) - clean} operations "
              f"sur {len(checked)} verifiees"]  # fmt: skip
    lines += [f"  {r['op']} : {', '.join(r['hors_trac'][:6])}" for r in checked if r["hors_trac"]][
        :10
    ]
    return "\n".join(lines)


def load(cibles: list[str], limit: int | None) -> tuple[list[tuple], dict, dict]:
    """Operations, dictionnaire et TRAC_DATA, lus en base."""
    where, params = [], {}
    if cibles:
        where.append(in_list("table_cible", cibles, params))
    ops = fetch_operations(where, params, max_rows=limit or ALL, max_seconds=LOAD_SECONDS)
    columns: dict = {}
    _, rows = client.fetch(queries.DICTIONARY_COLUMNS, max_rows=ALL, max_seconds=LOAD_SECONDS)
    for owner, table, column, data_type in rows:
        columns.setdefault(owner, {}).setdefault(table, {})[column] = data_type
    sql = queries.TRAC_DATA_ALL.format(
        source=framework.union(framework.TRAC_DATA, "source_name, target_name")
    )
    trac: dict[str, set[str]] = {}
    for target, source in client.fetch(sql, max_rows=ALL, max_seconds=LOAD_SECONDS)[1]:
        trac.setdefault(target.upper(), set()).add(source.upper())
    return ops, columns, trac


def main() -> None:
    parser = argparse.ArgumentParser(prog="vivia-lineage-coverage", description=__doc__)
    parser.add_argument(
        "cibles", nargs="*", help="seulement les operations qui ecrivent ces tables"
    )
    parser.add_argument("-n", type=int, help="nombre maximal d'operations")
    parser.add_argument("-j", type=int, default=4, help="processus en parallele")
    parser.add_argument("-t", "--timeout", type=int, default=60, help="secondes par operation")
    parser.add_argument(
        "--resume", action="store_true", help="reprend report.jsonl : refait seulement les erreurs"
    )
    args = parser.parse_args()

    ops, columns, trac = load([c.upper() for c in args.cibles], args.n)
    print(f"{len(ops)} operations, {sum(map(len, columns.values()))} tables au dictionnaire")
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / "report.jsonl"
    kept = (
        [json.loads(x) for x in report.read_text().splitlines()]
        if args.resume and report.exists()
        else []
    )
    rows = [
        r for r in kept if r["statut"] != "erreur"
    ]  # les erreurs sont refaites : le code change
    done = {r["op"] for r in rows}
    jobs = [(op, args.timeout) for op in ops if op_id(op) not in done]
    print(f"{len(jobs)} a analyser, {len(done)} deja faites", file=sys.stderr)
    pool = ProcessPoolExecutor(args.j, initializer=init, initargs=(columns, trac))
    with report.open("w") as out, pool:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
        for i, row in enumerate(pool.map(analyze, jobs, chunksize=1), 1):
            rows.append(row)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()  # rien n'est perdu si le script s'arrete : --resume reprend
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}", file=sys.stderr)
    summary = summarize(rows)
    (OUT / "summary.txt").write_text(summary + "\n")
    print(summary)


if __name__ == "__main__":
    main()
