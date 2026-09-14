# testhunch

[![CI](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml/badge.svg)](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/testhunch.svg)](https://pypi.org/project/testhunch/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/amazing-source/testhunch/blob/main/LICENSE)

**testhunch apprend de l'historique de votre CI quels tests un changement risque de casser, et les
lance en premier.**

Il lit les rapports JUnit XML que votre lanceur de tests produit déjà, ainsi que `git diff`, et
n'est donc lié à aucun langage ni framework. Il est testé sur de vrais rapports de pytest, Vitest,
Jest, Go (gotestsum), Java (Maven Surefire) et Rust (cargo-nextest).

> **Statut : pré-alpha.** Le pipeline de données (ingestion, stockage, rapports sur les tests
> instables et en échec) et un classement simple et explicable fonctionnent dès aujourd'hui, et le
> benchmark public le mesure ([résultats](#ce-qui-a-été-mesuré)). Le modèle appris est prévu dans la
> [feuille de route](https://github.com/amazing-source/testhunch/blob/main/ROADMAP.md).

## Pourquoi

La CI lance tous les tests à chaque push, quoi qu'on ait modifié. Plus une suite grossit, plus cela
veut dire de longues attentes, de grosses factures et des échecs aléatoires qui obligent à tout
relancer.

Apprendre de l'historique des tests lesquels comptent pour un changement a fait ses preuves à
grande échelle : chez Meta, [Predictive Test Selection](https://arxiv.org/abs/1810.05286) a divisé
par deux le coût des tests tout en détectant plus de 99,9 % des changements défectueux. Mais
aujourd'hui, on ne trouve cette capacité que sous ces formes :

| Où la trouver | Le problème |
|---|---|
| Systèmes internes de grandes entreprises | Jamais publiés |
| Services commerciaux (Develocity, CloudBees Smart Tests, Datadog) | Payants, souvent liés à un outil de build, et leurs promesses de précision sont invérifiables |
| Sélection basée sur Bazel | Oblige à migrer tout le build vers Bazel |
| Plugins open source | Un seul langage chacun, et surtout de l'analyse statique plutôt qu'un apprentissage sur l'historique |

testhunch se veut la version ouverte et indépendante du langage, et veut **prouver sa propre
précision publiquement** : chaque chiffre qu'il annonce est accompagné de la façon dont il a été
mesuré, et un mode fantôme (*shadow mode*) enregistre ce qu'il *aurait* sauté, avant qu'on lui
fasse confiance pour sauter quoi que ce soit.

## Fonctionnement

```mermaid
flowchart LR
    CI["job de CI<br/>lance les tests"] -->|JUnit XML + git diff| Ingest
    subgraph testhunch
        Ingest["analyse et normalisation<br/>(tout framework)"] --> Store[("historique<br/>SQLite ou Postgres")]
        Store --> Report["rapport : tests instables,<br/>lents, en échec"]
        Store --> Rank["classement des tests<br/>pour un changement"]
    end
    Rank -->|liste ordonnée + raisons| CI
```

1. Après votre job de tests, `testhunch ingest` enregistre le résultat de chaque test pour ce commit,
   ainsi que les fichiers modifiés.
2. `testhunch report` affiche les tests instables (réussis *et* échoués sur le même commit, y
   compris quand une relance réussit dans la même exécution), les tests lents et les tests en
   échec.
3. `testhunch prioritize` classe les tests selon les fichiers que vous avez modifiés, et explique
   pourquoi chacun arrive à cette place. Le score est celui qu'une étude comparative a retenu
   ([ADR 0014](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0014-the-ranking-study-measures-time-to-red-against-latest-failure.md),
   [ADR 0015](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0015-testhunch-ranks-by-latest-failure-per-unit-of-time.md)) :
   la récence des échecs du test, plus un bonus si le changement touche son propre fichier, le tout
   **divisé par sa durée habituelle**. Un test rapide qui peut échouer passe donc devant un test
   lent qui peut échouer autant. Tout est compté en builds, pas en exécutions : les nombreux jobs
   d'un même build ne pèsent qu'une fois.
4. **Mode fantôme** : avec `prioritize --record` avant les tests, le classement est enregistré
   pour ce commit ; tous les tests tournent quand même. Ensuite, `testhunch shadow` mesure ce
   qu'aurait manqué le fait de ne dépenser que 10 %, 25 % ou 50 % du temps de test attendu sur les
   tests les mieux classés :
   combien d'exécutions en échec seraient restées en échec, combien d'échecs auraient été vus, et
   la part de tests et de temps économisée. Un classement n'est jamais comparé à une exécution qu'il
   a déjà vue ([ADR 0006](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0006-shadow-mode-measures-misses-without-skipping.md)).

## Ce qui a été mesuré

Le classement a été rejoué sur de vrais historiques de CI : chaque exécution est classée uniquement
à partir de celles terminées avant elle, avec le vrai code de testhunch. Tous les chiffres, projet
par projet, y compris ceux où testhunch s'en sort mal, sont dans
[benchmarks/results](https://github.com/amazing-source/testhunch/blob/main/benchmarks/results/README.md).

Deux campagnes, avec deux classements différents : lisez bien lequel est mesuré.

### Le classement actuel, face à « les tests qui ont échoué récemment d'abord »

Le vrai risque de ce projet était que testhunch n'apporte rien de plus que cette stratégie très
simple. Une étude par ajouts successifs l'a mesuré ([ADR 0014](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0014-the-ranking-study-measures-time-to-red-against-latest-failure.md)) :
réglages sur 10 projets RTPTorrent, puis **une seule mesure** sur 10 autres projets, jamais regardés
pendant les réglages ([ADR 0013](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0013-development-projects-tune-held-out-projects-measure.md)).
Mesure principale : l'APFDc d'un job, tous ses échecs comptant pour une faute, c'est-à-dire la
vitesse à laquelle le build devient rouge. Détail : [held-out.md](https://github.com/amazing-source/testhunch/blob/main/benchmarks/results/study/held-out.md).

| Classement, sur les 10 projets mis de côté | APFDc | Temps de test pour rattraper 90 % des builds cassés |
|---|---:|---:|
| meilleur ordre possible, connu après coup | – | 49 % |
| **testhunch, classement actuel** | **0,840** | **58 %** |
| les tests qui ont échoué récemment d'abord | 0,812 | 66 % |
| testhunch 0.2.0 | 0,797 | 70 % |

Face à « échoué récemment », l'écart est de **+0,028** (intervalle de confiance à 95 % :
[+0,012, +0,051], meilleur sur 9 projets sur 10). La durée des tests apporte l'essentiel du gain :
+0,019 à elle seule, meilleure sur les 10 projets. Le bonus « le fichier du test est modifié » n'a
été retenu que de justesse, pendant les réglages : +0,012, intervalle [+0,000, +0,028], meilleur sur
6 projets sur 10 ([étape 3](https://github.com/amazing-source/testhunch/blob/main/benchmarks/results/study/step-3.md)).
Sur le banc d'essai mis de côté, le classement actuel obtient 0,980 contre 0,937 sur les 158 mutants
d'ollama/ollama, et fait jeu égal sur les 22 mutants de fastapi/fastapi.

### Les budgets, mesurés avec le classement de la 0.2.0

Ces chiffres-là datent de la phase 3 et n'ont **pas encore été refaits** avec le classement actuel ;
c'est la prochaine étape de la [feuille de route](https://github.com/amazing-source/testhunch/blob/main/ROADMAP.md).

**RTPTorrent**, 20 projets Java et 110 126 jobs Travis CI réels, résultats par classe de test. En ne
lançant que 25 % des classes connues (les inconnues tournent toujours), le projet médian :

- garde rouges **87 %** de ses jobs en échec (73 % pour le pire projet) ;
- lance **75 %** de ses classes en échec ;
- pour **44 %** de son temps de test (67 % pour le pire).

**Banc d'essai**, 200 commits de pallets/click (pytest) et 200 de spf13/cobra (Go), résultats par
test :

- Des mutants d'un seul jeton ont été glissés dans les lignes que chaque commit a changées. À 25 %
  des tests, la 0.2.0 rattrape **92 %** des mutants détectés sur click (pour 23 % du temps de test)
  et **84 %** sur cobra.
- La seule vraie régression de ces historiques, un commit de click annulé le jour même, est
  **manquée à tous les budgets** : les tests cassés n'avaient jamais échoué, et leur nom ne
  ressemble pas au fichier modifié.

## Démarrage rapide

```bash
# Dans un dépôt git, après avoir lancé vos tests avec une sortie JUnit :
uvx testhunch ingest junit.xml
uvx testhunch report
uvx testhunch prioritize --base origin/main
```

L'historique est conservé dans `.testhunch/history.db` (SQLite), sauf si vous indiquez une autre
base avec `--db` ou `TESTHUNCH_DATABASE_URL`, par exemple `postgresql://user@host/db`.

Sortie réelle, obtenue en ingérant l'exemple pytest de
[`tests/fixtures`](https://github.com/amazing-source/testhunch/tree/main/tests/fixtures/junit) sur
deux commits :

```text
$ testhunch prioritize --changed tests/test_sample.py --limit 4
   1.      1.46  tests.test_sample::test_parametrized[2]  (failed in the latest build; its file changed; takes about 0 ms)
   2.      1.46  tests.test_sample::test_errors_in_setup  (failed in the latest build; its file changed; takes about 0 ms)
   3.      1.46  tests.test_sample::test_errors_in_teardown  (failed in the latest build; its file changed; takes about 0 ms)
   4.      0.73  tests.test_sample::test_fails  (failed in the latest build; its file changed; takes about 1 ms)
```

Ces quatre tests ont le même historique ; seule leur durée les sépare, et `test_fails`, deux fois
plus lent, passe après. À score égal, l'ordre suit le commit sur le point d'être testé (`--commit`,
`HEAD` par défaut), pour ne pas toujours favoriser les mêmes tests.

### Obtenir du JUnit XML depuis votre lanceur de tests

| Lanceur | Commande |
|---|---|
| pytest | `pytest --junitxml=junit.xml` |
| Vitest | `vitest run --reporter=junit --outputFile=junit.xml` |
| Jest | `jest --reporters=default --reporters=jest-junit` (avec `JEST_JUNIT_ADD_FILE_ATTRIBUTE=true`) |
| Go | `gotestsum --junitfile junit.xml` |
| Maven (Surefire) | `mvn test` écrit un rapport par classe : `testhunch ingest 'target/surefire-reports/TEST-*.xml'` |
| cargo-nextest | `cargo nextest run --profile ci`, avec `[profile.ci.junit]` dans `.config/nextest.toml` (rapport dans `target/nextest/ci/junit.xml`) |

### Activer les relances

Un échec vu une seule fois peut venir d'un test instable. Quand le lanceur relance les tests en
échec, testhunch sait si un échec s'est reproduit à chaque tentative (échec **confirmé**) ou si le
test a fini par passer (test instable), et le mode fantôme compte les échecs confirmés à part
([ADR 0008](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0008-failures-are-confirmed-by-retries.md)).
Sans relances, le rapport le signale : ses chiffres peuvent alors paraître meilleurs que la réalité.

| Lanceur | Relancer deux fois les tests en échec |
|---|---|
| pytest | `pip install pytest-rerunfailures`, puis `pytest --reruns 2 --junitxml=junit.xml` |
| Maven (Surefire) | `mvn test -Dsurefire.rerunFailingTestsCount=2` |
| cargo-nextest | `retries = 2` dans le profil, par exemple `[profile.ci]` de `.config/nextest.toml` |
| Go | `gotestsum --junitfile junit.xml --rerun-fails=2 --packages ./...` |

Chaque ligne est vérifiée par un vrai rapport dans `tests/fixtures/junit` (pytest-rerunfailures
16.6.1, Surefire 3.6.0, cargo-nextest 0.9.144, gotestsum 1.13.0). Les relances de Vitest et de Jest
ne le sont pas encore.

### Dans GitHub Actions

L'Action de ce dépôt classe les tests avant qu'ils tournent, enregistre leurs résultats ensuite, et
écrit un résumé dans la page du job :

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0 # testhunch compare avec la branche de base de la pull request
- id: testhunch
  uses: amazing-source/testhunch@v0.2.0
  with:
    command: prioritize
    database-url: ${{ secrets.TESTHUNCH_DATABASE_URL }}
- run: pytest --junitxml=junit.xml
- if: ${{ !cancelled() }}
  uses: amazing-source/testhunch@v0.2.0
  with:
    command: ingest
    reports: junit.xml
    database-url: ${{ secrets.TESTHUNCH_DATABASE_URL }}
```

| Entrée | Rôle |
|---|---|
| `command` | `prioritize` avant les tests, `ingest` après |
| `reports` | Pour `ingest` : fichiers JUnit XML ou motifs glob, un par ligne |
| `base` | Référence à comparer pour trouver les fichiers modifiés ; par défaut, la branche de base de la pull request |
| `database-url` | Où garder l'historique ; par défaut un fichier SQLite qui disparaît à la fin du job |
| `last` | Pour `ingest` : nombre d'exécutions récentes couvertes par les résumés (50). Le classement, lui, apprend de tous les builds enregistrés |
| `summary-limit` | Nombre de tests affichés dans le résumé de `prioritize` (20) |
| `record` | Pour `prioritize` : enregistrer le classement pour le mode fantôme (`true` par défaut) |

`prioritize` a deux sorties : `ranking-json`, le chemin d'un fichier JSON avec le score et les
raisons de chaque test, et `ranking-keys`, le chemin d'un fichier avec une clé de test par ligne, du
plus au moins susceptible d'échouer.

Le mode fantôme est actif par défaut : `prioritize` enregistre son classement, tous les tests
tournent, et le résumé d'`ingest` indique ce qu'aurait manqué le fait de ne lancer que les tests les
mieux classés. Rien n'est jamais sauté.

Sans `database-url`, l'historique ne survit pas d'une exécution de CI à l'autre : pour un vrai
usage, passez l'URL d'une base Postgres depuis un secret, ou envoyez les rapports à une API
auto-hébergée (ci-dessous). `@v0.2.0` exécute testhunch 0.2.0 ; pour une garantie plus forte qu'un tag, utilisez le SHA de
son commit.

### Sauter vraiment des tests

Une fois que le rapport du mode fantôme montre ce qu'un budget aurait manqué sur votre historique,
`testhunch select` produit la sélection correspondante. Elle **laisse de côté** les tests connus
classés sous le budget ; tout le reste tourne, y compris les tests que testhunch n'a encore jamais
vus ([ADR 0007](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0007-selections-leave-out-known-low-ranked-tests.md)).
La coupure est exactement celle du mode fantôme.

**`--budget 25%`, c'est un quart du temps de test attendu, pas un quart des tests**
([ADR 0017](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0017-a-budget-is-a-share-of-the-test-time.md)).
Le classement met volontairement les tests rapides devant : un quart des tests coûterait bien moins
d'un quart du temps, et vous ne contrôleriez pas ce que votre CI paie vraiment. Le budget garde le
plus long début du classement qui tienne dans le temps imparti — jamais un autre sous-ensemble mieux
rempli, car l'ordre du classement est ce qu'il promet. Les tests que testhunch n'a jamais vus
tournent **en plus** du budget : rien n'a mesuré leur durée. `--budget-unit tests` revient à
l'ancien sens, une part du nombre de tests connus, pour un lanceur qui ne rapporte pas de durée
utilisable.

```bash
# pytest : testhunch doit être installé dans l'environnement des tests
testhunch select --budget 25% --runner pytest --base origin/main > skip.txt
pytest -p testhunch.pytest_plugin --testhunch-skip=skip.txt

# Go : -skip vise des noms de tests dans tous les paquets, testhunch a donc besoin de la liste actuelle
go test -list '.*' ./... > go-tests.txt
go test ./... -skip "$(testhunch select --budget 25% --runner go --go-test-list go-tests.txt --base origin/main)"
```

Avec Go, certains tests classés sous le budget tournent quand même, parce que `-skip` ne pourrait
pas les écarter seuls : un test dont le nom existe aussi dans un autre paquet, un test parent dont
un sous-test est gardé, et tous les tests d'un paquet dont un fichier `_test.go` a changé (un
sous-test ajouté serait écarté avec son parent). `select` indique combien.

```bash
# Maven Surefire
mvn test "-Dtest=$(testhunch select --budget 25% --runner surefire --base origin/main)"

# cargo-nextest
cargo nextest run -E "$(testhunch select --budget 25% --runner nextest --base origin/main)"
```

Avec Surefire, une méthode paramétrée n'est écartée que si toutes ses invocations connues le sont,
et rien n'est écarté dans une classe dont le fichier source a changé. Attention : `-Dtest` remplace
les `includes` et `excludes` configurés dans le `pom.xml`, donc des tests normalement exclus (des
tests d'intégration, par exemple) tourneraient. Vérifié avec Surefire 3.6.0 et JUnit 6 sur un
projet à un seul module.

Avec cargo-nextest, chaque test est visé par son binaire et son nom exacts : tous les tests sous le
budget sont écartés. Vérifié avec cargo-nextest 0.9.144.

```bash
# Vitest : -t vise des noms complets dans tous les fichiers, testhunch a donc besoin de la liste actuelle
npx vitest list --json=vitest-list.json --no-static-parse
npx vitest run -t "$(testhunch select --budget 25% --runner vitest --vitest-list vitest-list.json --base origin/main)"
```

Avec Vitest, un test n'est écarté que si son nom complet n'apparaît qu'une fois dans la liste
actuelle ; `--no-static-parse` fait exécuter les fichiers pour lister, sinon un `test.each` y figure
sous son modèle (`price %i is positive`) et non sous ses vrais noms. Vitest compte les tests écartés
comme « skipped » dans son rapport JUnit. Vérifié avec Vitest 5.0.0.

```bash
# Jest : le rapport doit indiquer le fichier de chaque test
export JEST_JUNIT_ADD_FILE_ATTRIBUTE=true
npx jest --reporters=default --reporters=jest-junit \
  --testPathIgnorePatterns "$(testhunch select --budget 25% --runner jest --base origin/main)"
```

Jest ne sait pas lister les noms de tests sans les lancer : un test homonyme dans un autre fichier ne
peut donc pas être exclu du doute, et la sélection écarte des **fichiers entiers**. Un fichier n'est
écarté que si tous ses tests connus sont sous le budget et qu'il n'a pas changé. Le motif remplace
les `testPathIgnorePatterns` de votre configuration ; il reprend `/node_modules/`, la valeur par
défaut de Jest. Vérifié avec Jest 30.5.1 et jest-junit 17.0.0.

Sur environ un build sur quatre, `select` ne laisse rien de côté : c'est un *learning run*, qui lance
toute la suite et enregistre le classement, pour que le mode fantôme continue de mesurer ce que la
sélection manque ([ADR 0009](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0009-learning-runs-keep-measuring-while-skipping.md)).
Le tirage dépend du commit : tous les jobs d'un même build prennent la même décision. Réglez la part
avec `--learning-runs` (25 % par défaut, `0%` pour désactiver).

Deux règles pour que ce soit sûr :

- **Gardez un filet de sécurité** : ne sautez des tests que sur les pull requests, et lancez toute la
  suite sur la branche principale après chaque fusion, pour rattraper ce qu'une sélection a laissé
  passer.
- **N'enregistrez pas vous-même le classement d'un build qui saute des tests** (pas de
  `prioritize --record`, et `record: false` dans l'Action) : les tests sautés n'ont pas de résultat,
  et le rapport du mode fantôme paraîtrait meilleur que la réalité. `select` n'enregistre que ses
  learning runs.

Chaque lanceur pris en charge (pytest, Go, Maven Surefire, cargo-nextest, Vitest, Jest) est vérifié
par un vrai lancement sélectif dans `tests/fixtures/select` : les tests lancés sont exactement tous
les tests moins ceux que testhunch dit écarter.

### Héberger l'API soi-même

```bash
docker compose up --build        # Postgres, les migrations, puis l'API sur :8000
curl http://localhost:8000/readyz
```

| Endpoint | Rôle |
|---|---|
| `POST /v1/runs` | Envoyer des rapports : fichiers `reports` en multipart et JSON `metadata` (`repo`, `commit_sha`, et en option `branch`, `base_sha`, `changes`) |
| `GET /v1/report?repo=owner/name` | Tests instables, les plus lents et en échec |
| `POST /v1/prioritize` | Tests classés pour `repo` et `changed_paths` ; `commit_sha` départage les scores égaux, `limit` tronque |
| `GET /healthz`, `GET /readyz` | Vivacité, et disponibilité (base de données comprise) |

Définissez `TESTHUNCH_API_TOKEN` pour exiger `Authorization: Bearer <token>` sur `/v1`. Sans jeton,
l'API est ouverte, ce qui n'est acceptable que sur votre propre machine.

## Développement

```bash
uv sync --all-extras
uv run pytest                       # tests de contrat sur SQLite ; ceux sur Postgres sont ignorés
uv run ruff check . && uv run ruff format --check . && uv run mypy

# Lancer aussi les tests de contrat du stockage sur Postgres :
docker compose up -d postgres
TESTHUNCH_TEST_POSTGRES_URL=postgresql://testhunch:testhunch@127.0.0.1:5432/testhunch uv run pytest
```

Utilisez `127.0.0.1` et non `localhost` : Compose ne publie le port qu'en IPv4, et sous Windows
`localhost` essaie d'abord `::1`, où chaque connexion reste bloquée jusqu'à expiration du délai.

Les décisions de conception sont consignées dans [`docs/adr`](https://github.com/amazing-source/testhunch/tree/main/docs/adr). La couche de stockage est
une seule implémentation SQL, exécutée sur SQLite comme sur Postgres, et chaque test de stockage
tourne sur les deux.

## Licence

[Apache-2.0](https://github.com/amazing-source/testhunch/blob/main/LICENSE)
