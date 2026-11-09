---
name: oracle-elt-dictionnaire
description: Requêtes sur le dictionnaire, grain d'une table, non-régression entre deux versions, standard de documentation (COMMENT, annotations). À charger pour explorer ou documenter.
---

# Explorer le schéma et documenter

Les noms non quotés sont stockés en MAJUSCULES : comparer avec `UPPER(:nom)`.
Vues `ALL_*` = objets accessibles ; `USER_*` = objets du schéma courant ; `DBA_*` = tout (privilège).

## Décrire une table

```sql
SELECT column_id, column_name, data_type, data_length, data_precision, data_scale, nullable
FROM   all_tab_columns WHERE owner = :schema AND table_name = :table ORDER BY column_id;

SELECT comments FROM all_tab_comments WHERE owner = :schema AND table_name = :table;
SELECT column_name, comments FROM all_col_comments
WHERE  owner = :schema AND table_name = :table AND comments IS NOT NULL;

-- Clés primaires, uniques, étrangères
SELECT c.constraint_name, c.constraint_type, cc.column_name, cc.position,
       c.r_owner, c.r_constraint_name
FROM   all_constraints c
JOIN   all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name
WHERE  c.owner = :schema AND c.table_name = :table AND c.constraint_type IN ('P','U','R')
ORDER  BY c.constraint_name, cc.position;

-- Volume et fraîcheur des statistiques
SELECT num_rows, blocks, last_analyzed, partitioned
FROM   all_tables WHERE owner = :schema AND table_name = :table;
```

Dans un data warehouse, les contraintes sont souvent absentes : la clé réelle se déduit des
données (voir « Grain » ci-dessous) et des index uniques (`ALL_INDEXES.uniqueness = 'UNIQUE'`).

## Retrouver qui lit ou écrit une table

```sql
-- Objets stockés (packages, procédures, vues) qui dépendent de la table
SELECT owner, name, type FROM all_dependencies
WHERE  referenced_owner = :schema AND referenced_name = :table;

-- Recherche dans le code source stocké (le SQL dynamique n'apparaît pas dans ALL_DEPENDENCIES)
SELECT owner, name, type, line, TRIM(text) text
FROM   all_source WHERE UPPER(text) LIKE '%' || UPPER(:table) || '%'
ORDER  BY owner, name, line;
```

Le SQL des opérations stocké dans les tables de métadonnées du framework n'est pas dans le
dictionnaire : il faut le chercher dans ces tables (outil dédié) et l'analyser.

## Autres objets utiles

```sql
SELECT table_name, partitioning_type, subpartitioning_type, partition_count, interval
FROM   all_part_tables WHERE owner = :schema;
SELECT partition_name, high_value, num_rows, last_analyzed
FROM   all_tab_partitions WHERE table_owner = :schema AND table_name = :table;
SELECT index_name, index_type, uniqueness, partitioned, visibility, status
FROM   all_indexes WHERE table_owner = :schema AND table_name = :table;
SELECT owner, object_name, object_type FROM all_objects
WHERE  owner = :schema AND status = 'INVALID';                        -- objets à recompiler
SELECT owner, synonym_name, table_owner, table_name FROM all_synonyms
WHERE  synonym_name = UPPER(:nom);                                      -- résoudre un synonyme
SELECT job_name, enabled, state, repeat_interval, last_start_date
FROM   all_scheduler_jobs WHERE owner = :schema;
-- 23ai+ : métadonnées structurées
SELECT object_name, column_name, annotation_name, annotation_value
FROM   all_annotations WHERE owner = :schema AND object_name = :table;
```

## Grain d'une table

Le grain = ce que représente **une ligne** (ex. « un compte par jour d'arrêté »). Le vérifier sur
les données plutôt que de le supposer :

```sql
SELECT COUNT(*) nb_lignes,
       COUNT(DISTINCT id_compte || '|' || TO_CHAR(dt_arrete, 'YYYYMMDD')) nb_cles
FROM   dwh.f_solde
WHERE  dt_arrete = DATE '2024-01-31';      -- toujours restreindre aux grosses tables
```

`nb_lignes = nb_cles` : la combinaison est une clé candidate. Sinon, chercher les doublons :
`GROUP BY id_compte, dt_arrete HAVING COUNT(*) > 1`. Sans échantillon restreint, utiliser
`ALL_TAB_COL_STATISTICS.num_distinct` comme indication (approximative).

## Comparer deux versions d'une requête (non-régression)

```sql
SELECT COUNT(*) nb, SUM(ORA_HASH(id || '|' || montant || '|' || TO_CHAR(dt, 'YYYYMMDD'))) controle
FROM  (/* version A */ SELECT …);
-- même requête sur la version B : nb et controle doivent être égaux

-- Différences ligne à ligne (dans les deux sens)
(SELECT … /* A */ MINUS SELECT … /* B */)
UNION ALL
(SELECT … /* B */ MINUS SELECT … /* A */);
```

`MINUS` ignore les doublons : compléter par le comptage. Restreindre à une date ou une partition
sur les grosses tables.

## Documenter une table

```sql
-- COMMENT n'accepte qu'un littéral : pas de concaténation ||
COMMENT ON TABLE dwh.f_solde IS 'Solde de fin de journée par compte. Grain : un compte par date d''arrêté. Alimentée par le flux SOLDES, opération CHARGE_F_SOLDE (incrémental, rejouable).';
COMMENT ON COLUMN dwh.f_solde.mt_solde IS 'Solde en devise du compte, signe comptable (+ créditeur).';
```

Contenu attendu pour chaque table : objectif métier, **grain**, clé, source(s), opération qui
l'alimente, fréquence, mode (complet / incrémental), historisation, règles de gestion non
évidentes. Pour chaque colonne : définition, unité/devise, règle de calcul, valeurs possibles
pour un code. Écrire ce qui est vérifié ; marquer `[à confirmer]` ce qui est déduit.

En 23ai+, les annotations stockent ces informations de façon structurée et interrogeable :
`ALTER TABLE dwh.f_solde ANNOTATIONS (ADD grain 'compte x date d''arrêté', ADD alimentation 'CHARGE_F_SOLDE');`
