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

## Telemetrie

La filter function `openwebui/functions/phoenix_tracing.py` (installee par `make configure`)
emet une trace par conversation, un span CHAIN par tour de chat et un span TOOL enfant
par appel d'outil, au format OpenInference, vers `http://phoenix:6006/v1/traces`.
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

Les spans sont emis dans `outlet`. `inlet` conserve le debut du tour dans le dictionnaire
`__metadata__` partage par les hooks inline ; a defaut, le timestamp du message est utilise.
Sans `chat_id`, chaque reponse obtient sa propre trace. Les anciennes traces ne sont pas
migrees : le regroupement s'applique aux tours emis avec cette version du filtre.

Tests du filtre (exporteur en memoire, sans appel LLM ni envoi a Phoenix) :

```sh
uv run --with arize-phoenix-otel --with openinference-semantic-conventions \
  python -m unittest discover -s tests -v
```
