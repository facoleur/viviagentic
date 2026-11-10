# Prompts de test — outils de rendu (MCP Apps)

A coller dans le chat Open WebUI (modele `qwen3:8b`). Ces outils affichent une vue dans la
conversation au lieu de renvoyer du texte : chart, graph, table, sql_lineage.

## chart

- Fais un graphique en barres avec les ventes de janvier a juin : 120, 150, 90, 200, 175, 130.
- Meme chose mais en courbe.
- Compare deux series sur les memes mois, en barres groupees : ventes 2024 (120, 150, 90, 200, 175, 130) et ventes 2025 (140, 160, 110, 210, 190, 150).
- Fais un graphique en aires de l'evolution du nombre de clients sur 12 mois, avec des valeurs inventees.

## graph

- Dessine un graphe avec ces dependances : A depend de B, B depend de C, D depend de B.
- Fais un graphe dirige de ce flux de donnees : SDA alimente SDE, SDE alimente DMD, DMD alimente le reporting.
- Meme chose avec des groupes de couleur differents pour chaque zone (SDA, SDE, DMD).

## table

- Montre-moi un tableau avec ces clients : id 1 Jean Dupont FR, id 2 Marie Martin BE, id 3 Alain Bernard LU.
- Lance une requete sur SDATRG.MOUVEMENT et affiche le resultat dans un tableau triable et filtrable.
- Affiche ces resultats dans un tableau avec les colonnes explicites id, nom, montant : (1, "A", 100), (2, "B", 250), (3, "C", 75).

## sql_lineage

- Fais le lineage par table de ce script : INSERT INTO DWH.FACT_SALES SELECT c.id, c.amount FROM STG.ORDERS c JOIN REF.CUSTOMERS r ON c.cid = r.id
- Meme chose mais par colonne, avec le graphe affiche.
- Fais le lineage de ce SELECT seul, en considerant qu'il alimente DMDTRG.W_CLIENT_360 : SELECT t.id_tiers, t.nom, f.montant FROM DMDTRG.D_TIERS t JOIN DMDTRG.F_OPERATION f ON f.id_tiers = t.id_tiers
