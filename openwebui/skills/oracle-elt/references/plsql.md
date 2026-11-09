---
name: oracle-elt-plsql
description: PL/SQL du framework : exceptions, BULK COLLECT/FORALL, SQL dynamique, qualité et maintenabilité. À charger pour écrire ou relire du PL/SQL.
---

# PL/SQL du framework ELT

## Structure d'un bloc

```sql
DECLARE
  v_nb PLS_INTEGER;
BEGIN
  INSERT INTO … SELECT …;            -- le SQL se termine par ;
  v_nb := SQL%ROWCOUNT;              -- à lire juste après l'instruction
  IF v_nb = 0 THEN
    NULL;
  END IF;                            -- END IF / END LOOP / END CASE : toujours fermés
END;
/
```

Dans un script SQL*Plus/SQLcl, un `/` seul sur sa ligne exécute le bloc. Une ligne vide au milieu
d'une requête SQL peut la couper (`SET SQLBLANKLINES ON` pour l'éviter), un `&` déclenche une
substitution (`SET DEFINE OFF`).

## Exceptions

```sql
EXCEPTION
  WHEN NO_DATA_FOUND THEN
    v_valeur := NULL;                                   -- cas attendu, traité explicitement
  WHEN OTHERS THEN
    log_pkg.erreur(p_operation => 'CHARGE_F_OPE',      -- journal en transaction autonome
                   p_message   => DBMS_UTILITY.FORMAT_ERROR_STACK
                                  || DBMS_UTILITY.FORMAT_ERROR_BACKTRACE);
    RAISE;                                              -- toujours relancer
END;
```

- Jamais `WHEN OTHERS THEN NULL` : l'opération semble réussir alors qu'elle a échoué.
- `SQLERRM` seul est tronqué et sans numéro de ligne : `FORMAT_ERROR_STACK` + `FORMAT_ERROR_BACKTRACE`.
- Journaliser dans une procédure `PRAGMA AUTONOMOUS_TRANSACTION`, sinon le journal disparaît au rollback.
- Erreurs métier : `RAISE_APPLICATION_ERROR(-20xxx, 'message', TRUE)` (plage -20000 à -20999,
  `TRUE` conserve l'erreur d'origine).
- Exceptions spécifiques avant `WHEN OTHERS` ; pas d'exception pour piloter un traitement normal.

## Traitement en masse quand le SQL ensembliste ne suffit pas

```sql
DECLARE
  CURSOR c IS SELECT id, montant FROM stg.ope;
  TYPE t_ids IS TABLE OF stg.ope.id%TYPE;
  TYPE t_mts IS TABLE OF stg.ope.montant%TYPE;
  v_ids t_ids; v_mts t_mts;
BEGIN
  OPEN c;
  LOOP
    FETCH c BULK COLLECT INTO v_ids, v_mts LIMIT 1000;   -- toujours un LIMIT
    EXIT WHEN v_ids.COUNT = 0;
    FORALL i IN 1 .. v_ids.COUNT
      UPDATE dwh.f_ope SET montant = v_mts(i) WHERE id = v_ids(i);
  END LOOP;
  CLOSE c;
END;
```

- `EXIT WHEN v_ids.COUNT = 0` après le `FETCH` (et non `c%NOTFOUND`, qui perd le dernier lot).
- `FORALL … SAVE EXCEPTIONS` pour continuer malgré des lignes en erreur, puis lire
  `SQL%BULK_EXCEPTIONS`.
- Mais d'abord : une seule instruction `UPDATE`/`MERGE` ensembliste est presque toujours plus
  rapide et plus simple que `BULK COLLECT` + `FORALL`.

## SQL dynamique

```sql
v_sql := 'INSERT /*+ APPEND */ INTO ' || DBMS_ASSERT.SQL_OBJECT_NAME(p_table)
      || ' SELECT * FROM stg.ope WHERE dt_charge = :d';   -- pas de ; final
EXECUTE IMMEDIATE v_sql USING p_date;
```

- Valeurs en variables liées (`:d` + `USING`), jamais concaténées (injection, analyse à chaque appel).
- Noms d'objets concaténés : les valider (`DBMS_ASSERT.SQL_OBJECT_NAME`, `SIMPLE_SQL_NAME`,
  ou liste blanche). `DBMS_ASSERT.NOOP` ne valide rien.
- SQL de plus de 32 767 octets : variable `CLOB`.
- Autant de `USING` que de variables liées (sinon ORA-01008).
- Le DDL en dynamique (`EXECUTE IMMEDIATE 'TRUNCATE TABLE …'`) committe la transaction en cours.
- En développement, journaliser le SQL construit : c'est le seul moyen de lire ce qui a échoué.

## Qualité et maintenabilité

- Une procédure = une responsabilité ; regrouper par flux dans un package, spécification courte.
- Typage par ancrage : `%TYPE`, `%ROWTYPE`, pour suivre l'évolution des tables.
- Liste de colonnes explicite dans `INSERT` et `SELECT` (jamais `INSERT INTO t SELECT *` vers
  une table permanente : casse quand une colonne est ajoutée).
- Pas de nom de schéma en dur si le framework le fournit (template `#SCHEMA#` ou paramètre).
- Constantes nommées plutôt que valeurs magiques (codes, dates pivots).
- En-tête de chaque opération : objectif, tables lues, table écrite, grain, mode de chargement
  (complet, incrémental, rejouable), auteur et date de dernière modification.
- Compiler avec les avertissements pour trouver le code mort et les conversions :
  `ALTER SESSION SET PLSQL_WARNINGS = 'ENABLE:ALL';` puis lire `ALL_ERRORS`.
