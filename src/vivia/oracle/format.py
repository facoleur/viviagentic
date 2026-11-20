"""Mise en forme Markdown commune aux outils d'exploration (reponse compacte, 2000 tokens max).

Seul module a produire du texte affiche : les tools n'assemblent pas de Markdown eux-memes.
"""

import oracledb

from vivia.oracle import glossary
from vivia.oracle.profile import MAX_ROWS, SENTINELS

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


_TIMEOUT = "Delai depasse : restreindre la requete (filtre, moins de colonnes ou de lignes)."
_HINTS = {  # conseil par erreur Oracle : ce que l'agent peut essayer ensuite
    "ORA-00942": "Table ou vue inexistante ou non accessible : verifier le nom (search_objects).",
    "ORA-00904": "Colonne ou nom invalide : lister les colonnes avec describe_table.",
    "ORA-01031": "Droits insuffisants sur cet objet.",
    "ORA-01013": _TIMEOUT,
    "DPY-4024": _TIMEOUT,
    "DPY-6005": "Connexion a la base impossible : prevenir l'administrateur.",
}


def oracle_error(err: oracledb.Error) -> str:
    """Erreur Oracle : code, message, et un conseil quand on en connait un."""
    error = err.args[0] if err.args else None
    code = getattr(error, "full_code", None) or type(err).__name__
    message = " ".join(str(getattr(error, "message", err)).split())
    return " ".join(filter(None, [f"Erreur Oracle {code} : {message}", _HINTS.get(code)]))


def internal_error(tool: str, err: Exception) -> str:
    return (
        f"Erreur interne dans {tool} ({type(err).__name__} : {err}). "
        "Reformuler la demande ; si elle persiste, prevenir l'administrateur."
    )


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


def _n(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def volume_text(profile: dict) -> str:
    """Nombre total de lignes, puis ce sur quoi le profil est calcule."""
    total = _n(profile["total"])
    count = {
        "exact": total,
        "estime": f"~{total} (estimation)",
        "minimum": f"au moins {total}",
    }[profile["total_kind"]]
    if profile["sampled"]:
        scope = f"un echantillon aleatoire de {_n(profile['rows'])} lignes"
    elif profile["rows"] >= MAX_ROWS:
        scope = f"les {_n(profile['rows'])} premieres lignes (non aleatoire)"
    else:
        scope = "toutes les lignes"
    return f"Lignes : {count}. Profil (apres le signe |) calcule sur {scope}."


def _pct(share: float) -> str:
    return "<1 %" if 0 < share < 0.005 else f"{share:.0%}".replace("%", " %")


def _short(value) -> str:
    return str(value)[:10] if hasattr(value, "year") else str(value)[:24]


def profile_text(s: dict, rows: int) -> str:
    """Une colonne profilee en une ligne : nulls, valeurs, bornes, signalements."""
    if s["non_null"] == 0:
        return "vide (100 % null)"
    parts = [f"{_pct(1 - s['non_null'] / rows)} null"]
    if s["distinct"] == 1 and s["non_null"] == rows:
        return f"constante : {_short(s['min'])}"
    if s["values"]:
        top = ", ".join(
            f"{_short(v)}{' (sentinelle)' if str(v).upper() in SENTINELS else ''} {_pct(n / rows)}"
            for v, n in s["values"]
        )
        parts.append(f"{s['distinct']} valeurs : {top}")
    else:
        unique = s["non_null"] == rows and s["distinct"] >= 0.99 * rows and rows >= 20
        parts.append("unique sur l'echantillon" if unique else f"~{s['distinct']} valeurs")
    if s["kind"] != "text":
        parts.append(f"min {_short(s['min'])}, max {_short(s['max'])}")
    if s["kind"] == "num" and s["x"]:
        parts.append(f"{_pct(s['x'] / rows)} negatifs")
    if s["kind"] == "date" and s["x"]:
        parts.append(f"{_pct(s['x'] / rows)} a {_short(s['max'])} (sentinelle)")
    if s["kind"] == "date" and s["y"]:
        parts.append(f"{_pct(s['y'] / rows)} <= 1900-01-01 (sentinelle)")
    return ", ".join(parts)


def describe_table_report(
    obj, cols, pk, uniques, part, partition_kind, view_text, profile=None
) -> str:
    """`profile` : le dict de `oracle.profile.profile`, ou un texte qui dit pourquoi il manque."""
    lines = [f"## {obj}", "", f"Zone/type : {glossary.zone_type(obj.schema)}", "", "### Colonnes"]
    if isinstance(profile, dict):
        lines.append(volume_text(profile))
    elif profile:
        lines.append(profile)
    for c, t, n, m in cols:
        line = f"- `{c}` {t}{' NULL' if n == 'Y' else ' NOT NULL'}{f' — {m}' if m else ''}"
        if isinstance(profile, dict) and profile["rows"] and c in profile["columns"]:
            line += f" | {profile_text(profile['columns'][c], profile['rows'])}"
        lines.append(line)
    if pk:
        lines += ["", "### Cle primaire", ", ".join(c for (c,) in pk)]
    if uniques:
        groups: dict[str, list[str]] = {}
        for idx, col in uniques:
            groups.setdefault(idx, []).append(col)
        lines += ["", "### Index uniques"]
        lines += [f"- `{idx}` ({', '.join(cs)})" for idx, cs in groups.items()]
    if view_text:
        lines += ["", "### Vue (ce qu'elle lit)", f"```sql\n{view_text}\n```"]
    elif part and part[0][0] == "YES":
        lines += ["", "### Partitionnement", partition_kind]
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


def dependencies_report(table: str, rows: list[tuple]) -> str:
    if not rows:
        return f"Aucune source declaree dans V_M_TRAC_DATA pour {table}."
    return "\n".join([f"## Sources de {table}", *(f"- `{name}` ({zone})" for zone, name in rows)])


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
    for *head, sql in rows[:limit]:
        lines.append(f"- {_operation_title(*head)}")
        lines_sql = enumerate((sql or "").splitlines(), 1)
        hits = [(i, ln) for i, ln in lines_sql if texte.upper() in ln.upper()]
        lines += [f"  - l.{i} : `{ln.strip()[:160]}`" for i, ln in hits[:3]]
        if len(hits) > 3:
            lines.append(f"  - ... {len(hits) - 3} autres lignes")
    if len(rows) > limit:
        lines.append(f"\n(plus de {limit} operations : affiner `texte`)")
    return truncate("\n".join(lines))


def list_operations_report(chaine: str, flux: str | None, rows: list[tuple], limit: int) -> str:
    if not rows:
        return f"Aucune operation pour {chaine}{f'.{flux}' if flux else ''}."
    columns = ["chaine", "flux", "op", "description", "table cible", "lignes SQL"]
    return markdown_table(columns, rows, limit)
