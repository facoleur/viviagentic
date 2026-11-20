"""Requetes propres a la retro-doc. Vues du framework en (vue, colonnes) : leurs schemas sont
decouverts par `vivia.tools.explore.framework.union`.
"""

# Qui lit quoi : une ligne par (flux, table cible, table source).
TRAC = ("V_M_TRAC_DATA", "chaine, flux, table_cible, table_source")

# Frequence de chargement par flux.
FLOWS = ("V_M_FLOWDATA", "chain_name, flow_name, load_frequency")

OPS = (
    "V_M_OPERATION",
    "chain_name, flow_name, operation_nr, target_table, operation, validity_end_date",
)

# Toutes les operations des flux qui ecrivent dans :t (tables intermediaires comprises).
OPERATIONS = """
    WITH ops AS (SELECT * FROM ({source}) WHERE validity_end_date > SYSDATE)
    SELECT chain_name, flow_name, operation_nr, target_table, operation FROM ops
    WHERE (chain_name, flow_name) IN (SELECT chain_name, flow_name FROM ops WHERE target_table = :t)
    ORDER BY chain_name, flow_name, operation_nr
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

EXAMPLES = "SELECT * FROM {table} FETCH FIRST 5 ROWS ONLY"
