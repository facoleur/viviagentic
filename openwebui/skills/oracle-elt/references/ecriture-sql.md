---
name: oracle-elt-ecriture
description: Méthode pour écrire du SQL Oracle juste du premier coup (vérifier, écrire, compiler, comparer), pièges silencieux qui donnent un résultat faux, et règles de style (lisible, court, maintenable). À charger avant d'écrire ou de réécrire une requête.
---

# Écrire du SQL Oracle juste et propre

Complète `oracle-elt` (dialecte, checklist) : ce skill donne la **méthode** et les pièges qui
**compilent mais donnent un résultat faux**, les plus dangereux.

## 1. Méthode : ne jamais écrire de mémoire

1. **Lire avant d'écrire.** `describe_table` sur chaque table utilisée : noms exacts, types,
   NULL possibles, clé. `search_objects` si le nom est incertain, `get_operation` pour le SQL
   d'une opération existante. Aucun nom de table ou de colonne non vérifié.
2. **Fixer le grain.** Écrire en une phrase ce que représente une ligne du résultat
   (« un compte par date d'arrêté »). Vérifier le grain des tables jointes avec `check_grain`
   sur la clé de jointure : une jointure sur une clé non unique multiplie les lignes.
3. **Vérifier les valeurs.** Avant de filtrer sur un code (`CD_STATUT = 'A'`), lire les valeurs
   réelles avec `distinct_values`. Ne jamais supposer un code, un libellé ou une casse.
4. **Écrire**, en suivant §3 et §4.
5. **Compiler** avec `compile_sql` et corriger jusqu'à « OK ». Un SQL non compilé n'est jamais
   présenté comme correct.
6. **Contrôler le résultat** sur un échantillon (`run_select`) : nombre de lignes plausible, pas
   de doublon au grain annoncé, totaux cohérents. Pour une réécriture, `compare_sql` doit
   donner le même nombre de lignes et la même somme de contrôle.

Si une information manque (colonne introuvable, règle métier ambiguë), le dire et demander,
plutôt que deviner.

## 2. Pièges silencieux (compile, mais résultat faux)

| Piège | Pourquoi c'est faux | Écrire plutôt |
|---|---|---|
| Filtre sur la table externe dans le `WHERE` après un `LEFT JOIN` | La jointure externe redevient interne | Mettre le filtre dans le `ON` |
| `NOT IN (SELECT …)` avec un NULL possible | Aucune ligne renvoyée | `NOT EXISTS` |
| `JOIN` sur une clé non unique | Lignes multipliées, sommes gonflées | Agréger ou dédoublonner la source avant la jointure |
| `DISTINCT` pour « corriger » des doublons | Masque une jointure fausse | Corriger la jointure (grain) |
| `BETWEEN DATE '2024-01-01' AND DATE '2024-01-31'` | Exclut le 31 après minuit | `d >= DATE '2024-01-01' AND d < DATE '2024-02-01'` |
| `TO_CHAR(d, 'YYYY-MM-DD HH:MM')` | `MM` = mois, les minutes sont `MI` | `'YYYY-MM-DD HH24:MI:SS'` |
| `TO_DATE(x)` / `TO_CHAR(n)` sans format | Dépend des réglages NLS de la session | Toujours un format explicite |
| `a = b` quand les deux peuvent être NULL | NULL = NULL est inconnu, ligne perdue | `DECODE(a, b, 1, 0) = 1` ou `(a = b OR (a IS NULL AND b IS NULL))` |
| `SUM`, `AVG` sur zéro ligne ou que des NULL | Renvoie NULL, pas 0 ; `AVG` ignore les NULL | `NVL(SUM(x), 0)` ; dire si les NULL comptent |
| `COUNT(col)` au lieu de `COUNT(*)` | Ne compte pas les NULL de `col` | `COUNT(*)` pour compter des lignes |
| `ADD_MONTHS` sur une fin de mois | Renvoie la fin du mois suivant (31/01 → 29/02 → 31/03) | Le vouloir explicitement, ou utiliser `LAST_DAY` |
| Table historisée (P) sans filtre de validité | Une ligne par version, pas par entité | Filtrer la version voulue (`DT_FIN` sentinelle ou date d'arrêté) |
| `ORDER BY` dans une sous-requête ou une vue | L'ordre n'est pas garanti au niveau supérieur | `ORDER BY` uniquement dans la requête finale, avec un critère départageant les ex aequo |
| `ROW_NUMBER() … ORDER BY` non unique | Ligne choisie au hasard, change d'une exécution à l'autre | Compléter l'`ORDER BY` jusqu'à une clé unique |

## 3. Pièges de compilation en plus de `oracle-elt` §2

- **Alias de colonne du `SELECT` dans le `WHERE`** : interdit (ORA-00904). Répéter l'expression
  ou passer par une CTE.
- **Fonction analytique dans le `WHERE`** (ORA-30483) : la calculer dans une CTE, filtrer après.
- **`DISTINCT` + `ORDER BY` sur une colonne non sélectionnée** : ORA-01791.
- **`CASE` dont les branches ont des types différents** : ORA-00932. Même type partout.
- **Liste `IN` de plus de 1 000 valeurs** : ORA-01795. Utiliser une table ou une sous-requête.
- **CLOB** : pas de `DISTINCT`, `GROUP BY`, `ORDER BY` ni `=` (ORA-00932 / ORA-22848).
  Comparer `DBMS_LOB.SUBSTR(c, 4000, 1)` ou `DBMS_LOB.COMPARE`.
- **Concaténation de plus de 4 000 octets en SQL** : ORA-01489. `LISTAGG(…) ON OVERFLOW
  TRUNCATE` ou un CLOB.
- **Mot réservé utilisé comme nom de colonne** (`DATE`, `LEVEL`, `SIZE`, `USER`, `COMMENT`…) :
  l'écrire entre guillemets **avec la casse exacte du dictionnaire** (`"DATE"`).
- **Conversion qui échoue sur une ligne** (ORA-01722, ORA-01861) : `TO_NUMBER(x DEFAULT NULL ON
  CONVERSION ERROR)` ou `VALIDATE_CONVERSION(x AS NUMBER) = 1` pour isoler les lignes en faute.
- **Division** : `a / NULLIF(b, 0)` évite ORA-01476.

## 4. Style : lisible, court, maintenable

**Structure**
- Une CTE par étape logique, nommée par ce qu'elle contient (`comptes_actifs`, pas `t1`).
  Pas de sous-requêtes imbriquées sur plusieurs niveaux.
- Filtrer le plus tôt possible, dans la CTE qui lit la table, pas à la fin.
- Liste de colonnes explicite partout : jamais de `SELECT *` dans du code livré, toujours
  `INSERT INTO t (col1, col2, …)`. Un `*` casse le jour où une colonne est ajoutée.
- Jointures ANSI (`JOIN … ON`) dans le code neuf ; garder `(+)` seulement pour une correction
  minimale d'un bloc qui l'utilise déjà.

**Lisibilité**
- Une colonne par ligne dans le `SELECT`, virgule en tête ou en fin selon le style du fichier.
- Mots-clés en majuscules, alias de table courts et parlants (`cpt`, `tie`), toujours utilisés
  pour préfixer les colonnes dès qu'il y a plus d'une table.
- Indentation régulière : `SELECT`, `FROM`, `WHERE`, `GROUP BY` alignés ; conditions une par ligne.
- Commenter le **pourquoi**, pas le quoi : la règle métier, le grain, la valeur sentinelle.
  En tête de requête : une ligne sur le grain du résultat.

**Fiabilité**
- Types comparés à l'identique, formats de date et de nombre explicites.
- Valeur par défaut de `NVL` choisie et justifiée (0 pour un montant, pas pour un taux).
- Pas de constante magique sans commentaire (`'9999-12-31'` = version courante).
- Templates `#NOM#` et paramètres plutôt que des valeurs codées en dur.

**Concision**
- Pas de colonne, de jointure ou de CTE inutilisée ; pas de code mort ni commenté.
- `CASE` simple plutôt qu'une cascade de `DECODE` imbriqués ; `COALESCE` pour plusieurs repli.
- Ne pas recalculer ce qu'une table P de SDE fournit déjà.

## 5. Exemple de forme attendue

```sql
-- Grain : un tiers par date d'arrêté #PNDATE#.
WITH tiers_courants AS (
    SELECT tie.id_tiers,
           tie.cd_segment
    FROM   sdeint.v_p_tiers tie
    WHERE  tie.dt_fin = DATE '9999-12-31'          -- version courante
),
soldes AS (
    SELECT cpt.id_tiers,
           SUM(cpt.mt_solde) AS mt_encours
    FROM   sdeint.v_p_compte cpt
    WHERE  cpt.dt_arrete = TO_DATE('#PNDATE#', 'YYYYMMDD')
    GROUP  BY cpt.id_tiers
)
SELECT tie.id_tiers,
       tie.cd_segment,
       NVL(sol.mt_encours, 0) AS mt_encours        -- tiers sans compte : 0
FROM   tiers_courants tie
LEFT   JOIN soldes sol
       ON sol.id_tiers = tie.id_tiers
```

Les noms de cet exemple sont illustratifs : toujours les vérifier dans le dictionnaire.
