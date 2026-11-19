"""Mise en forme Markdown commune aux outils d'exploration (reponse compacte, 2000 tokens max).

Seul module a produire du texte affiche : les tools n'assemblent pas de Markdown eux-memes.
"""

import oracledb

from vivia.oracle import glossary

MAX_CHARS = 8000  # ~2000 tokens


def markdown_table(
    columns: list[str], rows: list[tuple], limit: int, total: int | None = None
) -> str:
    """Tableau Markdown borne a `limit` lignes, avec une note explicite si tronque."""
    shown = rows[:limit]
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [head, sep]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in shown]
    text = "\n".join(lines)
    remaining = (total if total is not None else len(rows)) - len(shown)
    if remaining > 0:
        text += f"\n\n… {remaining} ligne(s) de plus, preciser le filtre."
    return text


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n… tronque a {limit} caracteres, preciser la demande."


def oracle_error(err: oracledb.DatabaseError) -> str:
    """Format commun d'un DatabaseError (code + message), sans contexte additionnel."""
    (error,) = err.args
    return f"{error.full_code} : {error.message.strip()}"


# --- run_select --------------------------------------------------------------------------------


def _cell_truncated(value, limit: int = 200):
    text = str(value) if value is not None else None
    return text if text is None or len(text) <= limit else text[:limit] + "…"


def run_select_table(columns: list[str], rows: list[tuple], limit: int) -> str:
    capped = [tuple(_cell_truncated(v) for v in row) for row in rows]
    return markdown_table(columns, capped, limit=limit)


# --- check_grain ---------------------------------------------------------------------------------


def too_many_rows(obj, num_rows: int, limit: int) -> str:
    return (
        f"Erreur : {obj} fait ~{num_rows:,} lignes, un filtre est obligatoire au-dela de {limit:,}."
    )


def check_grain_report(keys: str, total: int, distinct: int, dup_cols=None, dup_rows=None) -> str:
    lines = [f"lignes : {total} — cles distinctes ({keys}) : {distinct}"]
    if total != distinct:
        lines += ["", "### Exemples de doublons", markdown_table(dup_cols, dup_rows, limit=5)]
    return "\n".join(lines)


# --- column_stats --------------------------------------------------------------------------------


def column_stats_live(cols: list[str], columns: list[str], rows: list[tuple]) -> str:
    row = dict(zip(columns, rows[0], strict=True)) if rows else {}
    return "\n".join(
        f"- `{c}` : {row.get(f'{c}_D')} distinctes, {row.get(f'{c}_N')} nulls, "
        f"min={row.get(f'{c}_LO')}, max={row.get(f'{c}_HI')}"
        for c in cols
    )


# --- compile_sql -----------------------------------------------------------------------------


def _locate(sql: str, offset: int) -> tuple[int, int, str]:
    """Ligne et colonne 1-based d'un offset Oracle, avec un extrait de 3 lignes autour."""
    head = sql[:offset]
    line = head.count("\n") + 1
    column = offset - (head.rfind("\n") + 1) + 1
    lines = sql.splitlines()
    extract = "\n".join(lines[max(0, line - 2) : line + 1])
    return line, column, extract


def compile_error(err: oracledb.DatabaseError, resolved_sql: str) -> str:
    (error,) = err.args
    line, column, extract = _locate(resolved_sql, getattr(error, "offset", 0) or 0)
    return (
        f"{error.full_code} a la ligne {line}, colonne {column} :\n{error.message.strip()}\n\n"
        f"```\n{extract}\n```"
    )


def compile_ok(columns: list[tuple[str, str]]) -> str:
    return "OK — colonnes : " + ", ".join(f"{name} ({kind})" for name, kind in columns)


# --- compare_sql -------------------------------------------------------------------------------


def compare_sql_timeout(max_seconds: float, nouveau: bool) -> str:
    cote = "nouveau" if nouveau else "original (M_OPERATION)"
    return (
        f"Depassement de max_seconds={max_seconds:g}s sur le SQL {cote} — pas une erreur de "
        "compilation. Pour iterer vite : filtrer/reduire temporairement le volume dans le SQL "
        "lui-meme. Pour mesurer l'operation reelle : rappeler avec un `max_seconds` plus grand."
    )


def compare_sql_report(
    n_old: int,
    checksum_old: int,
    duree_old: float,
    n_new: int,
    checksum_new: int,
    duree_new: float,
) -> str:
    identique = n_old == n_new and checksum_old == checksum_new
    verdict = "IDENTIQUE" if identique else "DIFFERENT — ne pas deployer, verifier la logique"
    delta = duree_old - duree_new
    pct = (delta / duree_old * 100) if duree_old else 0.0
    return (
        f"Resultat : {verdict}\n"
        f"- original : {n_old} ligne(s), checksum {checksum_old}, {duree_old:.2f}s\n"
        f"- nouveau  : {n_new} ligne(s), checksum {checksum_new}, {duree_new:.2f}s\n"
        f"- gain : {delta:+.2f}s ({pct:+.1f}%)"
    )


# --- describe_table --------------------------------------------------------------------------


def unknown_object(obj) -> str:
    return f"Erreur : {obj} introuvable. Utiliser search_objects pour verifier le nom."


def describe_table_report(obj, cols, pk, uniques, part, partition_kind, view_text) -> str:
    lines = [f"## {obj}", "", f"Zone/type : {glossary.zone_type(obj.schema)}", "", "### Colonnes"]
    lines += [
        f"- `{c}` {t}{' NULL' if n == 'Y' else ' NOT NULL'}{f' — {m}' if m else ''}"
        for c, t, n, m in cols
    ]
    if pk:
        lines += ["", "### Cle primaire", ", ".join(c for (c,) in pk)]
    if uniques:
        groups: dict[str, list[str]] = {}
        for idx, col in uniques:
            groups.setdefault(idx, []).append(col)
        lines += ["", "### Index uniques"]
        lines += [f"- `{idx}` ({', '.join(cs)})" for idx, cs in groups.items()]
    if part:
        partitioned, num_rows, last_analyzed = part[0]
        partitioning = partition_kind if partitioned == "YES" else "aucun"
        lines += [
            "",
            "### Volumetrie",
            f"partitionnement : {partitioning} ; "
            f"num_rows : {num_rows if num_rows is not None else 'non analyse'} ; "
            f"last_analyzed : {last_analyzed or 'jamais'}",
        ]
    elif view_text:
        lines += ["", "### Vue (ce qu'elle lit)", f"```sql\n{view_text}\n```"]
    return "\n".join(lines)


# --- find_usages -----------------------------------------------------------------------------


def find_usages_report(obj, deps, source) -> str:
    lines = [f"## Dependances de {obj}"]
    if deps:
        lines += [f"- `{o}.{n}` ({t})" for o, n, t in deps]
    else:
        lines.append(
            "Aucune trouvee dans ALL_DEPENDENCIES — soit aucun code PL/SQL visible ne le cite, "
            "soit l'acces a cette vue est restreint pour ce compte."
        )
    lines += ["", f"## Code source citant {obj.name}"]
    if source:
        lines += [f"- `{o}.{n}` ({t}), ligne {line}" for o, n, t, line in source]
    else:
        lines.append(
            "Aucune occurrence dans ALL_SOURCE — soit aucun objet PL/SQL ne le cite, soit "
            "l'acces a cette vue est restreint pour ce compte."
        )
    lines += ["", "Operations ELT qui le citent : pas encore disponible (index phase 2)."]
    return "\n".join(lines)


# --- get_source ------------------------------------------------------------------------------


def no_source_lines(obj, lo: int, hi: int) -> str:
    return (
        f"Aucune ligne pour {obj} entre {lo} et {hi} — objet inconnu d'ALL_SOURCE, "
        "deja termine, ou acces restreint pour ce compte."
    )


def source_page(obj, lo: int, hi: int, rows: list[tuple]) -> str:
    body = "".join(text for _, text in rows)
    return f"```sql\n-- {obj}, lignes {lo}-{hi}\n{body}```"


# --- search_objects --------------------------------------------------------------------------


def search_objects_report(texte: str, zone: str | None, rows: list[tuple], limit: int) -> str:
    if not rows:
        return f"Aucun resultat pour « {texte} »" + (f" en zone {zone}" if zone else "")
    lines = [f"- `{o}.{n}` ({t}){f' — {c}' if c else ''}" for o, n, t, c in rows]
    if len(rows) >= limit:
        lines.append(f"\n… limite a {limit} resultats, preciser `zone` ou le texte.")
    return "\n".join(lines)


# --- distinct_values ---------------------------------------------------------------------------


def distinct_values_report(col: str, rows: list[tuple], limit: int) -> str:
    values = ", ".join("NULL" if v is None else str(v) for (v,) in rows)
    text = f"`{col}` : {values}" if rows else f"`{col}` : aucune valeur."
    if len(rows) >= limit:
        text += f" … (limite a {limit}, augmenter `limite` si besoin)"
    return text


# --- get_dependencies ----------------------------------------------------------------------------


def dependency_line(depth, source, bases, chaine, flux, new: bool) -> str:
    table = f" = {', '.join(f'`{b}`' for b in bases)}" if bases != [source] else ""
    seen = "" if new else " — deja remontee plus haut"
    return f"{'  ' * depth}- `{source}`{table} (chaine {chaine}, flux {flux}){seen}"


def dependencies_report(table_cible: str, lines: list[str]) -> str:
    if not lines:
        return f"Aucune dependance declaree dans TRAC_DATA pour {table_cible}."
    return truncate("\n".join([f"## Sources necessaires a {table_cible}", *lines]))


# --- operations --------------------------------------------------------------------------------


def _operation_title(chaine, flux, nr, description, cible) -> str:
    return f"{chaine}.{flux} op {nr} -> `{cible}`" + (f" — {description}" if description else "")


MAX_SQL_CHARS = 200_000


def operations_sql(flux: str, rows: list[tuple]) -> str:
    """SQL complet jusqu'a MAX_SQL_CHARS ; au-dela, refus (flux) ou troncature (operation seule)."""
    if not rows:
        return f"Aucune operation pour le flux {flux}. Utiliser search_operations."
    text = "\n\n".join(
        f"### {_operation_title(*row[:5])}\n```sql\n{row[5] or ''}\n```" for row in rows
    )
    if len(text) <= MAX_SQL_CHARS:
        return text
    if len(rows) > 1:
        sizes = [f"- op {nr} : {len(sql or ''):,} caracteres" for _, _, nr, *_, sql in rows]
        return "\n".join(
            [
                f"SQL du flux {flux} trop long ({len(text):,} caracteres > {MAX_SQL_CHARS:,}) : "
                "rappeler get_operation avec `operation_nr` pour une operation a la fois.",
                *sizes,
            ]
        )
    return (
        f"ATTENTION : SQL tronque a {MAX_SQL_CHARS:,} caracteres sur {len(text):,}. "
        "La fin de l'operation manque.\n\n" + text[:MAX_SQL_CHARS]
    )


def search_operations_report(texte: str, rows: list[tuple], limit: int) -> str:
    if not rows:
        return f"Aucune operation ne contient « {texte} »."
    lines = [f"## Operations contenant « {texte} »"]
    for *head, sql in rows:
        lines.append(f"- {_operation_title(*head)}")
        hits = [(i, ln) for i, ln in enumerate((sql or "").splitlines(), 1)]
        hits = [(i, ln) for i, ln in hits if texte.upper() in ln.upper()]
        lines += [f"  - l.{i} : `{ln.strip()[:160]}`" for i, ln in hits[:3]]
        if len(hits) > 3:
            lines.append(f"  - ... {len(hits) - 3} autres lignes")
    if len(rows) == limit:
        lines.append(f"\n(limite de {limit} atteinte : affiner `texte` ou `chaines`)")
    return truncate("\n".join(lines))


def list_operations_report(chaines: list[str], rows: list[tuple], limit: int) -> str:
    if not rows:
        return f"Aucune operation pour les chaines {', '.join(chaines)}."
    columns = ["chaine", "flux", "op", "description", "table cible", "lignes SQL"]
    return markdown_table(columns, rows, limit)
