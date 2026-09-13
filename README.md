# testhunch

[![CI](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml/badge.svg)](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**testhunch apprend de l'historique de votre CI quels tests un changement risque de casser, et les
lance en premier.**

Il lit les rapports JUnit XML que votre lanceur de tests produit déjà, ainsi que `git diff`, et
n'est donc lié à aucun langage ni framework. Il est testé sur de vrais rapports de pytest, Vitest et
Jest ; Go (gotestsum), JUnit (Surefire) et cargo-nextest sont les prochains sur la
[feuille de route](ROADMAP.md).

> **Statut : pré-alpha.** Le pipeline de données (ingestion, stockage, rapports sur les tests
> instables et en échec) et un classement de référence simple et explicable fonctionnent dès
> aujourd'hui. Le modèle appris et le benchmark public qui prouvera son efficacité sont prévus dans
> la [feuille de route](ROADMAP.md). Aucune promesse de précision n'est faite tant que ce benchmark
> n'existe pas.

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
2. `testhunch report` affiche les tests instables (réussis *et* échoués sur le même commit), les
   tests lents et les tests en échec.
3. `testhunch prioritize` classe les tests selon les fichiers que vous avez modifiés, et explique
   pourquoi chacun arrive à cette place.

## Démarrage rapide

```bash
# Dans un dépôt git, après avoir lancé vos tests avec une sortie JUnit :
uvx --from git+https://github.com/amazing-source/testhunch testhunch ingest junit.xml
uvx --from git+https://github.com/amazing-source/testhunch testhunch report
uvx --from git+https://github.com/amazing-source/testhunch testhunch prioritize --base origin/main
```

L'historique est conservé dans `.testhunch/history.db` (SQLite), sauf si vous indiquez une autre
base avec `--db` ou `TESTHUNCH_DATABASE_URL`, par exemple `postgresql://user@host/db`.

Sortie réelle, obtenue avec deux exécutions de l'exemple pytest de
[`tests/fixtures`](tests/fixtures/junit) :

```text
$ testhunch prioritize --changed src/sample/parametrized.py --limit 3
   1.  4.000  tests.test_sample::test_parametrized[2]  (matches changed file parametrized; failed in the latest run; failed 2 of 2 runs)
   2.  2.000  tests.test_sample::test_errors_in_setup  (failed in the latest run; failed 2 of 2 runs)
   3.  2.000  tests.test_sample::test_errors_in_teardown  (failed in the latest run; failed 2 of 2 runs)
```

### Obtenir du JUnit XML depuis votre lanceur de tests

| Lanceur | Commande |
|---|---|
| pytest | `pytest --junitxml=junit.xml` |
| Vitest | `vitest run --reporter=junit --outputFile=junit.xml` |
| Jest | `jest --reporters=default --reporters=jest-junit` (avec `JEST_JUNIT_ADD_FILE_ATTRIBUTE=true`) |

### Dans GitHub Actions

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0 # testhunch a besoin de l'historique pour comparer avec la branche de base
- run: pytest --junitxml=junit.xml
- if: ${{ !cancelled() }}
  run: uvx --from git+https://github.com/amazing-source/testhunch testhunch ingest junit.xml --base origin/main
```

Un fichier SQLite local ne survit pas d'une exécution de CI à l'autre. Pour un vrai usage en CI,
faites pointer `TESTHUNCH_DATABASE_URL` vers Postgres, ou envoyez les rapports à une API
auto-hébergée (ci-dessous).

### Héberger l'API soi-même

```bash
docker compose up --build        # Postgres, les migrations, puis l'API sur :8000
curl http://localhost:8000/readyz
```

| Endpoint | Rôle |
|---|---|
| `POST /v1/runs` | Envoyer des rapports : fichiers `reports` en multipart et JSON `metadata` (`repo`, `commit_sha`, et en option `branch`, `base_sha`, `changes`) |
| `GET /v1/report?repo=owner/name` | Tests instables, les plus lents et en échec |
| `POST /v1/prioritize` | Tests classés pour `repo` et `changed_paths` |
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

Les décisions de conception sont consignées dans [`docs/adr`](docs/adr). La couche de stockage est
une seule implémentation SQL, exécutée sur SQLite comme sur Postgres, et chaque test de stockage
tourne sur les deux.

## Licence

[Apache-2.0](LICENSE)
