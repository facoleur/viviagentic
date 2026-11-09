---
name: oracle-elt
description: Écrire, corriger, optimiser et documenter le SQL et le PL/SQL d'un ELT Oracle (26ai) sans erreur de compilation ORA-. À charger dès qu'une réponse contient du SQL Oracle ou porte sur une table, une opération, un flux ou une chaîne du data warehouse.
---

# Oracle ELT : règles de base

Contexte : data warehouse bancaire sur Oracle AI Database 26ai, ELT écrit en PL/SQL.
Une application = une ou plusieurs chaînes → flux → opérations (un bloc SQL ou PL/SQL).
Le code a 15 à 25 ans : du SQL propre côte à côte avec des opérations de 4 000 lignes.
Couches du DWH :
- **SDA** : données sources.
- **SDE** : données transformées, prêtes à être réutilisées, dont les tables **P** (préparatoires,
  pérennes, avec tout l'historique : P tiers, P flux…). Réutiliser une table P existante plutôt
  que recalculer la même logique dans un mart.
- **DMD** : data marts (tables de fait, de dimension et tables W).

## 1. Règles absolues

1. **Ne jamais inventer un nom.** Chaque table, colonne, vue, séquence et package utilisé doit
   avoir été lu dans le dictionnaire (outil de description de table) ou dans le SQL fourni.
   Un nom deviné donne ORA-00904 ou ORA-00942.
2. **Templates `#NOM#` intouchables.** Ce sont des variables du framework ELT, remplacées avant
   l'exécution. Les garder à l'identique, au même endroit, même dans une réécriture complète.
3. **Changer le moins possible.** Pour une correction, toucher seulement ce qui est nécessaire
   et garder le style du code existant (jointures, alias, casse). Dire ce qui a changé et pourquoi.
4. **Rester sémantiquement identique** lors d'une optimisation : mêmes lignes, mêmes valeurs,
   mêmes doublons. Signaler tout cas où le résultat pourrait différer (NULL, doublons, arrondis).
5. **Vérifier avant de rendre** : appliquer la checklist §4, puis compiler avec l'outil de
   validation s'il existe. Ne jamais présenter comme « testé » un SQL qui n'a pas été compilé.

## 2. Dialecte Oracle : ce qui casse la compilation

| Écrit par réflexe (autre SGBD) | Oracle | Erreur sinon |
|---|---|---|
| `FROM ventes AS v` | `FROM ventes v` (jamais `AS` devant un alias de **table**) | ORA-00933 |
| `SELECT … LIMIT 10` | `ORDER BY … FETCH FIRST 10 ROWS ONLY` | ORA-00933 |
| `WITH x AS (…) INSERT INTO t …` | `INSERT INTO t (cols) WITH x AS (…) SELECT …` | ORA-00928 |
| `"texte"` pour une chaîne | `'texte'` ; `"…"` est un identifiant sensible à la casse | ORA-00904 |
| `col::date`, `CAST(x AS text)` | `CAST(x AS DATE)`, `TO_DATE(x, 'YYYYMMDD')`, `VARCHAR2(n)` | ORA-00911/00902 |
| `ILIKE`, `ISNULL()`, `IFNULL()`, `NOW()`, `GETDATE()` | `UPPER(a) LIKE UPPER(b)`, `NVL`, `COALESCE`, `SYSDATE`, `SYSTIMESTAMP` | ORA-00904 |
| `'2024-01-31'` comparé à une DATE | `DATE '2024-01-31'` ou `TO_DATE('20240131','YYYYMMDD')` | ORA-01861 |
| `SELECT a, b, FROM t` (virgule finale) | supprimer la virgule | ORA-00936 |
| `;` à la fin d'un SQL passé à `EXECUTE IMMEDIATE` | pas de `;` (sauf bloc PL/SQL `BEGIN … END;`) | ORA-00911 |
| Mélange `(+)` et `JOIN … ON` dans un même bloc | tout en `(+)` ou tout en ANSI dans le bloc | ORA-25156 |
| `UPDATE t SET … FROM t2` (avant 23ai) | `MERGE` ou sous-requête corrélée | ORA-00933 |
| `NOT IN (SELECT col …)` avec des NULL possibles | `NOT EXISTS (…)` (`NOT IN` + un NULL = aucune ligne, sans erreur) | résultat faux |

Les nouveautés 23ai/26ai (BOOLEAN, `SELECT` sans `FROM`, `IF NOT EXISTS`, `UPDATE … FROM`,
`GROUP BY` sur un alias…) ne sont utilisables que si la base est réellement en 23 ou plus :
voir `oracle-elt-syntaxe-26ai`. Dans le doute, écrire en syntaxe classique, qui marche partout.

## 3. Pièges de logique fréquents

- **GROUP BY** : toute colonne non agrégée du `SELECT` doit être dans le `GROUP BY` (ORA-00979).
  Pas d'agrégat dans le `WHERE` : le mettre dans `HAVING` (ORA-00934).
- **Colonne ambiguë** : préfixer par l'alias toute colonne présente dans deux tables (ORA-00918).
- **Sous-requête scalaire** : elle doit renvoyer au plus une ligne (ORA-01427).
- **UNION / UNION ALL** : même nombre de colonnes (ORA-01789), types compatibles position par
  position (ORA-01790). `UNION` dédoublonne et trie : utiliser `UNION ALL` sauf besoin réel.
- **MERGE** : la source doit avoir au plus une ligne par clé `ON` (ORA-30926) ; une colonne
  utilisée dans `ON` ne peut pas être mise à jour (ORA-38104).
- **Insert direct-path** (`/*+ APPEND */`) : `COMMIT` obligatoire avant de relire ou modifier la
  table dans la même transaction (ORA-12838).
- **Conversion implicite** : comparer des types identiques (`TO_NUMBER`, `TO_DATE` avec format).
  Sinon ORA-01722 / ORA-01861 à l'exécution, et l'index ou l'élagage de partition est perdu.
- **NULL** : `col = NULL` est toujours faux, utiliser `IS NULL`. La chaîne vide `''` est NULL.
- **ROWNUM** : `ROWNUM > 1` est toujours faux ; `ROWNUM` est appliqué avant `ORDER BY`.
- **LAST_VALUE** : ajouter `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`.

## 4. Checklist avant de rendre du SQL

1. Toutes les tables et colonnes existent (vérifiées), avec le bon propriétaire/schéma.
2. Parenthèses équilibrées, pas de virgule avant `FROM`/`)`, chaque `CASE` a son `END`.
3. Aucun alias de table avec `AS`, chaînes entre apostrophes simples, dates avec format.
4. `GROUP BY` complet, colonnes ambiguës préfixées, `UNION` alignés en nombre et type.
5. Templates `#…#` tous présents et inchangés.
6. Pas de `;` dans un SQL dynamique ; `/` après chaque bloc PL/SQL dans un script SQL*Plus.
7. Pour une optimisation : résultat identique (cf. règle 4) et plan vérifié (`oracle-elt-performance`).

## 5. Lire une erreur ORA

Lire le code complet et la position (ligne/colonne) avant de corriger. `ORA-06550` n'est qu'une
enveloppe : la vraie cause est le `PLS-xxxxx` qui suit. `ORA-06512` indique seulement la ligne.
Table des erreurs de compilation et corrections : `oracle-elt-erreurs`.

## 6. Skills complémentaires (à charger avec `view_skill` seulement si la tâche le demande)

| Tâche | Skill |
|---|---|
| Corriger une erreur ORA- / PLS- | `oracle-elt-erreurs` |
| Savoir si une syntaxe récente est permise | `oracle-elt-syntaxe-26ai` |
| Écrire ou réécrire une opération de chargement (MERGE, APPEND, partitions, reprise) | `oracle-elt-patterns` |
| Opération lente, plan d'exécution, statistiques, index | `oracle-elt-performance` |
| PL/SQL : exceptions, bulk, SQL dynamique, qualité | `oracle-elt-plsql` |
| Explorer le schéma, retrouver des dépendances, documenter (commentaires, grain) | `oracle-elt-dictionnaire` |

---
Sources : synthèse de `github.com/oracle/skills` (domaine `db`, commit 0779f03, licence UPL 1.0),
complétée pour les erreurs de compilation, les nouveautés 23ai/26ai et les patterns de
chargement ELT, peu couverts par ce dépôt. Les points marqués « à vérifier » sont à confirmer
sur l'instance.
