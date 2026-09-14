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

## Phase 4 : service hébergé

- [ ] Terraform pour un seul serveur : Postgres, API, worker, stockage objet pour les rapports bruts
- [ ] Déploiement continu de `main` vers la préproduction, promotion manuelle en production
- [ ] Métriques (Prometheus) et alertes, dont le taux de tests manqués en mode fantôme comme objectif de niveau de service
- [ ] La CI de testhunch envoie son historique à l'API hébergée
- [ ] Des jetons par dépôt au lieu d'un jeton partagé
- [ ] Partitionner `results` par date quand la table sera assez grosse pour le justifier

## Phase 5 : un modèle appris

Le modèle appris devra battre la meilleure heuristique simple, et non le classement de testhunch
0.2.0. Les études ne donnent pas le gagnant d'avance. Sur les suites longues de LRTS, le meilleur
modèle appris obtient un APFDc moyen de 0,736, contre 0,735 pour « les tests qui ont échoué le plus
récemment d'abord », et 0,835 quand cette heuristique tient compte en plus de la durée des tests
(Cheng et al., tableau 8). Chez Yaraghi et al., à l'inverse, une forêt aléatoire atteint 0,82 contre
0,71 pour la meilleure heuristique (RQ2.5). La première étape ne dépend pas de la phase 4 et peut
avancer avant elle.

### D'abord, la meilleure heuristique

- [ ] Séparer les projets avant tout réglage : des projets de développement pour régler, des projets mis de côté pour publier, jamais regardés pendant les réglages. Le partage de RTPTorrent est tiré au sort et consigné dans un ADR avant la première mesure ; le banc d'essai n'a que deux projets, ceux mis de côté seront de nouveaux projets
- [ ] Mesurer aussi l'APFDc (l'APFD qui tient compte de la durée des tests) et le rappel selon la part du temps de test réellement lancée. Les suites de LRTS durent 6,5 heures en moyenne : ce que la durée apporte sur des suites de quelques secondes reste à mesurer
- [ ] Compter la récence et la fenêtre d'historique en builds, et non en exécutions : sur SonarQube, les nombreux jobs par build laissent beaucoup de classes inconnues (voir les [résultats de la phase 3](benchmarks/results/README.md))
- [ ] Une étude par ajouts successifs, chaque version mesurée : partir des tests qui ont échoué le plus récemment, puis ajouter la durée, le taux d'échec, les changements de verdict, l'historique conjoint fichiers × tests, et enfin le nom et le diff. Un ajout n'est gardé que s'il améliore la mesure sur les projets de développement
  - Le nom et le diff comme signal quand l'historique ne dit rien, et non comme bonus fixe qui domine le score : sur le premier échec de chaque test de LRTS, « le plus récemment échoué » tombe à 0,467 contre 0,504 pour l'aléatoire, et une recherche textuelle dans le diff atteint 0,691 (tableau 10). Chez Facebook, les « tokens communs » entre chemins et noms de tests dégradaient le modèle et ont été retirés (Machalica et al., tableau I)
- [ ] La meilleure version devient le classement de référence, avec ses raisons ; publier les mesures de chaque version sur les projets mis de côté, y compris les mauvaises

### Ensuite, le modèle appris

- [ ] Variables : échecs conjoints fichiers/tests, distance entre chemins, récence, instabilité, durée des tests, et celles que Facebook a retenues après sélection (Machalica et al., tableau I) : historique de modification des fichiers modifiés (3, 14 et 56 jours), extensions de ces fichiers, taux d'échec sur plusieurs fenêtres (7, 14, 28 et 56 jours), nombre de tests
- [ ] Des arbres à gradient boosting comparés à la meilleure heuristique de l'étape précédente, réglés sur les projets de développement et mesurés sur les projets mis de côté
- [ ] Ne le livrer que s'il bat cette heuristique ; publier la comparaison dans tous les cas
- [ ] Explorer les indicateurs de prédiction de défauts (fichiers historiquement sujets aux bugs) comme variable supplémentaire

## Références

- Machalica et al., *Predictive Test Selection*, ICSE-SEIP 2019 (Meta), [doi:10.1109/ICSE-SEIP.2019.00018](https://doi.org/10.1109/ICSE-SEIP.2019.00018), [arXiv:1810.05286](https://arxiv.org/abs/1810.05286)
- Mattis et al., *RTPTorrent: An Open-source Dataset for Evaluating Regression Test Prioritization*, MSR 2020
- Cheng, Wang, Jabbarvand et Marinov, *Revisiting Test-Case Prioritization on Long-Running Test Suites*, ISSTA 2024, [doi:10.1145/3650212.3680307](https://doi.org/10.1145/3650212.3680307) (le jeu de données LRTS)
- Yaraghi, Bagherzadeh, Kahani et Briand, *Scalable and Accurate Test Case Prioritization in Continuous Integration Contexts*, IEEE TSE 2023, [doi:10.1109/TSE.2022.3184842](https://doi.org/10.1109/TSE.2022.3184842), [arXiv:2109.13168](https://arxiv.org/abs/2109.13168)
- *Predicting test failures induced by software defects*, Journal of Systems and Software, 2025 (Nokia 5G)
