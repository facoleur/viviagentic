# Prompts de test — outils d'exploration Oracle

A coller dans le chat Open WebUI (modele `qwen3:8b`), contre les donnees de
`docker/oracle-test/init.sql`. Penser a rebuild/relancer le conteneur `mcp` avant.

## describe_table

- Décris-moi la table D_TIERS, zone DMD : colonnes, clé, volumétrie.
- Quelles colonnes a DMDTRG.W_CLIENT_360 et est-ce qu'elle a une clé primaire ?
- Décris-moi M_OPERATION. (doit lever l'ambiguïté — elle existe dans 3 schémas, et demander de préciser au lieu de deviner)
- Décris-moi la table CLIENTS_XYZ. (n'existe pas — doit renvoyer une erreur qui dit d'utiliser search_objects)

## search_objects

- Je cherche les tables ou vues qui parlent des tiers.
- Trouve les objets contenant "flux" dans le nom, uniquement en zone SDE.

## compile_sql

- Est-ce que cette requête est valide : SELECT id_tiers, nom FROM DMDTRG.D_TIERS WHERE segment = #SEG# ?
- Vérifie cette requête sans l'exécuter : SELECT id_inconnu FROM DMDTRG.D_TIERS (doit renvoyer le code ORA-00904 et la position exacte)
- Cette requête avec un TO_DATE('#PNDATE#','YYYYMMDD') compile-t-elle ? (teste la substitution de template entre guillemets)

## run_select

- Montre-moi 5 lignes de SDATRG.MOUVEMENT.
- Supprime les lignes de SDATRG.MOUVEMENT où le montant est négatif. (doit être refusé — bon test que rien d'écriture ne passe, ni côté outil ni côté droits Oracle)

## check_grain

- Est-ce que id_mouvement est une vraie clé pour SDATRG.MOUVEMENT ? (oui, pas de doublons)
- Et devise ? (non — tout le monde est en EUR, ça doit montrer des doublons)

## column_stats

- Donne les valeurs distinctes de segment et pays dans DMDTRG.D_TIERS, filtré sur pays='FR'.

## find_usages

- Qui dépend de ou référence la table D_TIERS ?

## get_source

- Montre-moi le code source du package PKG_CHARGEMENT. (n'existe pas dans la base de test — doit renvoyer une erreur propre, pas une trace Python)
