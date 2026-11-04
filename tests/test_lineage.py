from lineage import lineage

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
