"""Tout le SQL des outils d'exploration. Les binds `:nom` sont poses par le tool ; les
`{...}` (identifiants deja valides, fragments controles) sont substitues par `.format()`.
"""

CHECK_GRAIN_NUM_ROWS = "SELECT num_rows FROM all_tables WHERE owner = :o AND table_name = :t"

CHECK_GRAIN_COUNTS = "SELECT COUNT(*), COUNT(DISTINCT {keys}) FROM {obj} {where}"

CHECK_GRAIN_DUPLICATES = (
    "SELECT {keys}, COUNT(*) occurrences FROM {obj} {where} "
    "GROUP BY {keys} HAVING COUNT(*) > 1 FETCH FIRST 5 ROWS ONLY"
)

COLUMN_STATS_LIVE = "SELECT {selects} FROM {obj} WHERE {filtre}"

COMPILE_SQL_PROBE = "SELECT * FROM (\n{sql}\n) WHERE 1 = 0 FETCH FIRST 0 ROWS ONLY"

DESCRIBE_TABLE_COLUMNS = """
    SELECT c.column_name, c.data_type, c.nullable, m.comments
    FROM all_tab_columns c
    LEFT JOIN all_col_comments m
      ON m.owner = c.owner AND m.table_name = c.table_name AND m.column_name = c.column_name
    WHERE c.owner = :owner AND c.table_name = :name
    ORDER BY c.column_id
"""

DESCRIBE_TABLE_PK = """
    SELECT acc.column_name
    FROM all_constraints ac JOIN all_cons_columns acc
      ON acc.owner = ac.owner AND acc.constraint_name = ac.constraint_name
    WHERE ac.owner = :owner AND ac.table_name = :name AND ac.constraint_type = 'P'
    ORDER BY acc.position
"""

DESCRIBE_TABLE_UNIQUE_INDEXES = """
    SELECT ai.index_name, aic.column_name
    FROM all_indexes ai JOIN all_ind_columns aic
      ON aic.index_owner = ai.owner AND aic.index_name = ai.index_name
    WHERE ai.owner = :owner AND ai.table_name = :name AND ai.uniqueness = 'UNIQUE'
    ORDER BY ai.index_name, aic.column_position
"""

DESCRIBE_TABLE_VOLUMETRY = (
    "SELECT partitioned, num_rows, last_analyzed FROM all_tables "
    "WHERE owner = :owner AND table_name = :name"
)

DESCRIBE_TABLE_PARTITION_KIND = (
    "SELECT partitioning_type FROM all_part_tables WHERE owner = :owner AND table_name = :name"
)

DESCRIBE_TABLE_VIEW_TEXT = "SELECT text FROM all_views WHERE owner = :owner AND view_name = :name"

FIND_USAGES_DEPENDENCIES = (
    "SELECT owner, name, type FROM all_dependencies "
    "WHERE referenced_owner = :owner AND referenced_name = :name FETCH FIRST :lim ROWS ONLY"
)

FIND_USAGES_SOURCE = (
    "SELECT owner, name, type, line FROM all_source WHERE UPPER(text) LIKE :needle "
    "FETCH FIRST :lim ROWS ONLY"
)

GET_SOURCE = (
    "SELECT line, text FROM all_source WHERE owner = :owner AND name = :name "
    "AND line BETWEEN :lo AND :hi ORDER BY line"
)

RUN_SELECT_CAPPED = "SELECT * FROM (\n{sql}\n) FETCH FIRST {max_rows} ROWS ONLY"

SEARCH_OBJECTS = """
    SELECT owner, object_name, object_type, comments FROM (
      SELECT t.owner, t.table_name object_name, 'TABLE' object_type, c.comments
      FROM all_tables t LEFT JOIN all_tab_comments c
        ON c.owner = t.owner AND c.table_name = t.table_name
      WHERE t.table_name LIKE :needle {filter_t}
      UNION
      SELECT v.owner, v.view_name, 'VIEW', c.comments
      FROM all_views v LEFT JOIN all_tab_comments c
        ON c.owner = v.owner AND c.table_name = v.view_name
      WHERE v.view_name LIKE :needle {filter_v}
      UNION
      SELECT DISTINCT t.owner, t.table_name, 'TABLE (commentaire)', c.comments
      FROM all_col_comments c JOIN all_tables t
        ON t.owner = c.owner AND t.table_name = c.table_name
      WHERE c.comments LIKE :needle {filter_t}
    )
    ORDER BY owner, object_name
"""
