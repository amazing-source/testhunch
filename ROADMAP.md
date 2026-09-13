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
- [ ] Produire les sélections au format de chaque lanceur, sous forme d'exclusions des tests connus classés sous le budget, pour que les nouveaux tests tournent toujours ([ADR 0007](docs/adr/0007-selections-leave-out-known-low-ranked-tests.md)) ; chaque format vérifié en faisant tourner le vrai lanceur :
  - [x] pytest (plugin `testhunch.pytest_plugin`)
  - [ ] Go (gotestsum, `go test`)
  - [ ] JUnit/Surefire
  - [ ] cargo-nextest
  - [ ] Vitest
  - [ ] Jest
- [x] Documenter le filet de sécurité : ne sauter des tests que sur les pull requests, et lancer toute la suite sur la branche principale après chaque fusion (comme l'étape de stabilisation de Facebook, Machalica et al., section II-B)
- [x] Distinguer les échecs **confirmés** (toutes les tentatives ont échoué : `rerunFailure` chez Surefire et nextest, test répété et toujours en échec chez gotestsum) des échecs non confirmés, séparer les deux dans le mode fantôme et recommander d'activer les relances. Chez Facebook, sans ce nettoyage, l'évaluation annonçait un rappel par test d'environ 0,9 pour un rappel réel d'environ 0,7 : trois fois plus d'échecs manqués que prévu (Machalica et al., section VI-C)
- [x] *Learning runs* ([ADR 0009](docs/adr/0009-learning-runs-keep-measuring-while-skipping.md)) : quand une sélection saute des tests, lancer quand même toute la suite sur un échantillon de builds et n'enregistrer que ceux-là pour le mode fantôme, pour continuer à mesurer (Facebook échantillonne près d'un quart des changements, section IV-C)
- [x] Utiliser testhunch sur lui-même : la CI de testhunch conserve son historique d'une exécution à l'autre (l'API hébergée n'arrive qu'en phase 4)

## Phase 3 : le benchmark public

- [ ] Un banc d'essai qui récupère des projets open source à des commits passés, dans des conteneurs figés, et lance leurs suites
- [ ] Des tests de mutation pour créer des échecs réalistes là où l'historique en contient trop peu
- [ ] Évaluer sur RTPTorrent (résultats par classe de test, pas par méthode), avec un découpage temporel pour qu'aucun modèle ne voie le futur : chaque variable (taux d'échec, instabilité, récence) est calculée uniquement à partir des exécutions antérieures à celle qu'on prédit
- [ ] Mesurer le rappel par test et le rappel par changement, ainsi que le temps de test économisé
- [ ] Publier les résultats, y compris là où testhunch s'en sort mal

## Phase 4 : service hébergé

- [ ] Terraform pour un seul serveur : Postgres, API, worker, stockage objet pour les rapports bruts
- [ ] Déploiement continu de `main` vers la préproduction, promotion manuelle en production
- [ ] Métriques (Prometheus) et alertes, dont le taux de tests manqués en mode fantôme comme objectif de niveau de service
- [ ] La CI de testhunch envoie son historique à l'API hébergée
- [ ] Des jetons par dépôt au lieu d'un jeton partagé
- [ ] Partitionner `results` par date quand la table sera assez grosse pour le justifier

## Phase 5 : un modèle appris

- [ ] Variables : échecs conjoints fichiers/tests, distance entre chemins, récence, instabilité, durée des tests, et celles que Facebook a retenues après sélection (Machalica et al., tableau I) : historique de modification des fichiers modifiés (3, 14 et 56 jours), extensions de ces fichiers, taux d'échec sur plusieurs fenêtres (7, 14, 28 et 56 jours), nombre de tests
- [ ] Mesurer ce qu'apporte la correspondance de noms entre fichiers modifiés et tests du classement de référence : chez Facebook, les « tokens communs » entre chemins et noms de tests dégradaient le modèle et ont été retirés (tableau I)
- [ ] Des arbres à gradient boosting comparés au classement de référence de la phase 1, sur le benchmark de la phase 3
- [ ] Ne le livrer que s'il bat la référence ; publier la comparaison dans tous les cas
- [ ] Explorer les indicateurs de prédiction de défauts (fichiers historiquement sujets aux bugs) comme variable supplémentaire

## Références

- Machalica et al., *Predictive Test Selection*, ICSE-SEIP 2019 (Meta), [doi:10.1109/ICSE-SEIP.2019.00018](https://doi.org/10.1109/ICSE-SEIP.2019.00018), [arXiv:1810.05286](https://arxiv.org/abs/1810.05286)
- Mattis et al., *RTPTorrent: An Open-source Dataset for Evaluating Regression Test Prioritization*, MSR 2020
- *Predicting test failures induced by software defects*, Journal of Systems and Software, 2025 (Nokia 5G)
