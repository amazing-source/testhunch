# testhunch

[![CI](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml/badge.svg)](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/testhunch.svg)](https://pypi.org/project/testhunch/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/amazing-source/testhunch/blob/main/LICENSE)

**testhunch apprend de l'historique de votre CI quels tests un changement risque de casser, et les
lance en premier.**

Il lit les rapports JUnit XML que votre lanceur de tests produit déjà, ainsi que `git diff`, et n'est
donc lié à aucun langage ni framework. Il est testé sur de vrais rapports de pytest, Vitest, Jest, Go
(gotestsum), Java (Maven Surefire) et Rust (cargo-nextest).

📚 **[La documentation](https://testhunch.mintlify.app)** : prise en main, intégration en CI, les six
lanceurs, déploiement et référence.

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

1. `testhunch ingest` enregistre le résultat de chaque test pour ce commit, et les fichiers modifiés.
2. `testhunch report` affiche les tests instables, lents et en échec.
3. `testhunch prioritize` classe les tests selon ce que vous avez modifié, et explique chaque place.
4. `testhunch shadow` mesure ce qu'un budget *aurait* manqué, sans rien sauter.

Le score est celui qu'une étude comparative a retenu : la récence des échecs du test comptée en
builds, plus un bonus si le changement touche son propre fichier, le tout **divisé par sa durée
habituelle**. Le détail est sur
[la page du classement](https://testhunch.mintlify.app/docs/concepts/classement).

## Ce qui a été mesuré

Le classement a été rejoué sur de vrais historiques de CI : chaque exécution est classée uniquement
à partir de celles terminées avant elle, avec le vrai code de testhunch. **Ces chiffres sont ceux de
la 0.5.0**, celle que `uvx testhunch` et `@v0.5.0` installent. Tous les résultats, projet par projet,
y compris ceux où testhunch s'en sort mal, sont dans
[benchmarks/results](https://github.com/amazing-source/testhunch/blob/main/benchmarks/results/README.md).

Réglages sur 10 projets RTPTorrent, puis **une seule mesure** sur 10 autres projets, jamais regardés
pendant les réglages ([ADR 0013](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0013-development-projects-tune-held-out-projects-measure.md)).
Mesure principale : l'APFDc d'un job, tous ses échecs comptant pour une faute, c'est-à-dire la
vitesse à laquelle le build devient rouge. Détail : [held-out.md](https://github.com/amazing-source/testhunch/blob/main/benchmarks/results/study/held-out.md).

| Classement, sur les 10 projets mis de côté | APFDc | Temps de test pour rattraper 90 % des builds cassés |
|---|---:|---:|
| meilleur ordre possible, connu après coup | – | 49 % |
| **testhunch, classement actuel** | **0,840** | **58 %** |
| les tests qui ont échoué récemment d'abord | 0,812 | 66 % |
| testhunch 0.2.0 | 0,797 | 70 % |

Face à « échoué récemment », l'écart est de **+0,028**, intervalle de confiance à 95 %
[+0,012, +0,051], meilleur sur 9 projets sur 10. La durée des tests apporte l'essentiel de ce gain.

### L'angle mort : un test qui n'a jamais échoué

Ces moyennes mélangent deux régimes, et un seul est bon. Découpées selon que le test en échec avait
déjà échoué ou non ([détail](https://github.com/amazing-source/testhunch/blob/main/benchmarks/results/study/first-failures.md)),
position du premier test en échec dans l'ordre, plus bas étant meilleur :

| | A déjà échoué (94 % des jobs) | N'a jamais échoué (6 %) |
|---|---:|---:|
| testhunch | **0,124** | 0,692 |
| aléatoire | 0,460 | **0,472** |

**Sur un test qui n'a jamais échoué, testhunch fait pire que le hasard.** Ce n'est pas de la
malchance : un classement fondé sur la récence des échecs relègue par construction ce qui n'a jamais
cassé, donc il cherche au mauvais endroit. C'est exactement le cas d'un bug écrit dans du code neuf.

C'est pourquoi le filet de sécurité, ne sauter des tests que sur les pull requests et relancer toute
la suite sur la branche principale, n'est pas une précaution de principe
([ADR 0018](https://github.com/amazing-source/testhunch/blob/main/docs/adr/0018-first-failures-are-a-guardrail-not-an-average.md),
[le filet](https://testhunch.mintlify.app/docs/ci/filet-de-securite)).

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
`HEAD` par défaut), pour ne pas toujours favoriser les mêmes tests. Un autre commit présentera donc
les ex aequo dans un autre ordre.

## Aller plus loin

| | |
|---|---|
| [Prise en main](https://testhunch.mintlify.app/docs/demarrer) | Installer, ingérer, classer, et le mode fantôme |
| [En CI](https://testhunch.mintlify.app/docs/ci/action) | L'Action GitHub et le filet de sécurité |
| [Sauter des tests](https://testhunch.mintlify.app/docs/sauter/index) | Les budgets et les six lanceurs, avec les limites de chacun |
| [Déployer](https://testhunch.mintlify.app/docs/deployer/docker) | Docker, Postgres et l'API HTTP |
| [Référence](https://testhunch.mintlify.app/docs/reference/cli) | Les commandes, leurs options, les variables d'environnement |

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
