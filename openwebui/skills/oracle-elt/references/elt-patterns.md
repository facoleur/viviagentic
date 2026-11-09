---
name: oracle-elt-patterns
description: Formes de chargement ELT : INSERT APPEND, MERGE dédoublonné, échange de partition, rejouabilité, sources de lenteur des vieux flux. À charger pour écrire ou réécrire une opération.
---

# Patterns d'opérations ELT

Principe : **une opération = une instruction ensembliste**. Une boucle qui traite les lignes une
à une est presque toujours la cause d'une lenteur ; la remplacer par un `INSERT … SELECT`, un
`MERGE` ou, à défaut, `BULK COLLECT` + `FORALL` (skill `oracle-elt-plsql`).

## Choisir la forme de chargement

| Besoin | Forme | Points d'attention |
|---|---|---|
| Recharger entièrement une table de travail | `TRUNCATE` puis `INSERT /*+ APPEND */ … SELECT` | `TRUNCATE` est du DDL : commit implicite, pas de retour arrière |
| Ajouter un lot à une table historique | `INSERT /*+ APPEND */ … SELECT` | `COMMIT` avant toute relecture (ORA-12838) |
| Mettre à jour + insérer (upsert) | `MERGE` | Source unique par clé (ORA-30926), pas de `SET` sur les colonnes de `ON` (ORA-38104) |
| Remplacer une partition entière | Charger une table de travail, puis `EXCHANGE PARTITION` | Même structure et mêmes index ; opération quasi instantanée |
| Gros volume, peu de lignes modifiées | `INSERT` direct-path des nouvelles lignes + `UPDATE` ciblé | Mesurer : `MERGE` n'est pas toujours le plus rapide |
| Isoler les lignes en erreur sans tout planter | `LOG ERRORS INTO err$_t REJECT LIMIT UNLIMITED` | Créer la table d'erreurs avec `DBMS_ERRLOG.CREATE_ERROR_LOG` ; contrôler son contenu après |

## Insert direct-path (`APPEND`)

```sql
INSERT /*+ APPEND */ INTO dwh.f_operation (id_ope, dt_ope, mt_ope)
SELECT s.id_ope, s.dt_ope, s.mt_ope
FROM   stg.operation s
WHERE  s.dt_charge = TO_DATE('#DT_TRAITEMENT#', 'YYYYMMDD');
COMMIT;   -- obligatoire avant de relire dwh.f_operation dans la même session
```

- Écrit au-dessus de la limite haute de la table, sans passer par le cache : rapide, peu d'undo.
- Oracle repasse en insert classique, **sans le dire**, si la table a des triggers actifs ou des
  clés étrangères actives. Vérifier dans le plan : `LOAD AS SELECT` = direct-path.
- En parallèle : `ALTER SESSION ENABLE PARALLEL DML;` avant l'instruction.
- Statistiques : un `CREATE TABLE AS SELECT` ou un `INSERT /*+ APPEND */` dans une table **vide**
  calcule les statistiques au passage (12c+). Sinon, les calculer après le chargement.

## MERGE

```sql
MERGE INTO dwh.d_client c
USING (
    SELECT id_client, segment, dt_maj
    FROM  (SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.id_client ORDER BY s.dt_maj DESC) rn
           FROM   stg.client s)
    WHERE  rn = 1                                   -- une seule ligne par clé : évite ORA-30926
) s
ON (c.id_client = s.id_client)
WHEN MATCHED THEN UPDATE
     SET c.segment = s.segment, c.dt_maj = s.dt_maj
     WHERE DECODE(c.segment, s.segment, 0, 1) = 1   -- ne réécrire que ce qui change (NULL compris)
WHEN NOT MATCHED THEN INSERT (id_client, segment, dt_maj)
     VALUES (s.id_client, s.segment, s.dt_maj);
```

- La clause `WHERE` du `UPDATE` évite de réécrire des lignes identiques (moins d'undo et de redo).
- `DELETE WHERE` dans `WHEN MATCHED` ne supprime que des lignes **mises à jour** par ce `MERGE`.
- Comparaison de colonnes nullables : `DECODE(a, b, 0, 1) = 1` traite `NULL = NULL` comme égal.

## Échange de partition

```sql
-- 1. Charger stg.f_ope_202401 (même structure que dwh.f_ope, sans partition)
-- 2. Créer sur stg.f_ope_202401 les mêmes index que les index LOCAL de dwh.f_ope
ALTER TABLE dwh.f_ope EXCHANGE PARTITION p_202401
  WITH TABLE stg.f_ope_202401 INCLUDING INDEXES WITHOUT VALIDATION;
```

`WITHOUT VALIDATION` suppose que toutes les lignes appartiennent bien à la partition : à ne
faire que si le chargement le garantit. Les index globaux deviennent inutilisables sans
`UPDATE GLOBAL INDEXES`.

## Rejouabilité et reprise

- Une opération doit pouvoir être relancée sans doubler les données : purger d'abord la tranche
  qu'elle charge (`DELETE` ciblé ou `TRUNCATE PARTITION`), ou utiliser `MERGE`.
- Ne pas committer dans une boucle qui lit la table qu'elle modifie (ORA-01555, reprise impossible).
- Le DDL (`CREATE`, `TRUNCATE`, `ALTER`) committe tout ce qui précède : le placer en début
  d'opération, jamais au milieu d'une transaction de données.
- Tables temporaires globales (GTT) : pas de redo pour les données, statistiques propres à la
  session ; pratiques pour les étapes intermédiaires d'une même session.

## Sources de lenteur typiques dans un vieux flux

| Symptôme dans le code | Remplacement |
|---|---|
| `FOR r IN (SELECT …) LOOP … INSERT/UPDATE … END LOOP` | Une seule instruction ensembliste |
| Appel d'une fonction PL/SQL par ligne dans un `SELECT` | Jointure, `CASE`, ou sous-requête scalaire (mise en cache) |
| Même table lue plusieurs fois par des `UNION` ou des sous-requêtes | Une lecture + agrégation conditionnelle (`SUM(CASE …)`), ou `WITH` |
| Auto-jointure pour comparer à la ligne précédente | `LAG` / `LEAD` |
| `DISTINCT` ajouté pour masquer des doublons | Corriger la jointure qui duplique |
| Tables de travail successives copiées entièrement | Fusionner les étapes en une requête, ou n'y copier que les colonnes utiles |
| `UPDATE` successifs sur la même table | Un seul `UPDATE`/`MERGE` avec `CASE`, ou recalcul en `INSERT … SELECT` |
| Fonction sur la colonne de partition ou indexée (`TRUNC(dt) = …`) | Prédicat en intervalle : `dt >= :d AND dt < :d + 1` |
