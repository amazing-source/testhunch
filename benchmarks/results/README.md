# Résultats du benchmark

Mesurés le 14 septembre 2026, avec le classement de référence de testhunch 0.2.0 : affinité de nom
avec les fichiers modifiés, récence des échecs, taux d'échec sur les 50 dernières exécutions. Aucun
modèle appris. Chaque chiffre vient d'un rejeu où chaque exécution est classée uniquement à partir
des exécutions terminées avant elle, avec le vrai code d'ingestion et de classement de testhunch.

Les pages générées, en anglais, donnent le détail par projet :

- [RTPTorrent](rtptorrent/README.md) : 20 projets Java, historique réel de Travis CI.
- [Banc d'essai](harness/) : pallets/click (pytest) et spf13/cobra (Go), commit par commit et avec
  mutants.

Les budgets sont ceux du mode fantôme (ADR 0006) : ne lancer que les 10 %, 25 % ou 50 % de tests
connus les mieux classés. Les tests que le classement ne connaît pas tournent toujours, donc un peu
plus que le budget tourne.

## RTPTorrent : 20 projets Java, 110 126 jobs Travis CI

Méthode : [ADR 0010](../../docs/adr/0010-benchmark-replays-rtptorrent-in-build-order.md). Données :
RTPTorrent 1.1 (Mattis et al., MSR 2020, [doi:10.5281/zenodo.4046180](https://doi.org/10.5281/zenodo.4046180),
CC-BY-4.0). Chaque fichier lu est vérifié par son CRC-32 et listé dans le JSON du projet. Les
résultats sont **par classe de test**, sans relances, et les jobs ont été rejoués dans l'ordre de
leurs identifiants.

| Budget | Jobs en échec rattrapés (médiane des projets) | Classes en échec lancées (médiane) | Temps de test lancé (médiane) |
|---:|---:|---:|---:|
| 10 % | 78 % (le pire projet : 60 %) | 59 % | 22 % (le pire : 62 %) |
| 25 % | 87 % (le pire : 73 %) | 75 % | 44 % (le pire : 67 %) |
| 50 % | 94 % (le pire : 82 %) | 91 % | 69 % (le pire : 85 %) |

Un job est rattrapé quand au moins une de ses classes en échec tourne : le build reste rouge
(rappel par changement). Les classes en échec lancées sont le rappel par test. Le temps lancé est la
part de la durée des classes qui aurait tourné ; le reste est le temps économisé.

**Comme ordre d'exécution** (APFD, la mesure du papier RTPTorrent, calculée sur les 6 189 jobs en
échec que couvrent les ordres des auteurs du jeu de données) :

| Ordre | APFD moyen |
|---|---:|
| optimal (connu après coup, borne haute) | 0,926 |
| **recently-failed** (les tests qui ont échoué récemment d'abord) | **0,847** |
| **testhunch** | **0,832** |
| matrice fichiers × tests, naïve | 0,625 |
| matrice fichiers × tests, probabilité conditionnelle | 0,527 |
| aléatoire | 0,499 |
| ordre d'origine | 0,314 |

### Là où testhunch s'en sort mal

- **Recently-failed fait mieux au total** et devance testhunch sur 10 des 20 projets. testhunch
  fait mieux que l'ordre d'origine et l'aléatoire sur les 20 projets, et que les deux matrices des
  auteurs sur 19 et 20 projets.
- **Le rappel par test est faible sur plusieurs projets** : à 10 %, 32 % des classes en échec
  tournent sur LittleProxy et HikariCP, 19 à 20 % sur jade4j, dynjs, DSpace et wicket-bootstrap.
  Le build reste souvent rouge quand même, parce qu'une seule classe en échec suffit.
- **SonarQube** : à 10 %, 62 % du temps de test tourne encore. La fenêtre d'historique compte les
  50 dernières exécutions, et non les 50 derniers builds. Or SonarQube lance beaucoup de jobs par
  build : beaucoup de classes restent inconnues et tournent toujours. De plus, 32 321 de ses 53 307
  jobs n'ont aucun commit associé dans le jeu de données, donc aucun fichier modifié connu.

### Limites

- Des classes Java, des builds Travis CI que le papier date « de 2007 à 2016 », sans relances : un
  échec instable ne se distingue pas d'un vrai échec.
- Le JSON de SonarQube indique `"commit": null`, car `git rev-parse` a échoué à la fin de ce rejeu
  de 53 minutes, pendant que la machine manquait de mémoire. Les 20 projets ont été lancés par le
  même script, depuis un worktree détaché au commit `bc417f1`, dont le journal affiche ce commit au
  démarrage. Les 19 autres JSON l'enregistrent.

## Banc d'essai : click et cobra, commit par commit

Méthode : [ADR 0011](../../docs/adr/0011-harness-replays-real-projects-in-pinned-containers.md) et
[ADR 0012](../../docs/adr/0012-mutants-seed-faults-in-the-lines-a-commit-changed.md). Les 200
derniers commits de premier parent de [pallets/click](https://github.com/pallets/click) (pytest,
jusqu'à `6aabf099`) et de [spf13/cobra](https://github.com/spf13/cobra) (Go, jusqu'à `adbc8813`)
ont chacun lancé leur suite complète dans un conteneur. Les résultats sont **par test**, relancés
une fois en cas d'échec. Les 400 commits se sont tous construits.

### Historique réel

| Projet | Commits évalués | Commits en échec confirmé | Rattrapés à 10 / 25 / 50 % | Tests lancés à 10 / 25 / 50 % |
|---|---:|---:|---:|---:|
| pallets/click | 199 | 1 | 0 / 0 / 0 | 11 % / 26 % / 51 % |
| spf13/cobra | 199 | 0 | – | 10 % / 25 % / 50 % |

Le seul échec confirmé est une vraie régression publiée sur la branche principale de click :
[`6c4a77b`](https://github.com/pallets/click/commit/6c4a77ba24854dab793a8ff72110a0a24c403c9f),
« Use `default=True` as a sentinel for non-boolean flags », modifie `src/click/core.py`. Il casse
4 tests de `tests/test_options.py` et `tests/test_termui.py`, et a été annulé le jour même.
**testhunch le manque à tous les budgets** : aucun de ces tests n'avait échoué avant, et leur nom
ne rappelle pas `core`. Sur les 11 autres commits de click dont la suite a échoué, les tests
`test_echo_via_pager` ont échoué une fois puis réussi à la relance : ils comptent comme instables,
pas comme des échecs à rattraper.

### Mutants dans les lignes changées par chaque commit

| Projet | Mutants essayés | Détectés par un test | Mutants rattrapés à 10 / 25 / 50 % | Tests détecteurs lancés à 10 / 25 / 50 % | Temps de test lancé à 10 / 25 / 50 % |
|---|---:|---:|---:|---:|---:|
| pallets/click | 132 | 90 | 84 % / 92 % / 97 % | 17 % / 34 % / 64 % | 11 % / 23 % / 46 % |
| spf13/cobra | 111 | 62 | 68 % / 84 % / 92 % | 18 % / 31 % / 66 % | voir plus bas |

Sur click, 41 mutants n'ont été détectés par aucun test et 1 n'a produit aucun rapport. Sur cobra,
26 n'ont pas été détectés et 23 ne compilaient pas. Aucun de ces mutants n'entre dans les
pourcentages.

### Limites

- Deux projets, pas un échantillon : ils ont été choisis avant de voir un résultat, pour les
  raisons de l'ADR 0011.
- Un mutant d'un seul jeton, dans un fichier dont le nom ressemble à celui de ses tests, favorise
  l'affinité de nom de testhunch. La seule vraie régression, elle, est manquée.
- **Le temps de cobra n'est pas mesurable** : `go test` écrit la durée de chaque test au centième
  de seconde (`%.2fs`), et presque tous valent 0. Les quelques tests qui ont une durée font donc
  basculer la part du temps d'un coup : sur l'historique réel, 3 % du temps à 10 % et à 25 %, puis
  99 % à 50 %.
- Les images ont été reconstruites à chaque reprise de la collecte, qu'une panne réseau et deux
  manques de mémoire ont interrompue. Ce sont les mêmes Dockerfiles, avec une image de base
  épinglée par digest et gotestsum épinglé par version. Chaque JSON liste les ID d'images
  utilisés. Dans les images encore présentes : `less` 668-1, Python 3.12.14 et uv 0.12.13 pour
  click ; Go 1.27.1 et gotestsum 1.13.0 pour cobra.
- Les runs ont été collectés avec le banc d'essai de `6094bec`, puis de `a4a2b88`, qui ajoute
  seulement une nouvelle tentative quand l'installation échoue (aucun des runs gardés n'en a eu
  besoin). L'évaluation a été faite à `a4a2b88`.
