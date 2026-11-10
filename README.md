# vivia

Stack LLM locale : Ollama + Open WebUI + serveur MCP + Arize Phoenix.
Seul Open WebUI est publie (`:3000`) ; Phoenix est sur la loopback (`127.0.0.1:6006`),
Ollama et le serveur MCP restent sur le reseau interne du projet.

## Demarrage

```sh
cp .env.example .env && $EDITOR .env   # WEBUI_SECRET_KEY, VIVIA_MODEL, ORACLE_DSN/USER/PASSWORD
uv sync
make up                                # pull du modele inclus (service ollama-pull)
make configure                         # applique vivia.toml a Open WebUI
```

## Configuration

Tout passe par `vivia.toml` : admin, utilisateurs, groupes, permissions par defaut,
modele par defaut, tool servers MCP, skills, functions. `make configure` est idempotent,
rejouable a volonte, et ne demande jamais de passer par l'UI.

Chaque table `[api."<chemin>"]` est POSTee telle quelle sur `/api/v1/<chemin>` : ajouter ou
retirer un reglage ne demande aucune modification de code, et n'importe quel endpoint de
configuration est atteignable. Seules `[[groups]]`, `[[skills]]`, `[[models]]` et `[[functions]]`
ont un schema fixe, chacune traitee par un module de `src/vivia/configure/`.
Les noms de cles sont documentes dans
<https://docs.openwebui.com/getting-started/env-configuration/>.

Avec `only_declared_models = true` (section `[openwebui]`), seuls les modeles declares
dans `[[models]]` (ici `qwen3:8b`) restent proposes : tout autre modele liste par Open WebUI
(Ollama dont `nomic-embed-text`, connexions, modeles du workspace) recoit une entree
`is_active = false`, qui le retire de la liste pour tous les comptes. Un modele tire plus tard
dans Ollama est desactive au `make configure` suivant. Le modele d'arene est coupe par
`[api."evaluations/config"]`. Desactiver `nomic-embed-text` ici ne touche pas aux embeddings
RAG, qui l'appellent directement.

### Skills

`[[skills]]` pointe un dossier : chaque `.md` (`SKILL.md`, `references/*.md`) devient un skill
Open WebUI nomme par son frontmatter (`name`, `description`), car Open WebUI 0.10 ne gere
qu'un contenu par skill. Les ids listes dans `meta.skillIds` d'un modele lui sont attaches :
le modele recoit leur liste (id + description) et charge le contenu dont il a besoin avec
l'outil integre `view_skill`, ce qui demande `function_calling = "native"`.

`openwebui/skills/oracle-elt/` aide a ecrire du SQL et du PL/SQL Oracle (26ai) qui compile :
regles et pieges du dialecte dans `SKILL.md`, puis erreurs ORA, syntaxe 23ai/26ai, patterns
de chargement ELT, performance, PL/SQL et dictionnaire en skills separes. Synthese filtree de
<https://github.com/oracle/skills> (licence UPL 1.0), completee sur ce que ce depot couvre peu.

Les generations auxiliaires (titre de conversation, tags, questions de suivi, autocompletion,
reformulation de requete) sont desactivees via `[api."tasks/config/update"]` : le modele ne
recoit que la question posee.

## Tools MCP

`src/vivia/mcp/server.py` monte un sous-serveur FastMCP par categorie d'outils
(`sanity.py`, `rendering.py`, `lineage.py`, `explore.py`, ...), sans namespace, en
streamable-HTTP sur `http://mcp:8000/mcp`. La logique de chaque outil vit dans
`src/vivia/tools/<categorie>/<outil>.py` (un fichier par outil) ; le module `mcp/<categorie>.py`
ne fait que l'enregistrer (`@mcp.tool` ou `mcp.tool(...)`). `sanity.py` expose `now`, `calc`,
`roll_dice` et `text_stats`, des outils jouets qui valident le mecanisme de tool call.
L'image embarque le code : apres modification, `docker compose build mcp` puis `up -d`.

### Tools qui rendent une vue

`chart`, `graph`, `sql_lineage` et `table` sont des MCP Apps : ils affichent une vue dans la conversation
au lieu de renvoyer du texte. Le tool porte un `resourceUri` en `ui://`, le serveur sert le
HTML correspondant en `text/html;profile=mcp-app`, et Open WebUI l'affiche dans une iframe
sandboxee, sous le message. Les documents sont dans `src/vivia/tools/rendering/views.py`.

- `chart` : barres groupees, lignes ou aires, axes a graduations rondes, survol, legende.
- `graph` : graphe dispose par forces, noeuds deplacables, groupes colores, aretes dirigees.
- `table` : tableau trie par colonne et filtrable, colonnes numeriques alignees a droite.

Trois contraintes de l'hote dictent la forme de ces documents :

- CSP `default-src 'none'` avec `script-src 'unsafe-inline'`. L'inline passe, le reseau non :
  tout est ecrit a la main, sans CDN ni `fetch`, ce qui evite d'avoir a declarer des domaines.
- L'iframe n'a pas `allow-same-origin` : origine opaque, donc ni `localStorage` ni cookie.
- Open WebUI repond `inline` a `ui/request-display-mode` : la vue s'affiche dans le fil, pas
  dans un panneau lateral, et sa hauteur est pilotee par `ui/notifications/size-changed`.
  Le panneau lateral reste celui des artifacts, alimente par un bloc ```html dans la reponse.

Le dialogue est du JSON-RPC 2.0 par `postMessage`. L'hote n'envoie `tool-input` puis
`tool-result` qu'apres avoir recu `ui/notifications/initialized` : le rendu s'accroche a
cette notification, jamais a `load`.

## Telemetrie

La filter function `openwebui/functions/phoenix_tracing.py` (installee par `make configure`)
emet une trace par tour de chat, dont la racine est un span CHAIN (question et reponse),
puis des spans enfants LLM pour chaque appel au modele et TOOL pour les executions d'outils, au format
OpenInference, vers `http://phoenix:6006/v1/traces`.
Traces visibles sur http://127.0.0.1:6006 (projet
`open-webui`), sans authentification : `PHOENIX_ENABLE_AUTH=false`, sinon l'ingestion OTLP
exigerait une cle d'API.

Les traces d'un meme chat portent `session.id` = `chat_id` : l'onglet Sessions de Phoenix
affiche la conversation comme la suite des input/output des spans racines de ses traces,
d'ou une trace par tour (avec un span racine commun a toute la conversation, la session ne
montrerait qu'une entree vide). Le `session_id` WebUI (connexion navigateur) n'est jamais
utilise pour regrouper les conversations. Les identifiants, derives du projet, de
l'utilisateur, du `chat_id` et du `message_id`, restent les memes apres un rechargement du
filtre : Phoenix ignore un tour deja recu.

Compatible avec le format `output` d'Open WebUI 0.10 a 0.13 : seuls les `function_call` du
message courant sont traces, avec leur `function_call_output` associe par `call_id`,
leurs arguments, leur statut et leurs horaires d'execution. Open WebUI < 0.13 ne date pas
les appels d'outils : le span outil est alors place entre la fin de l'appel LLM qui l'a
demande et le debut du suivant (`openwebui.tool.timing_source=llm_calls`,
`openwebui.tool.timing_available=false`), ce qui garde l'ordre LLM -> outil -> LLM ; sa duree
est majoree (elle inclut le traitement d'Open WebUI). Sans aucun repere, il a une duree nulle
a la fin du tour (`timing_source=none`).

`request` photographie le contexte et les schemas d'outils avant chaque appel au modele.
`stream` reassemble sa reponse (texte, raisonnement expose, appels d'outils), sa raison
de fin et ses compteurs de tokens. Les spans `llm.call.1`, `llm.call.2`, etc. suivent donc
la sequence LLM -> outils -> LLM, avec un input/output JSON et des messages structures
OpenInference. Les compteurs restent sur les spans LLM pour eviter de les compter deux fois.
Le raisonnement expose est distingue du texte de reponse dans les contenus `reasoning`.

Les snapshots d'entree refletent le hook `request`, avant les derniers ajustements du
routeur fournisseur (par exemple le system prompt du modele workspace). Les timestamps
mesurent du hook de requete a l'evenement terminal, sans inclure l'execution des outils.
Les usages recus apres l'evenement terminal sont conserves sans prolonger la duree.
Un flux sans evenement terminal reste incomplet (statut UNSET). Sans streaming, seul
l'appel final observable est renseigne depuis `outlet` ; sa duree inclut le post-traitement.
Sans hooks de capture (ancien historique ou appel `/api/chat/completed` seul), aucun
appel LLM intermediaire n'est invente. Un tour abandonne avant `outlet` n'est pas exporte.

Open WebUI 0.10 et 0.11 n'ont pas de hook `request` (il apparait en 0.12). Le filtre le
detecte (aucun appel a `request` pendant le tour) et se replie sur `inlet` et `stream` :
chaque nouvelle reponse du fournisseur ouvre un span LLM, qui commence a son premier
evenement recu. Le premier appel reprend l'entree vue par `inlet`
(`openwebui.llm.input_source=inlet_filter`, avant ajout des outils et du system prompt) ;
les suivants, apres execution des outils, n'ont pas d'entree
(`input_source=unavailable`). Sans streaming, l'appel unique est reconstruit depuis `inlet`
et `outlet`. Tours, outils, sorties, raisons de fin et compteurs de tokens sont identiques.
Ces versions n'enregistrent cote serveur que l'`output` du message assistant : `outlet` le
recoit avec un `content` vide, la reponse du tour est donc reprise des items `message` de
`output`, comme le fait Open WebUI 0.13.

Les spans sont emis dans `outlet`. `inlet` conserve le debut du tour dans le dictionnaire
`__metadata__` partage par les hooks inline ; a defaut, le timestamp du message est utilise.
Sans `chat_id`, chaque reponse obtient sa propre trace. Les anciennes traces ne sont pas
migrees : le regroupement s'applique aux tours emis avec cette version du filtre.

### Votes utilisateur

Chaque vote 👍/👎 devient une annotation Phoenix `user_rating` sur le span du tour note
(`up`/`down`, score 1/0, commentaire en explication), des qu'il est donne : la fonction
d'evenement `openwebui/functions/phoenix_feedback.py` (installee par `make configure`,
Open WebUI 0.10+) recoit `feedback.created` et `feedback.updated`, relit le vote et l'envoie
a Phoenix. Le filtre derivant ses identifiants par hachage de (projet, utilisateur,
`chat_id`, `message_id`), la fonction rejoue ce calcul sans etat partage ;
`tests/test_phoenix_feedback.py` echoue si les deux divergent, et `project_name` doit etre
le meme dans les valves des deux fonctions. Un vote donne avant que le tour soit exporte est
renvoye toutes les 5 s (6 essais). `identifier` vaut l'id du feedback : changer son vote ou
ajouter un commentaire met a jour l'annotation au lieu d'en empiler une. Phoenix est suppose
toujours actif : il n'y a pas de rattrapage pour des votes donnes pendant un arret.

### Latence

Les spans LLM portent `openwebui.llm.time_to_first_token_ms`, mesure du hook `request` au
premier fragment reellement emis par le modele — texte, raisonnement ou arguments d'outil.
Les evenements de role, d'usage ou d'ouverture d'item n'en sont pas un. OpenInference n'ayant
pas de convention de TTFT, l'attribut reste dans le namespace `openwebui`. Sans streaming,
ou avant Open WebUI 0.12 (pas de hook `request`, donc pas de debut d'appel), il est absent
plutot qu'estime.

## Exploration Oracle

`src/vivia/mcp/explore.py` expose 8 outils de lecture du DWH Oracle (compte lecture seule) :
`compile_sql`, `describe_table`, `search_objects`, `run_select`, `check_grain`, `column_stats`,
`find_usages`, `get_source`. La connexion (`src/vivia/oracle/client.py`, `python-oracledb` en
mode thin, pas de client Oracle a installer) lit `ORACLE_DSN`, `ORACLE_USER`, `ORACLE_PASSWORD`
(obligatoires), `ORACLE_CALL_TIMEOUT_MS` et `ORACLE_MAX_ROWS` (optionnels) dans l'environnement.

Aucun outil n'a besoin de plus que `SELECT` : pas d'`EXPLAIN PLAN`, pas de DDL/DML, pas
d'AWR/ASH/Diagnostics Pack. `compile_sql` et `run_select` valident le SQL libre par `sqlglot`
(dialecte `oracle`, une seule instruction `SELECT`/`WITH`) avant toute execution, templates
`#NOM#` masques puis restaures (`lineage.mask_templates`, partage avec le lineage SQL). Les
privileges optionnels (`DBMS_STATS.CONVERT_RAW_VALUE` pour `column_stats`, visibilite
d'`ALL_DEPENDENCIES`/`ALL_SOURCE` pour `find_usages`/`get_source`) se degradent proprement,
sans jamais faire planter l'outil.

```sh
docker compose -f docker/oracle-test/docker-compose.yml up -d   # Oracle Free, schemas zone+type
ORACLE_DSN=localhost:1521/FREEPDB1 ORACLE_USER=AGENT ORACLE_PASSWORD=Welcome_1 \
  uv run --group dev --group ops pytest tests/test_oracle_explore.py
```

Sans ce conteneur, `tests/test_oracle_explore.py` se saute proprement (`unittest.SkipTest`) ;
`test_sql_guard.py` et `test_oracle_identifiers.py` tournent sans base.

## Lineage SQL

`src/lineage/` extrait le lineage d'un script SQL Oracle avec [sqlglot](https://github.com/tobymao/sqlglot)
(parseur pur Python, dialecte Oracle). Sont lus `INSERT`, `MERGE`, `UPDATE` et `CREATE ... AS` ;
les CTE et sous-requetes sont traversees.

Un script qui ne contient qu'un `SELECT`, ecrit en table par l'outil ETL, est lu comme
`CREATE TABLE <cible> AS SELECT ...` : la cible est `-t/--target` (`target=` en Python), par
defaut le nom du fichier sans extension. Sans cible, un `SELECT` seul ne produit rien.

```sh
uv run vivia-lineage script.sql                    # niveau table : "SOURCE -> CIBLE"
uv run vivia-lineage script.sql -c                 # niveau colonne : "T.COL -> T.COL"
uv run vivia-lineage script.sql -c --md out.md     # + graphe Mermaid en Markdown
uv run vivia-lineage extract.sql -t '#SCH#.DST'    # SELECT seul ecrit dans #SCH#.DST
```

En Python, `lineage(sql, columns=False, schema=None, target=None)` renvoie `[{"source": ..., "target": ...}]`,
directement utilisable par le tool `graph`, et `to_mermaid(edges, columns)` le bloc Markdown correspondant.

- **Colonnes** : `sqlglot.lineage` remonte chaque colonne cible jusqu'aux colonnes des tables
  sources, a travers expressions, CTE, sous-requetes et `UNION` (correspondance par position avec
  la liste de colonnes de l'`INSERT`). Les constantes ne produisent pas d'arete. Sans schema, un
  `SELECT *` donne une colonne `*` ; `schema` (format sqlglot `{schema: {table: {col: type}}}`,
  templates ecrits `TPL#NOM#`) permet de le developper.
- **Templates** : `#NOM#` est masque en `TPL#NOM#` avant le parsing (Oracle accepte `#` dans un
  identifiant, sauf en tete) puis restitue : `#SCH#_STG.ORDERS` reste tel quel dans le graphe.
  Un template seul en position de colonne (`SELECT sysdate, #pndate#, ...`) est traite comme une
  valeur : il ne cree pas d'arete. Un template doit tenir dans un identifiant ou une valeur, pas
  remplacer un bout de requete (`#WHERE_CLAUSE#`).
- **Agent** : le tool MCP `sql_lineage(sql, columns, target)` affiche le graphe dans la conversation
  Open WebUI, avec la vue de `graph` (aucune ressource externe) ; en mode colonne, une couleur par
  table. Les aretes restent dans le resultat, lisibles par le modele.
- **Markdown** : `--md` ecrit un bloc ` ```mermaid ` (flowchart gauche-droite, une boite par table en
  mode colonne), rendu nativement par Open WebUI, GitHub ou VS Code, sans rien charger du web.

## Tests

```sh
make test   # tous les tests, sans appel LLM, sans conteneur, sans reseau
make lint
```
