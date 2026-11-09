---
name: oracle-elt-performance
description: Diagnostiquer une opération lente : plan réel, causes fréquentes, statistiques, index et partitions, hints. À charger pour optimiser.
---

# Diagnostiquer et optimiser une opération lente

Ne jamais optimiser à l'aveugle : mesurer, lire le plan réel, corriger la première étape où
l'estimation diverge de la réalité, re-mesurer. Le coût (`COST`) n'est pas un temps.

## 0. Sans accès à l'exécution

L'agent est en lecture seule : pas d'exécution, pas d'`EXPLAIN PLAN`, pas d'AWR/ASH/SQL Monitor
(Diagnostics et Tuning Packs non licenciés). Il travaille donc ainsi :
1. Durées et volumes réels : l'historique d'exécution du framework (durée par opération,
   lignes traitées), pas une estimation.
2. Volumes et statistiques : `ALL_TABLES.num_rows`, `last_analyzed`, partitions, index
   (skill `oracle-elt-dictionnaire`).
3. Analyse statique du SQL avec le tableau §2 et les patterns de `oracle-elt-patterns`.
4. Rendre une proposition **à mesurer** : la requête `DISPLAY_CURSOR` ci-dessous à faire lancer
   par un humain avant/après, et l'hypothèse qu'elle doit confirmer. Ne jamais annoncer un gain
   chiffré non mesuré.

## 1. Obtenir le plan réel (lignes estimées vs réelles) — à faire lancer par un humain

```sql
SELECT /*+ GATHER_PLAN_STATISTICS */ …;          -- exécuter la requête une fois

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(NULL, NULL, 'ALLSTATS LAST'));
-- ou pour une requête déjà passée :
SELECT sql_id, child_number, executions, elapsed_time/1e6 s, buffer_gets, sql_text
FROM   v$sql WHERE sql_text LIKE '%f_operation%' ORDER BY elapsed_time DESC;
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(:sql_id, :child, 'ALLSTATS LAST +PEEKED_BINDS'));
```

`EXPLAIN PLAN` donne un plan **théorique**, qui peut différer du plan exécuté (variables liées,
statistiques). Il suffit pour vérifier qu'une requête compile, pas pour diagnostiquer.

Lecture :
- Comparer `E-Rows` (estimé) et `A-Rows` (réel) à chaque étape. Un écart de 10x ou plus à
  une étape explique en général le mauvais plan : partir de la plus profonde.
- `A-Time` est cumulé : le temps d'une étape = son `A-Time` moins celui de ses enfants.
- Section *Predicate Information* : `access` = utilisé pour accéder (index, partition),
  `filter` = appliqué après lecture. Une conversion implicite y apparaît (`INTERNAL_FUNCTION`,
  `TO_NUMBER(col)`).
- `PARTITION RANGE ALL` sur une grosse table = pas d'élagage de partition.
- `Used-Tmp` élevé = tri ou hachage qui déborde sur disque (TEMP).

Licences : `V$SQL_MONITOR`/rapports SQL Monitor demandent le Tuning Pack ; AWR et ASH le
Diagnostics Pack. Vérifier avec l'équipe avant de s'en servir. `DISPLAY_CURSOR` n'en demande pas.

## 2. Causes fréquentes et corrections

| Constat | Cause | Correction |
|---|---|---|
| Estimation très fausse sur une table chargée dans le flux | Statistiques absentes ou périmées après le chargement | `DBMS_STATS.GATHER_TABLE_STATS` après le chargement (voir §3) |
| Index ou partition ignorés | Fonction ou conversion sur la colonne (`TRUNC(dt)`, `col = '123'` sur un NUMBER) | Prédicat sur la colonne nue, types identiques ; index de fonction si l'expression est récurrente |
| `NESTED LOOPS` sur des millions de lignes | Sous-estimation de cardinalité | Corriger les stats ; au pire `USE_HASH` le temps de corriger la cause |
| Même table lue plusieurs fois | `UNION`, sous-requêtes répétées | Une lecture et agrégation conditionnelle ; `WITH` + `/*+ MATERIALIZE */` si réutilisé |
| Énorme tri / `HASH GROUP BY` qui déborde | Trop de colonnes ou de lignes transportées | Filtrer et agréger tôt, ne garder que les colonnes utiles |
| Jointure qui multiplie les lignes puis `DISTINCT` | Clé de jointure incomplète | Corriger la jointure |
| `OR` sur des colonnes différentes | Pas d'accès indexé possible | `UNION ALL` de deux branches exclusives, si mesuré meilleur |
| Fonction PL/SQL appelée par ligne | Changement de contexte SQL/PL/SQL à chaque ligne | Logique en SQL, ou sous-requête scalaire (mise en cache), ou `PRAGMA UDF` |

## 3. Statistiques dans un ELT

```sql
BEGIN
  DBMS_STATS.GATHER_TABLE_STATS(ownname => 'DWH', tabname => 'F_OPERATION',
                                partname => 'P_202401', granularity => 'PARTITION');
END;
/
```

- Après un chargement conventionnel important, toujours recalculer avant que les opérations
  suivantes lisent la table. Les valeurs par défaut (`AUTO_SAMPLE_SIZE`,
  `FOR ALL COLUMNS SIZE AUTO`) sont presque toujours les bonnes.
- Tables partitionnées : statistiques incrémentales (`DBMS_STATS.SET_TABLE_PREFS(…,
  'INCREMENTAL', 'TRUE')`) pour ne pas relire les partitions inchangées.
- Tables de référence stables : on peut verrouiller leurs statistiques.

## 4. Index et partitions dans un data warehouse

- Index locaux sur les tables partitionnées ; index globaux seulement si indispensable
  (une maintenance de partition les rend inutilisables sans `UPDATE GLOBAL INDEXES`).
- Index bitmap pour les colonnes peu sélectives des faits, **jamais** sur une table modifiée en
  concurrence (verrous).
- Avant de supprimer un index : le rendre `INVISIBLE`, mesurer, puis supprimer.
- Partitionnement par intervalle (`INTERVAL`) sur la date de chargement ou d'arrêté : les
  partitions se créent seules ; les requêtes doivent filtrer sur la colonne de partition nue.
- Compression (`COMPRESS FOR QUERY HIGH` sur Exadata, `ROW STORE COMPRESS ADVANCED` sinon)
  sur les partitions historiques qui ne bougent plus.

## 5. Hints : en dernier recours

Un hint dans le code fige un plan et casse quand les données changent. Les accepter seulement
s'ils sont justifiés par une mesure : `APPEND`, `PARALLEL(t n)`, `MATERIALIZE`/`INLINE` sur un
`WITH`, `LEADING`/`USE_HASH` après échec des corrections de statistiques. Retirer les hints
hérités qui n'apportent plus rien (les tester avec et sans).

## 6. Rendre une optimisation

Toujours fournir : le temps ou les `buffer_gets` avant/après (ou demander à les mesurer), la
preuve que le résultat est identique (comptage et somme de contrôle des deux versions, voir
skill `oracle-elt-dictionnaire`), et la liste des changements de comportement possibles.
