from lineage import lineage, to_mermaid

SQL = """
INSERT INTO #SCH#.FACT_SALES (id, amount)
WITH c AS (SELECT * FROM #SCH#_STG.ORDERS o JOIN ref.customers cu ON o.cid = cu.id)
SELECT c.id, NVL(c.amount, 0) FROM c WHERE c.dt = TO_DATE('#DATE#', 'YYYYMMDD');

MERGE INTO dwh.dim_client d USING (SELECT * FROM stg_#ENV#.client) s ON (d.id = s.id)
WHEN MATCHED THEN UPDATE SET d.nom = s.nom
WHEN NOT MATCHED THEN INSERT (id, nom) VALUES (s.id, s.nom);

CREATE TABLE tmp_x AS SELECT a.* FROM dwh.dim_client a, #SCH#.FACT_SALES b WHERE a.id = b.id(+);

UPDATE dwh.dim_client d SET flag = 1 WHERE EXISTS (SELECT 1 FROM tmp_x t WHERE t.id = d.id);

SELECT * FROM dual;
"""


def test_lineage_tables():
    assert {(e["source"], e["target"]) for e in lineage(SQL)} == {
        ("#SCH#_STG.ORDERS", "#SCH#.FACT_SALES"),
        ("REF.CUSTOMERS", "#SCH#.FACT_SALES"),
        ("STG_#ENV#.CLIENT", "DWH.DIM_CLIENT"),
        ("DWH.DIM_CLIENT", "TMP_X"),
        ("#SCH#.FACT_SALES", "TMP_X"),
        ("TMP_X", "DWH.DIM_CLIENT"),
    }


COLUMNS_SQL = """
INSERT INTO #SCH#.FACT_SALES (id, amount)
WITH c AS (SELECT o.id, o.amount + cu.bonus AS total FROM #SCH#_STG.ORDERS o JOIN ref.cust cu
           ON o.cid = cu.id)
SELECT c.id, NVL(c.total, 0) FROM c UNION ALL SELECT h.id, h.amount FROM hist.sales h;

MERGE INTO dwh.client d USING (SELECT id, nom FROM stg_#ENV#.client) s ON (d.id = s.id)
WHEN MATCHED THEN UPDATE SET d.nom = s.nom
WHEN NOT MATCHED THEN INSERT (id, nom) VALUES (s.id, s.nom);

UPDATE dwh.client d SET flag = 1, ca = (SELECT SUM(f.amount) FROM #SCH#.FACT_SALES f
                                         WHERE f.id = d.id);

CREATE TABLE tmp_x AS SELECT a.id, b.amount mt FROM dwh.client a, #SCH#.FACT_SALES b;
"""


def test_lineage_columns():
    assert {(e["source"], e["target"]) for e in lineage(COLUMNS_SQL, columns=True)} == {
        ("#SCH#_STG.ORDERS.ID", "#SCH#.FACT_SALES.ID"),
        ("HIST.SALES.ID", "#SCH#.FACT_SALES.ID"),
        ("#SCH#_STG.ORDERS.AMOUNT", "#SCH#.FACT_SALES.AMOUNT"),
        ("REF.CUST.BONUS", "#SCH#.FACT_SALES.AMOUNT"),
        ("HIST.SALES.AMOUNT", "#SCH#.FACT_SALES.AMOUNT"),
        ("STG_#ENV#.CLIENT.ID", "DWH.CLIENT.ID"),
        ("STG_#ENV#.CLIENT.NOM", "DWH.CLIENT.NOM"),
        ("#SCH#.FACT_SALES.AMOUNT", "DWH.CLIENT.CA"),
        ("DWH.CLIENT.ID", "TMP_X.ID"),
        ("#SCH#.FACT_SALES.AMOUNT", "TMP_X.MT"),
    }


def test_star_with_and_without_schema():
    sql = "INSERT INTO t SELECT * FROM #S#.src"
    schema = {"TPL#S#": {"SRC": {"A": "INT", "B": "INT"}}}
    assert lineage(sql, columns=True) == [{"source": "#S#.SRC.*", "target": "T.*"}]
    assert lineage(sql, columns=True, schema=schema) == [
        {"source": "#S#.SRC.A", "target": "T.A"},
        {"source": "#S#.SRC.B", "target": "T.B"},
    ]


def test_mermaid():
    md = to_mermaid(lineage(COLUMNS_SQL, columns=True), columns=True)
    assert md.startswith("```mermaid\nflowchart LR\n")
    assert 'subgraph t0["#35;SCH#35;_STG.ORDERS"]' in md
    assert "-->" in md


def test_template_as_value():
    sql = (
        "INSERT INTO t (d, j, x, c_#X#) SELECT sysdate, #pndate#, a, b_#X# FROM src"
        " WHERE dt = #pndate#"
    )
    assert lineage(sql, columns=True) == [
        {"source": "SRC.A", "target": "T.X"},
        {"source": "SRC.B_#X#", "target": "T.C_#X#"},
    ]


def test_select_only_script_with_target():
    sql = "WITH a AS (SELECT id, mt FROM #SCH#.src) SELECT sysdate d, #pndate# j, a.id, a.mt FROM a"
    assert lineage(sql) == []
    assert lineage(sql, target="#SCH#.dst") == [{"source": "#SCH#.SRC", "target": "#SCH#.DST"}]
    assert lineage(sql, columns=True, target="#SCH#.dst") == [
        {"source": "#SCH#.SRC.ID", "target": "#SCH#.DST.ID"},
        {"source": "#SCH#.SRC.MT", "target": "#SCH#.DST.MT"},
    ]
