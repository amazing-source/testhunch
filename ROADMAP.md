# Feuille de route

Chaque phase est utile à elle seule. Aucune promesse de précision n'est faite tant que la phase 3 ne
permet pas de la mesurer.

## Phase 1 : enregistrer l'historique des tests (fondations)

- [x] Lire le JUnit XML de pytest, Vitest et Jest, testé sur de vrais rapports de chacun
- [x] Normaliser l'identité des tests entre dialectes ; fusionner les doublons au sein d'une exécution
- [x] Refuser le XML dangereux (expansion d'entités, références externes)
- [x] Lire les fichiers modifiés depuis git, renommages compris
- [x] Une seule couche de stockage SQL pour SQLite et Postgres, avec une suite de tests de contrat exécutée sur les deux
- [x] Ingestion idempotente : les mêmes rapports pour le même commit ne sont enregistrés qu'une fois
- [x] Rapports : tests instables (réussis et échoués sur un même commit), les plus lents, en échec
- [x] CLI : `ingest`, `report`, `prioritize`, `migrate`
- [x] API HTTP avec authentification par jeton *bearer*, contrôles de vivacité et de disponibilité
- [x] Image Docker, stack Compose, CI (lint, types, tests de Python 3.12 à 3.14 sur Postgres, test de fumée du conteneur), publication sur GHCR
- [x] Un vrai rapport de test pour Go (gotestsum), relances comprises
- [x] Un vrai rapport de test pour JUnit/Surefire (dont `flakyFailure` et `rerunFailure`)
- [x] Un vrai rapport de test pour cargo-nextest
- [x] Enregistrer les relances au sein d'une exécution comme indice d'instabilité ([ADR 0005](docs/adr/0005-retries-within-a-run-are-flakiness-evidence.md))
- [x] Regrouper les insertions par test dans `ingest` (auparavant une requête par test)
- [x] Publier sur PyPI avec la publication de confiance (*trusted publishing*) : [testhunch 0.1.0](https://pypi.org/project/testhunch/0.1.0/)

## Phase 2 : l'utiliser en CI

- [x] Une GitHub Action qui enveloppe `ingest` et `prioritize`
- [x] **Mode fantôme** : lancer tous les tests, enregistrer ce qui aurait été sauté, publier le vrai taux de tests manqués ([ADR 0006](docs/adr/0006-shadow-mode-measures-misses-without-skipping.md))
- [x] Produire les sélections au format de chaque lanceur, sous forme d'exclusions des tests connus classés sous le budget, pour que les nouveaux tests tournent toujours ([ADR 0007](docs/adr/0007-selections-leave-out-known-low-ranked-tests.md)) ; chaque format vérifié en faisant tourner le vrai lanceur :
  - [x] pytest (plugin `testhunch.pytest_plugin`)
  - [x] Go (`go test -skip`, aussi derrière gotestsum)
  - [x] JUnit/Surefire (`-Dtest=!classe#méthode`)
  - [x] cargo-nextest (filterset `-E`)
  - [x] Vitest (`-t` et `vitest list`)
  - [x] Jest (fichiers entiers, `--testPathIgnorePatterns`)
- [x] Documenter le filet de sécurité : ne sauter des tests que sur les pull requests, et lancer toute la suite sur la branche principale après chaque fusion (comme l'étape de stabilisation de Facebook, Machalica et al., section II-B)
- [x] Distinguer les échecs **confirmés** (toutes les tentatives ont échoué : `rerunFailure` chez Surefire et nextest, test répété et toujours en échec chez gotestsum) des échecs non confirmés, séparer les deux dans le mode fantôme et recommander d'activer les relances. Chez Facebook, sans ce nettoyage, l'évaluation annonçait un rappel par test d'environ 0,9 pour un rappel réel d'environ 0,7 : trois fois plus d'échecs manqués que prévu (Machalica et al., section VI-C)
- [x] *Learning runs* ([ADR 0009](docs/adr/0009-learning-runs-keep-measuring-while-skipping.md)) : quand une sélection saute des tests, lancer quand même toute la suite sur un échantillon de builds et n'enregistrer que ceux-là pour le mode fantôme, pour continuer à mesurer (Facebook échantillonne près d'un quart des changements, section IV-C)
- [x] Utiliser testhunch sur lui-même : la CI de testhunch conserve son historique d'une exécution à l'autre (l'API hébergée n'arrive qu'en phase 4)

## Phase 3 : le benchmark public

- [x] Un banc d'essai qui récupère des projets open source à des commits passés, dans des conteneurs figés, et lance leurs suites
- [x] Des tests de mutation pour créer des échecs réalistes là où l'historique en contient trop peu
- [x] Évaluer sur RTPTorrent (résultats par classe de test, pas par méthode), avec un découpage temporel pour qu'aucun modèle ne voie le futur : chaque variable (taux d'échec, instabilité, récence) est calculée uniquement à partir des exécutions antérieures à celle qu'on prédit
- [x] Mesurer le rappel par test et le rappel par changement, ainsi que le temps de test économisé
- [x] Publier les résultats, y compris là où testhunch s'en sort mal

## Phase 4 : la meilleure heuristique

Le principal risque du projet n'est pas l'infrastructure : c'est que les signaux de testhunch
n'apportent rien de plus que « les tests qui ont échoué le plus récemment d'abord ». Cette phase le
mesure avant de construire le service hébergé. Sur les suites longues de LRTS, cette heuristique
obtient un APFDc moyen de 0,735, et 0,835 quand elle tient compte en plus de la durée des tests
(Cheng et al., tableau 8).

- [x] Séparer les projets avant tout réglage : des projets de développement pour régler, des projets mis de côté pour publier, jamais regardés pendant les réglages ([ADR 0013](docs/adr/0013-development-projects-tune-held-out-projects-measure.md)). RTPTorrent est partagé 10/10 par une règle sans graine ; au banc d'essai, click et cobra servent au développement, fastapi et ollama sont mis de côté
- [x] Rendre les regards comptables ([ADR 0016](docs/adr/0016-every-look-at-the-held-out-projects-is-recorded.md)) : tout rejeu d'un projet mis de côté s'inscrit dans [un registre](benchmarks/results/held-out-log.md) avant de commencer, et refuse de partir d'un dépôt modifié ou non poussé. Ce que le code ne peut pas empêcher — les chiffres publiés ont été lus par qui règle ensuite — est écrit au lieu d'être tu
- [x] Programmer « le plus récemment échoué » dans le rejeu, comme référence mesurée partout avec les mêmes mesures que testhunch ([ADR 0014](docs/adr/0014-the-ranking-study-measures-time-to-red-against-latest-failure.md)), et le comparer aux ordres des auteurs de RTPTorrent : sur les projets de développement, notre implémentation de leur formule fait mieux sur 7 projets et moins bien sur 3 (APFD moyen 0,846 contre 0,810, [détail](benchmarks/results/study/baseline.md)) ; leur code n'est pas publié avec le jeu de données
- [x] Mesurer aussi l'APFDc (l'APFD qui tient compte de la durée des tests) et le rappel des builds cassés à budget de temps fixé. La mesure principale et le critère de décision (amélioration projet par projet, intervalle de confiance) sont fixés dans un ADR avant la première comparaison ([ADR 0014](docs/adr/0014-the-ranking-study-measures-time-to-red-against-latest-failure.md) : l'APFDc d'un job, tous ses échecs comptant pour une faute). Les suites de LRTS durent 6,5 heures en moyenne : ce que la durée apporte sur des suites de quelques secondes reste à mesurer
- [x] Compter la récence et la fenêtre d'historique en builds, et non en exécutions : sur SonarQube, les nombreux jobs par build laissent beaucoup de classes inconnues (voir les [résultats de la phase 3](benchmarks/results/README.md)). L'étude compte en builds depuis l'ADR 0014 ; le produit aussi depuis l'[ADR 0015](docs/adr/0015-testhunch-ranks-by-latest-failure-per-unit-of-time.md), qui tient l'historique à jour à l'ingestion et supprime toute fenêtre pour le classement
- [x] Une étude par ajouts successifs sur les projets de développement : partir du plus récemment échoué, puis, à chaque étape, essayer chacun des signaux restants et garder le meilleur, s'il améliore la mesure principale. Les signaux : la durée, le taux d'échec, les changements de verdict, l'historique conjoint fichiers × tests, le nom et le diff
  - Le nom et le diff comme signal quand l'historique ne dit rien, et non comme bonus fixe qui domine le score : sur le premier échec de chaque test de LRTS, « le plus récemment échoué » tombe à 0,467 contre 0,504 pour l'aléatoire, et une recherche textuelle dans le diff atteint 0,691 (tableau 10). Chez Facebook, les « tokens communs » entre chemins et noms de tests dégradaient le modèle et ont été retirés (Machalica et al., tableau I)
  - Étapes 1 à 4 ([résultats](benchmarks/results/study/)) : la durée gagne sur les 10 projets, puis plus rien ne gagne nettement ; une étape d'extension avec des signaux de proximité (Elsner et al., ISSTA 2021) retient « le fichier du test est modifié », de justesse, puis plus rien ne gagne. Version finale sur les projets de développement : 0,861, contre 0,825 pour le plus récemment échoué et 0,843 pour la 0.2.0
  - Ce que chaque source peut mesurer : RTPTorrent n'a que les noms des fichiers modifiés et des classes de test ; les durées de Go sont arrondies au centième de seconde ; au banc d'essai, les projets de développement n'ont presque que des mutants
- [x] Figer les choix, puis mesurer une seule fois chaque version retenue sur les projets mis de côté et publier le résultat, bon ou mauvais ([résultats](benchmarks/results/study/held-out.md)). Sur les 10 projets RTPTorrent mis de côté, la version finale fait +0,028 face à « le plus récemment échoué » (meilleure sur 9) et +0,043 face à la 0.2.0 ; pour rattraper 90 % des builds cassés, elle lance 58 % du temps de test, contre 66 % et 70 %. Au banc d'essai, elle fait jeu égal sur les mutants de fastapi et nettement mieux sur ceux d'ollama
- [x] La version finale devient le classement de référence de testhunch, avec ses raisons et une sélection par budget de temps ; le rejeu du produit doit reproduire les chiffres de l'étude
  - [x] Le classement de l'étude dans le produit ([ADR 0015](docs/adr/0015-testhunch-ranks-by-latest-failure-per-unit-of-time.md)) : historique par build tenu à jour à l'ingestion, priorité RTPTorrent, durée moyenne et fichier du test, dans la CLI, l'Action, l'API et le rejeu. Un test vérifie que le rejeu du produit donne exactement les ordres du moteur de l'étude
  - [x] Une sélection par budget de temps, et non par nombre de tests ([ADR 0017](docs/adr/0017-a-budget-is-a-share-of-the-test-time.md)) : le gain mesuré est en temps, pas en nombre. `--budget 25 %` dépense un quart du temps de test attendu ; le mode fantôme coupe avec les durées enregistrées avec le classement, jamais avec celles de l'exécution qu'il juge
  - [x] Que le rejeu du produit donne exactement les ordres du moteur de l'étude : vérifié par un test sur l'extrait RTPTorrent et sur un historique synthétique, ce qui est plus fort que de comparer des moyennes
  - [x] Refaire les tableaux de budgets avec le classement et le budget actuels ([résultats](benchmarks/results/README.md)) : un seul regard aux 10 projets mis de côté, inscrit au [registre](benchmarks/results/held-out-log.md) ([ADR 0016](docs/adr/0016-every-look-at-the-held-out-projects-is-recorded.md)). À 25 % du temps de test, le projet médian garde rouges 90 % de ses jobs en échec pour 24 % de son temps, contre 87 % pour 44 % en 0.2.0 ; mais à 50 % la 0.2.0 rattrapait plus de builds, et le rappel par test baisse à tous les budgets
- [x] Mesurer le classement sur la tranche où l'historique ne dit rien : sur un test qui n'a jamais échoué, testhunch fait **pire que l'aléatoire** (position 0,692 contre 0,472), alors qu'il est quatre fois meilleur que lui sur un test déjà tombé ([résultats](benchmarks/results/study/first-failures.md)). Le biais est dans le classement, pas dans la règle des tests inconnus, et notre seul avantage sur cette tranche vient du coût, pas de la prédiction
- [x] Faire des premiers échecs un garde-fou et non une ligne dans une moyenne ([ADR 0018](docs/adr/0018-first-failures-are-a-guardrail-not-an-average.md)) : trois mesures jamais fusionnées, et une barre de principe — ne jamais être pire que l'aléatoire sur cette tranche — qui ne demande aucune donnée pour se justifier. Les signaux de proximité rejetés par l'étape 3 y placent le test cassé entre 0,334 et 0,454, contre 0,469 pour l'aléatoire et 0,638 pour le classement actuel, sur les 118 jobs de la tranche dont les fichiers modifiés sont connus ([mesure](benchmarks/results/study/first-failures-signals.md))
- [x] Les étapes d'étude que l'ADR 0018 décrit, arrêtées après trois familles éliminées : les signaux de proximité continus noient le classement ([cold-start](benchmarks/results/study/cold-start.md)), le signal de nom sélectif ne rapporte presque rien ([selective](benchmarks/results/study/selective.md)), le diviseur de durée n'y est pour rien ([cold-free](benchmarks/results/study/cold-free.md)). Les 0,455 de la 0.2.0 restent inexpliqués ; une quatrième hypothèse — la fenêtre — est écrite dans l'ADR et volontairement non testée
- [ ] Arbitrer ce qu'un candidat peut céder sur la mesure principale pour franchir le garde-fou — après LRTS, pas avant
- [ ] Selon ce résultat, décider si le modèle appris (phase 6) passe avant le service hébergé (phase 5)

## Phase 5 : service hébergé

- [x] Terraform pour un seul serveur sur AWS ([ADR 0020](docs/adr/0020-one-server-reached-only-through-ssm.md)) : une `t3.small` à Paris, Postgres et l'API en conteneurs tenus par un service systemd, un bucket S3 pour les rapports bruts, et les secrets engendrés par Terraform dans Parameter Store. Aucune règle entrante et aucune clé SSH : on l'atteint par SSM. L'étape locale a été sautée à la demande du mainteneur, qui avait déjà un compte. Pas de worker, il n'y en a pas encore dans le code, et le bucket attend le code qui écrira dedans
  - [x] Donner un nom public à l'API ([ADR 0021](docs/adr/0021-the-api-answers-on-one-public-name.md)) : une adresse fixe, 80 et 443 ouverts, et Caddy devant l'API qui obtient et renouvelle seul son certificat Let's Encrypt. Tout cela tient à une variable : sans nom de domaine, rien n'est réservé ni ouvert et le serveur reste celui de l'ADR 0020. Le jeton partagé devient dès lors la seule chose entre Internet et la base, ce qui rend les jetons par dépôt urgents
- [ ] Déploiement continu de `main` vers la préproduction, promotion manuelle en production
- [ ] Métriques (Prometheus) et alertes, dont le taux de tests manqués en mode fantôme comme objectif de niveau de service
- [ ] La CI de testhunch envoie son historique à l'API hébergée : l'étape existe et l'Action sait parler au service (`api-url`), vérifié en CI contre une vraie API lancée dans le job. Il reste à déposer les deux secrets et à publier une version dont l'image porte les jetons par dépôt, le serveur tournant encore la 0.3.0
- [x] Enregistrer le classement côté serveur ([ADR 0023](docs/adr/0023-the-server-keeps-the-ranking-it-served.md)) : `prioritize --api` demande le classement au serveur, qui garde ce qu'il a servi. Le client n'envoie jamais de classement, sinon il pourrait enregistrer une prédiction que le serveur n'a pas faite, et un rapport de mode fantôme ne vaut que si personne n'a pu écrire la prédiction après avoir vu le résultat
- [ ] Lire le rapport du mode fantôme depuis l'API : les mesures sont enregistrées côté serveur, mais `testhunch shadow` lit encore une base, donc un utilisateur du service hébergé ne peut pas afficher ce qu'un budget aurait manqué
- [x] Des jetons par dépôt au lieu d'un jeton partagé ([ADR 0022](docs/adr/0022-a-token-opens-one-repository.md)) : une table `api_tokens` qui ne garde que l'empreinte SHA-256, un jeton frappé par la CLI contre la base et jamais par l'API, donc aucune requête ne peut en produire un ni élargir le sien. Un jeton présenté sur un autre dépôt reçoit un 403, un jeton inconnu ou révoqué un 401. Le jeton de l'exploitant ouvre toujours tout
- [ ] Partitionner `results` par date quand la table sera assez grosse pour le justifier

## Phase 6 : un modèle appris

Le modèle appris devra battre la meilleure heuristique de la phase 4, et non le classement de
testhunch 0.2.0. Les études ne donnent pas le gagnant d'avance. Sur LRTS, le meilleur modèle appris
obtient un APFDc moyen de 0,736, contre 0,735 pour le plus récemment échoué (Cheng et al.,
tableau 8). Chez Yaraghi et al., à l'inverse, une forêt aléatoire atteint 0,82 contre 0,71 pour la
meilleure heuristique (RQ2.5).

- [ ] Variables : échecs conjoints fichiers/tests, distance entre chemins, récence, instabilité, durée des tests, et celles que Facebook a retenues après sélection (Machalica et al., tableau I) : historique de modification des fichiers modifiés (3, 14 et 56 jours), extensions de ces fichiers, taux d'échec sur plusieurs fenêtres (7, 14, 28 et 56 jours), nombre de tests
- [ ] Des arbres à gradient boosting comparés à la meilleure heuristique de la phase 4, réglés sur les projets de développement et mesurés sur les projets mis de côté
- [ ] Ne le livrer que s'il bat cette heuristique ; publier la comparaison dans tous les cas
- [ ] Explorer les indicateurs de prédiction de défauts (fichiers historiquement sujets aux bugs) comme variable supplémentaire

## Références

- Machalica et al., *Predictive Test Selection*, ICSE-SEIP 2019 (Meta), [doi:10.1109/ICSE-SEIP.2019.00018](https://doi.org/10.1109/ICSE-SEIP.2019.00018), [arXiv:1810.05286](https://arxiv.org/abs/1810.05286)
- Mattis et al., *RTPTorrent: An Open-source Dataset for Evaluating Regression Test Prioritization*, MSR 2020
- Cheng, Wang, Jabbarvand et Marinov, *Revisiting Test-Case Prioritization on Long-Running Test Suites*, ISSTA 2024, [doi:10.1145/3650212.3680307](https://doi.org/10.1145/3650212.3680307) (le jeu de données LRTS)
- Yaraghi, Bagherzadeh, Kahani et Briand, *Scalable and Accurate Test Case Prioritization in Continuous Integration Contexts*, IEEE TSE 2023, [doi:10.1109/TSE.2022.3184842](https://doi.org/10.1109/TSE.2022.3184842), [arXiv:2109.13168](https://arxiv.org/abs/2109.13168)
- *Predicting test failures induced by software defects*, Journal of Systems and Software, 2025 (Nokia 5G)
