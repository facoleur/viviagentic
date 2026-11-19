"""Requetes du framework ETL et du dictionnaire. Seul fichier a adapter si les noms de la prod
different (vues V_* exposees dans chaque schema *INT).
"""

ZONES = ("SDA", "SDE", "DMD")


def _all_zones(view: str, columns: str) -> str:
    return " UNION ALL ".join(f"SELECT {columns} FROM {zone}INT.{view}" for zone in ZONES)


# Qui lit quoi : une ligne par (flux, table cible, table source).
TRAC = _all_zones("V_TRAC_DATA", "chaine, flux, table_cible, table_source")

# Frequence de chargement par flux.
FLOWS = _all_zones("V_M_FLOWDATA", "chain_name, flow_name, load_frequency")

# Toutes les operations des flux qui ecrivent dans :t (tables intermediaires comprises).
OPERATIONS = f"""
    WITH ops AS ({_all_zones("V_M_OPERATION", "chaine, flux, operation_nr, table_cible, sql_text")})
    SELECT chaine, flux, operation_nr, table_cible, sql_text FROM ops
    WHERE (chaine, flux) IN (SELECT chaine, flux FROM ops WHERE table_cible = :t)
    ORDER BY chaine, flux, operation_nr
"""

# Vue -> table qu'elle expose (les flux lisent souvent SDEINT.V_X plutot que SDETRG.X).
VIEWS = """
    SELECT owner || '.' || name, referenced_owner || '.' || referenced_name
    FROM all_dependencies WHERE type = 'VIEW' AND referenced_type = 'TABLE'
"""

TABLE_COMMENT = "SELECT comments FROM all_tab_comments WHERE owner = :owner AND table_name = :name"

COLUMNS = """
    SELECT c.column_name, c.data_type, m.comments
    FROM all_tab_columns c
    LEFT JOIN all_col_comments m
      ON m.owner = c.owner AND m.table_name = c.table_name AND m.column_name = c.column_name
    WHERE c.owner = :owner AND c.table_name = :name
    ORDER BY c.column_id
"""

PK = """
    SELECT acc.column_name
    FROM all_constraints ac JOIN all_cons_columns acc
      ON acc.owner = ac.owner AND acc.constraint_name = ac.constraint_name
    WHERE ac.owner = :owner AND ac.table_name = :name AND ac.constraint_type = 'P'
    ORDER BY acc.position
"""

# {stats} : COUNT(col), APPROX_COUNT_DISTINCT(col) par colonne ; {source} : table ou echantillon.
PROFILE = "SELECT COUNT(*), {stats} FROM (SELECT * FROM {source} FETCH FIRST 100000 ROWS ONLY)"

EXAMPLES = "SELECT * FROM {table} FETCH FIRST 5 ROWS ONLY"
