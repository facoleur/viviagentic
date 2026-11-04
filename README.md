# vivia

Stack LLM locale : Ollama + Open WebUI + serveur MCP + Arize Phoenix.
Seul Open WebUI est publie (`:3000`) ; Phoenix est sur la loopback (`127.0.0.1:6006`),
Ollama et le serveur MCP restent sur le reseau interne du projet.

## Demarrage

```sh
cp .env.example .env && $EDITOR .env   # WEBUI_SECRET_KEY, VIVIA_MODEL
uv sync
make up                                # pull du modele inclus (service ollama-pull)
make configure                         # applique vivia.toml a Open WebUI
```

## Configuration

Tout passe par `vivia.toml` : admin, utilisateurs, groupes, permissions par defaut,
modele par defaut, tool servers MCP, filter functions. `make configure` est idempotent,
rejouable a volonte, et ne demande jamais de passer par l'UI.

Chaque table `[api."<chemin>"]` est POSTee telle quelle sur `/api/v1/<chemin>` : ajouter ou
retirer un reglage ne demande aucune modification de code, et n'importe quel endpoint de
configuration est atteignable. Seules `[[groups]]` et `[[functions]]` ont un schema fixe.
Les noms de cles sont documentes dans
<https://docs.openwebui.com/getting-started/env-configuration/>.

Les generations auxiliaires (titre de conversation, tags, questions de suivi, autocompletion,
reformulation de requete) sont desactivees via `[api."tasks/config/update"]` : le modele ne
recoit que la question posee.

## Tools MCP

`src/vivia/mcp.py` expose `now`, `calc`, `roll_dice` et `text_stats` en streamable-HTTP
sur `http://mcp:8000/mcp`. Ajouter un tool = une fonction decoree `@mcp.tool`.
L'image embarque le code : apres modification, `docker compose build mcp` puis `up -d`.

### Tools qui rendent une vue

`chart`, `graph` et `table` sont des MCP Apps : ils affichent une vue dans la conversation
au lieu de renvoyer du texte. Le tool porte un `resourceUri` en `ui://`, le serveur sert le
HTML correspondant en `text/html;profile=mcp-app`, et Open WebUI l'affiche dans une iframe
sandboxee, sous le message. Les documents sont dans `src/vivia/ui.py`.

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
emet une trace par conversation, un span CHAIN par tour de chat, puis des spans enfants
LLM pour chaque appel au modele et TOOL pour les executions d'outils, au format
OpenInference, vers `http://phoenix:6006/v1/traces`.
Traces visibles sur http://127.0.0.1:6006 (projet
`open-webui`), sans authentification : `PHOENIX_ENABLE_AUTH=false`, sinon l'ingestion OTLP
exigerait une cle d'API.

Les identifiants derives du projet, de l'utilisateur et du `chat_id` conservent la meme
trace apres un rechargement du filtre. Le span racine `open-webui.conversation` est un
point de rattachement de duree nulle : Open WebUI ne fournit pas d'evenement de fermeture
definitive d'un chat. Les spans des tours et des outils portent leurs propres durees.
Phoenix ignore les spans deja recus avec le meme identifiant, y compris la racine
reenvoyee a chaque tour. `session.id` reste egal au `chat_id` ; le `session_id` WebUI
(connexion navigateur) n'est jamais utilise pour regrouper les conversations.

Compatible avec le format `output` d'Open WebUI 0.13 : seuls les `function_call` du
message courant sont traces, avec leur `function_call_output` associe par `call_id`,
leurs arguments, leur statut et leurs horaires d'execution. Sans horaires disponibles,
le span outil a une duree nulle et `openwebui.tool.timing_available=false`.

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

Les spans sont emis dans `outlet`. `inlet` conserve le debut du tour dans le dictionnaire
`__metadata__` partage par les hooks inline ; a defaut, le timestamp du message est utilise.
Sans `chat_id`, chaque reponse obtient sa propre trace. Les anciennes traces ne sont pas
migrees : le regroupement s'applique aux tours emis avec cette version du filtre.

### Votes utilisateur

`make annotate` (`src/vivia/annotate.py`) reporte les votes 👍/👎 d'Open WebUI en annotations
Phoenix, sur le span du tour note. Le filtre derivant ses identifiants par hachage de
(projet, utilisateur, `chat_id`, `message_id`), le script rejoue ce calcul depuis l'exterieur :
un vote laisse apres coup retrouve son span sans qu'aucun etat n'ait ete conserve.
`identifier` vaut l'id du feedback, donc relancer la commande met a jour au lieu d'empiler.
`tests/test_annotate.py` echoue si le filtre et le script divergent sur ce calcul.

### Latence

Les spans LLM portent `openwebui.llm.time_to_first_token_ms`, mesure du hook `request` au
premier fragment reellement emis par le modele — texte, raisonnement ou arguments d'outil.
Les evenements de role, d'usage ou d'ouverture d'item n'en sont pas un. OpenInference n'ayant
pas de convention de TTFT, l'attribut reste dans le namespace `openwebui`. Sans streaming,
il est absent plutot qu'estime.

## Lineage SQL

`src/lineage/` extrait le lineage d'un script SQL Oracle avec [sqlglot](https://github.com/tobymao/sqlglot)
(parseur pur Python, dialecte Oracle). Sont lus `INSERT`, `MERGE`, `UPDATE` et `CREATE ... AS` ;
les CTE et sous-requetes sont traversees, les `SELECT` seuls ne produisent rien.

```sh
uv run vivia-lineage script.sql                    # niveau table : "SOURCE -> CIBLE"
uv run vivia-lineage script.sql -c                 # niveau colonne : "T.COL -> T.COL"
uv run vivia-lineage script.sql -c --html out.html # + page HTML du graphe
```

En Python, `lineage(sql, columns=False, schema=None)` renvoie `[{"source": ..., "target": ...}]`,
directement utilisable par le tool `graph`, et `to_html(edges, columns)` la page correspondante.

- **Colonnes** : `sqlglot.lineage` remonte chaque colonne cible jusqu'aux colonnes des tables
  sources, a travers expressions, CTE, sous-requetes et `UNION` (correspondance par position avec
  la liste de colonnes de l'`INSERT`). Les constantes ne produisent pas d'arete. Sans schema, un
  `SELECT *` donne une colonne `*` ; `schema` (format sqlglot `{schema: {table: {col: type}}}`,
  templates ecrits `TPL#NOM#`) permet de le developper.
- **Templates** : `#NOM#` est masque en `TPL#NOM#` avant le parsing (Oracle accepte `#` dans un
  identifiant, sauf en tete) puis restitue : `#SCH#_STG.ORDERS` reste tel quel dans le graphe.
  Un template doit donc tenir dans un identifiant ou une valeur, pas remplacer un bout de requete.
- **HTML** : page autonome, rendue par Mermaid (charge depuis jsDelivr) en flowchart gauche-droite ;
  en mode colonne, une boite par table contenant ses colonnes.

## Tests

```sh
make test   # tous les tests, sans appel LLM, sans conteneur, sans reseau
make lint
```
