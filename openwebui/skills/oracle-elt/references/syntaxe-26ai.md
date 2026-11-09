---
name: oracle-elt-syntaxe-26ai
description: Nouveautés SQL 23ai/26ai (BOOLEAN, UPDATE … FROM, IF EXISTS, annotations…) et leur équivalent classique. À charger avant d'utiliser une syntaxe récente.
---

# Syntaxe récente (23ai / 26ai) : quand l'utiliser

Oracle AI Database 26ai reprend les nouveautés SQL apparues en 23ai. Elles ne sont utilisables
que si l'instance est en 23 ou plus **et** que le paramètre `COMPATIBLE` l'est aussi.

```sql
SELECT version_full FROM product_component_version;          -- version du moteur
SELECT value FROM v$parameter WHERE name = 'compatible';      -- si privilège sur V$
```

Règle pour ce data warehouse : le code existant est en syntaxe classique. Pour **corriger** une
opération, rester en syntaxe classique. Pour une **réécriture** validée par l'équipe, ces
nouveautés sont permises si la version le confirme. Ne jamais les mélanger à la légère dans un
flux dont d'autres opérations tournent ailleurs (autre base, version plus ancienne).

## Nouveautés SQL utiles (23ai et plus)

| Nouveauté | Exemple | Équivalent classique |
|---|---|---|
| Type `BOOLEAN` en SQL | `actif BOOLEAN`, `WHERE actif` | `NUMBER(1)` + `CHECK (actif IN (0,1))`, `WHERE actif = 1` |
| `SELECT` sans `FROM` | `SELECT SYSDATE;` | `SELECT SYSDATE FROM dual;` |
| `IF [NOT] EXISTS` en DDL | `DROP TABLE IF EXISTS stg_x;` | bloc PL/SQL qui ignore ORA-00942 |
| `GROUP BY` sur un alias | `SELECT TRUNC(dt,'MM') mois, SUM(m) … GROUP BY mois` | répéter l'expression |
| Jointure directe dans `UPDATE` / `DELETE` | `UPDATE c SET c.seg = s.seg FROM seg s WHERE s.id = c.id` | `MERGE`, ou sous-requête corrélée |
| `INSERT` multi-lignes | `INSERT INTO t VALUES (1,'a'), (2,'b');` | `INSERT ALL … SELECT * FROM dual` ou `UNION ALL` |
| Constructeur de table | `SELECT * FROM (VALUES (1,'a'), (2,'b')) v (id, lib)` | `SELECT … FROM dual UNION ALL …` |
| `RETURNING OLD / NEW` | `UPDATE … RETURNING OLD m, NEW m INTO …` | lecture avant/après |
| Annotations | `ALTER TABLE t ANNOTATIONS (ADD grain 'un compte par jour')` | `COMMENT ON TABLE` |
| Domaines SQL | `CREATE DOMAIN montant AS NUMBER(18,2) …` | type + `CHECK` répétés |

À vérifier sur l'instance avant de s'y fier : la syntaxe exacte de ces clauses a des variantes.
En cas d'erreur, revenir à l'équivalent classique de la troisième colonne.

## Ce qui n'a PAS changé

- Toujours pas d'`AS` devant un alias de table, pas de `LIMIT`, pas de `ILIKE`, pas de `::`.
- `WITH` reste placé après `INSERT INTO t (cols)`.
- La chaîne vide `''` reste traitée comme `NULL` pour `VARCHAR2`.
- `(+)` et syntaxe ANSI ne se mélangent toujours pas dans un même bloc.
- Les noms non quotés sont stockés en MAJUSCULES dans le dictionnaire.

## Disponible depuis longtemps (12c / 19c), souvent oublié

- `FETCH FIRST n ROWS ONLY`, `OFFSET … FETCH NEXT` (12.1).
- `LISTAGG(… ON OVERFLOW TRUNCATE)` (12.2), `LISTAGG(DISTINCT …)` (19c).
- `VALIDATE_CONVERSION(x AS NUMBER)` et `TO_NUMBER(x DEFAULT NULL ON CONVERSION ERROR)` (12.2) :
  convertir sans planter sur une valeur sale.
- Macros SQL (`SQL_MACRO`, 19c/21c) : factoriser une expression répétée sans coût PL/SQL.
- `MATCH_RECOGNIZE`, `PIVOT`/`UNPIVOT`, fonctions analytiques (`LAG`, `LEAD`, `RATIO_TO_REPORT`).
