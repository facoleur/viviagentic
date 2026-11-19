"""Requetes propres a la retro-doc. Les vues du framework et le dictionnaire commun sont dans
`vivia.tools.explore.queries`, partages avec les outils.
"""

from vivia.tools.explore.queries import all_zones as _all_zones

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

TABLE_COMMENT = "SELECT comments FROM all_tab_comments WHERE owner = :owner AND table_name = :name"

COLUMNS = """
    SELECT c.column_name, c.data_type, m.comments
    FROM all_tab_columns c
    LEFT JOIN all_col_comments m
      ON m.owner = c.owner AND m.table_name = c.table_name AND m.column_name = c.column_name
    WHERE c.owner = :owner AND c.table_name = :name
    ORDER BY c.column_id
"""

# {stats} : COUNT(col), APPROX_COUNT_DISTINCT(col) par colonne ; {source} : table ou echantillon.
PROFILE = "SELECT COUNT(*), {stats} FROM (SELECT * FROM {source} FETCH FIRST 100000 ROWS ONLY)"

EXAMPLES = "SELECT * FROM {table} FETCH FIRST 5 ROWS ONLY"
