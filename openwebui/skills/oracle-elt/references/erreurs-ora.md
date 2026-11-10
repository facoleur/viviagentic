---
name: oracle-elt-erreurs
description: Table des erreurs ORA- et PLS- (compilation et exécution) : cause probable et correction. À charger pour corriger une erreur Oracle.
---

# Erreurs ORA- et PLS- : cause probable et correction

Lire d'abord le code et la position (ligne, colonne). La position pointe souvent juste **après**
la vraie faute : regarder le mot précédent.

## Compilation SQL (la requête n'a pas pu être analysée)

| Code              | Message                                                        | Cause la plus probable                                                                                                              | Correction                                                                                                                  |
| ----------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| ORA-00900         | invalid SQL statement                                          | Commande non SQL (commande SQL\*Plus, mot-clé d'un autre SGBD), bloc PL/SQL envoyé comme SQL                                        | Exécuter les blocs PL/SQL comme blocs ; retirer les commandes d'outil                                                       |
| ORA-00904         | invalid identifier                                             | Colonne inexistante ou mal orthographiée, alias défini dans le même `SELECT` puis réutilisé dans `WHERE`, chaîne écrite entre `"…"` | Vérifier la colonne dans `ALL_TAB_COLUMNS` ; répéter l'expression au lieu de l'alias ; apostrophes simples pour les chaînes |
| ORA-00905         | missing keyword                                                | `CASE` sans `THEN`/`END`, `MERGE` incomplet (`WHEN MATCHED THEN UPDATE SET`), `INTERVAL` mal écrit                                  | Compléter la clause                                                                                                         |
| ORA-00906 / 00907 | missing left / right parenthesis                               | Parenthèses déséquilibrées ; `ORDER BY` dans une sous-requête de `IN (…)` ; type avec taille mal placée                             | Recompter les parenthèses ; retirer l'`ORDER BY` inutile                                                                    |
| ORA-00909         | invalid number of arguments                                    | Mauvais nombre d'arguments (`NVL` à 3, `DECODE` incomplet, `SUBSTR` mal formé)                                                      | Corriger l'appel                                                                                                            |
| ORA-00911         | invalid character                                              | `;` final dans du SQL dynamique, `::`, guillemets typographiques `’ “`, `#` hors template, caractère invisible                      | Retirer le caractère ; apostrophes droites `'`                                                                              |
| ORA-00917         | missing comma                                                  | Virgule oubliée entre deux colonnes ou valeurs                                                                                      | Ajouter la virgule                                                                                                          |
| ORA-00918         | column ambiguously defined                                     | Colonne présente dans deux tables, non préfixée ; colonnes homonymes avec `FETCH FIRST`                                             | Préfixer par l'alias ; aliaser les colonnes homonymes                                                                       |
| ORA-00920         | invalid relational operator                                    | `WHERE col` seul, `==`, opérateur manquant                                                                                          | Écrire une comparaison complète                                                                                             |
| ORA-00923         | FROM keyword not found where expected                          | Virgule manquante dans le `SELECT`, alias avec espace non quoté, mot réservé comme alias                                            | Corriger la liste du `SELECT`                                                                                               |
| ORA-00928         | missing SELECT keyword                                         | `WITH … INSERT` (ordre inversé), `INSERT INTO t (cols) VALUES` attendu                                                              | `INSERT INTO t (cols) WITH … SELECT …`                                                                                      |
| ORA-00932         | inconsistent datatypes                                         | Comparaison ou `CASE`/`NVL`/`DECODE` mélangeant types (DATE vs NUMBER, CLOB dans `DISTINCT`/`GROUP BY`/`=`)                         | Convertir explicitement ; `DBMS_LOB.SUBSTR` ou `TO_CHAR` pour un CLOB                                                       |
| ORA-00933         | SQL command not properly ended                                 | `AS` devant un alias de table, `LIMIT`, `UPDATE … FROM` avant 23ai, `ORDER BY` mal placé, texte après la fin de requête             | Syntaxe Oracle (skill `oracle-elt`, §2)                                                                                     |
| ORA-00934         | group function is not allowed here                             | Agrégat dans `WHERE` ou dans un `GROUP BY`                                                                                          | Déplacer dans `HAVING` ou une sous-requête                                                                                  |
| ORA-00936         | missing expression                                             | Virgule en trop, `SELECT` vide, opérande manquant, template non remplacé qui laisse un trou                                         | Supprimer la virgule ; compléter l'expression                                                                               |
| ORA-00937         | not a single-group group function                              | Agrégat mélangé à une colonne non agrégée sans `GROUP BY`                                                                           | Ajouter le `GROUP BY` ou une fonction analytique `OVER ()`                                                                  |
| ORA-00942         | table or view does not exist                                   | Nom faux, schéma manquant, synonyme absent, privilège manquant                                                                      | Vérifier `ALL_TABLES`/`ALL_VIEWS`/`ALL_SYNONYMS`, préfixer le schéma                                                        |
| ORA-00957         | duplicate column name                                          | Même nom deux fois dans un `CREATE TABLE AS SELECT` ou une vue                                                                      | Aliaser                                                                                                                     |
| ORA-00969         | missing ON keyword                                             | `MERGE … USING` sans `ON (…)`, `GRANT` incomplet                                                                                    | `ON (cond)` entre parenthèses dans un `MERGE`                                                                               |
| ORA-00979         | not a GROUP BY expression                                      | Colonne du `SELECT`/`ORDER BY` absente du `GROUP BY`                                                                                | Ajouter la colonne (l'expression exacte) au `GROUP BY`                                                                      |
| ORA-00984         | column not allowed here                                        | Chaîne écrite `"…"` dans `VALUES`, colonne dans une valeur `DEFAULT`                                                                | Apostrophes simples                                                                                                         |
| ORA-01735 / 02000 | invalid option / missing keyword (DDL)                         | Option de `ALTER TABLE` d'un autre SGBD                                                                                             | Syntaxe Oracle du `ALTER TABLE`                                                                                             |
| ORA-01779         | cannot modify a column which maps to a non key-preserved table | `UPDATE (SELECT … JOIN …)` sans clé unique côté source                                                                              | Réécrire en `MERGE`                                                                                                         |
| ORA-01789         | query block has incorrect number of result columns             | `UNION` avec nombres de colonnes différents                                                                                         | Aligner les colonnes                                                                                                        |
| ORA-01790         | expression must have same datatype as corresponding expression | `UNION` avec types différents à la même position, `NULL` non typé                                                                   | `CAST(NULL AS DATE)` etc.                                                                                                   |
| ORA-25156         | old style outer join (+) cannot be used with ANSI joins        | `(+)` et `JOIN` dans le même bloc                                                                                                   | Un seul style par bloc (en ANSI de préférence pour du code neuf)                                                            |
| ORA-32034         | unsupported use of WITH clause                                 | `WITH` dans une position non permise                                                                                                | Placer le `WITH` juste avant le `SELECT` concerné                                                                           |
| ORA-38104         | columns referenced in the ON clause cannot be updated          | `MERGE … UPDATE SET` d'une colonne de `ON`                                                                                          | Retirer la colonne du `SET`, ou changer la clé                                                                              |

## Exécution (la requête compile mais échoue sur les données)

| Code                      | Cause                                                                                  | Correction                                                                     |
| ------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| ORA-00001                 | Doublon sur une clé unique                                                             | Dédoublonner la source, ou `MERGE`                                             |
| ORA-01400                 | NULL dans une colonne NOT NULL                                                         | `NVL`/valeur par défaut, ou filtrer les lignes                                 |
| ORA-01403 / 01422         | `SELECT INTO` : 0 ligne / plus d'une ligne                                             | Gérer `NO_DATA_FOUND` ; agréger ou curseur                                     |
| ORA-01427                 | Sous-requête scalaire qui renvoie plusieurs lignes                                     | Ajouter la condition manquante ou agréger (`MAX`)                              |
| ORA-01438 / 12899         | Valeur trop grande pour la précision / la longueur de la colonne                       | Vérifier la colonne cible ; ne pas tronquer en silence                         |
| ORA-01476                 | Division par zéro                                                                      | `NULLIF(diviseur, 0)`                                                          |
| ORA-01722                 | Nombre invalide (conversion implicite d'une chaîne non numérique)                      | `TO_NUMBER` explicite, `VALIDATE_CONVERSION`, filtrer avant de convertir       |
| ORA-01830 / 01843 / 01861 | Format de date incohérent                                                              | `TO_DATE` avec masque exact ; ne pas dépendre de `NLS_DATE_FORMAT`             |
| ORA-01555                 | Snapshot too old (requête longue, undo écrasé)                                         | Raccourcir la requête ; ne pas committer dans une boucle qui lit la même table |
| ORA-12838                 | Lecture/modification après un insert direct-path ou parallèle dans la même transaction | `COMMIT` juste après l'insert `APPEND`                                         |
| ORA-30926                 | Source du `MERGE` non unique sur la clé `ON`                                           | Dédoublonner la source (`ROW_NUMBER() … = 1`)                                  |

## PL/SQL

`ORA-06550` enveloppe une erreur de compilation PL/SQL : lire le `PLS-` qui suit.

| Code      | Cause                                                                                        | Correction                                                                      |
| --------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| PLS-00103 | Symbole inattendu : `;` manquant, `END` sans `END IF`/`END LOOP`, mot-clé mal placé          | Corriger la structure du bloc                                                   |
| PLS-00201 | Identifiant non déclaré (variable, table, package, schéma manquant)                          | Déclarer, préfixer le schéma, vérifier les privilèges directs (pas via un rôle) |
| PLS-00302 | Composant inexistant dans le package ou l'enregistrement                                     | Vérifier la spécification du package / les champs                               |
| PLS-00306 | Mauvais nombre ou type d'arguments                                                           | Vérifier la signature (`ALL_ARGUMENTS`)                                         |
| PLS-00382 | Expression de mauvais type                                                                   | Conversion explicite                                                            |
| PLS-00428 | `SELECT` sans `INTO` dans un bloc                                                            | Ajouter `INTO`, ou curseur                                                      |
| PLS-00905 | Objet invalide                                                                               | Recompiler la dépendance, lire `ALL_ERRORS`                                     |
| ORA-06502 | Valeur trop grande pour la variable (souvent `VARCHAR2(32767)` dépassé par un SQL dynamique) | Variable plus grande ou `CLOB`                                                  |
| ORA-06512 | Indique seulement la ligne de la pile                                                        | Lire l'erreur qui précède                                                       |

Erreurs de compilation d'un objet stocké :

```sql
SELECT line, position, text
FROM   all_errors
WHERE  owner = :schema AND name = :objet AND type = :type   -- 'PACKAGE BODY', 'PROCEDURE'…
ORDER  BY sequence;
```

Une procédure qui accède à une table via un **rôle** compile en SQL direct mais échoue en PL/SQL
(PLS-00201 / ORA-00942) : dans le code stocké, seuls les privilèges accordés directement comptent.
