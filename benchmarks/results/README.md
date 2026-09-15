# Résultats du benchmark

Mesurés le 15 septembre 2026 avec le classement de référence de testhunch tel que l'étude des
heuristiques l'a retenu ([ADR 0014](../../docs/adr/0014-the-ranking-study-measures-time-to-red-against-latest-failure.md),
[ADR 0015](../../docs/adr/0015-testhunch-ranks-by-latest-failure-per-unit-of-time.md)) : la récence
des échecs du test comptée en builds, plus un bonus quand le changement touche son propre fichier,
le tout divisé par sa durée habituelle. Aucun modèle appris.

Les budgets sont désormais des **parts du temps de test attendu**, et non des parts du nombre de
tests ([ADR 0017](../../docs/adr/0017-a-budget-is-a-share-of-the-test-time.md)). C'est le changement
qui explique l'essentiel des écarts avec la campagne précédente : la colonne « rattrapés » et la
colonne « temps » ne se lisent plus séparément.

Chaque chiffre vient d'un rejeu où chaque exécution est classée uniquement à partir des exécutions
terminées avant elle, avec le vrai code d'ingestion et de classement de testhunch. Les projets mis
de côté n'ont été rejoués qu'une fois, et ce regard est inscrit dans
[le registre](held-out-log.md) ([ADR 0016](../../docs/adr/0016-every-look-at-the-held-out-projects-is-recorded.md)) :
RTPTorrent au commit `159548f`, le banc d'essai à `06e054a`, dont le code de mesure est identique.

Les pages générées, en anglais, donnent le détail par projet :

- [RTPTorrent](rtptorrent/README.md) : 20 projets Java, historique réel de Travis CI.
- [Banc d'essai](harness/) : click et cobra (projets de développement), fastapi et ollama (mis de
  côté), commit par commit et avec mutants.
- [Étude des heuristiques](study/) : comment cette version a été choisie, et ce qu'elle vaut face à
  « les tests qui ont échoué le plus récemment d'abord ».
- [testhunch sur testhunch](self.md) : notre propre CI, où **aucun test n'a jamais échoué**, donc où
  testhunch ne peut rien démontrer. C'est notre plus mauvais résultat et il est publié quand même
  ([ADR 0028](../../docs/adr/0028-testhunch-measures-itself-and-publishes-that-it-cannot.md)).

## Ce qu'il faut retenir, y compris ce qui est moins bon

**À budget nominal égal, testhunch dépense deux fois moins de temps de test qu'en 0.2.0 à 10 % et à
25 %** (10,4 % contre 21,7 %, 23,6 % contre 43,6 %), **et 30 % de moins à 50 %** (48,5 % contre
69,1 %). C'est le gain, et il est net. Mais il ne se paie pas de rien :

- le **rappel par build** — le build reste-t-il rouge — s'améliore à 10 % et à 25 % du temps, et
  **se dégrade à 50 %** : 91,8 % contre 94,1 % pour la 0.2.0 ;
- le **rappel par test** baisse à tous les budgets. Beaucoup de tests en échec ne tournent plus, le
  build devient rouge quand même.

Attention cependant : ce tableau compare une part du **temps** à une part du **nombre de tests**.
La comparaison à part de temps égale existe déjà, mesurée une seule fois sur les projets mis de
côté avec des versions figées d'avance ([study/held-out.md](study/held-out.md)) — part des jobs en
échec devenus rouges :

| À part de temps égale | 10 % | 25 % | 50 % |
|---|---:|---:|---:|
| **classement actuel** | **0,573** | **0,706** | **0,810** |
| les tests qui ont échoué récemment d'abord | 0,526 | 0,674 | 0,771 |
| testhunch 0.2.0 | 0,511 | 0,637 | 0,749 |

À temps égal, la version actuelle rattrape plus de builds cassés que la 0.2.0 à **tous** les
budgets, d'environ 6 points, et à nombre de tests égal aussi. La ligne « 50 % » du tableau
précédent ne dit donc pas que la 0.2.0 ordonnait mieux : elle dit que 50 % du temps achète moins de
tests que 50 % des tests.

Ce qui reste franchement moins bon : le rappel par test. Pour savoir vite qu'un changement casse
quelque chose, cette version est meilleure et bien moins chère ; pour savoir *tout* ce qu'il casse,
elle est moins bonne.

### Et un angle mort, mesuré : les premiers échecs

Ces moyennes mélangent deux régimes très différents. Découpées selon que le test en échec avait
déjà échoué ou non ([détail](study/first-failures.md), `python -m benchmarks.firstfailures`, sur les
10 projets de développement), position du premier test en échec dans l'ordre, **plus bas = mieux** :

| | A déjà échoué (4 182 jobs) | N'a jamais échoué (283 jobs) |
|---|---:|---:|
| testhunch | **0,124** | 0,692 |
| le plus récemment échoué | 0,107 | 0,616 |
| aléatoire | 0,460 | **0,472** |

Sur un test qui a déjà échoué — 94 % des jobs en échec — testhunch est presque quatre fois meilleur
que l'aléatoire. **Sur un test qui n'a jamais échoué, il est plus mauvais que l'aléatoire**, et c'est
structurel : un classement fondé sur la récence des échecs relègue par construction ce qui n'a jamais
cassé, donc il cherche au mauvais endroit. Le hasard, lui, ne se trompe pas exprès. Cheng et al.
(ISSTA 2024, tableau 10) mesurent la même chose sur « le plus récemment échoué » : 0,467 contre
0,504 pour l'aléatoire.

Deux précisions que la page détaille :

- **Notre seul avantage sur cette tranche vient du coût, pas de la prédiction.** En temps (`red_at`)
  testhunch fait 0,554 contre 0,721 pour le plus récemment échoué, uniquement parce qu'il lance les
  tests rapides d'abord. En position, il fait *moins bien* que lui : diviser par la durée repousse
  encore un test neuf qui est lent. Ne rapporter que le temps revendiquerait une compétence qu'il
  n'a pas.
- **Ce n'est pas la faute de la règle des tests inconnus.** La position parmi les seuls tests connus
  (0,704) est la même que la position globale (0,692) : le biais est dans le classement lui-même.

C'est le cas de la seule vraie régression de click — manquée à 10 % du temps de test, et rattrapée à
25 % par un seul de ses quatre tests cassés — et c'est le cas de tout bug écrit dans du code neuf.
C'est aussi la raison pour laquelle le filet de sécurité de
l'[ADR 0007](../../docs/adr/0007-selections-leave-out-known-low-ranked-tests.md) — ne sauter que sur
les pull requests, relancer toute la suite sur la branche principale — n'est pas une précaution de
principe mais une pièce portante.

**Et cette régression, c'est notre étude qui l'a introduite.** Mesurée sur la même tranche
([détail](study/cold-start.md)) :

| | A déjà échoué (4 182 jobs) | N'a jamais échoué (283 jobs) |
|---|---:|---:|
| classement actuel | **0,124** | 0,692 |
| testhunch 0.2.0 | 0,149 | **0,455** |
| aléatoire | 0,460 | 0,472 |

La 0.2.0 n'était pas pire que le hasard sur les premiers échecs ; la version que l'étude a retenue
l'est. La 0.2.0 portait un signal de démarrage à froid — son affinité de nom, de poids 2,0,
appliquée à tous les tests — que l'étude a remplacé par `test_file_changed*0.5`, lequel ne se
déclenche que sur un cinquième des jobs : 20,4 % exactement, 929 des 4 545 jobs en échec des projets
de développement, comptés sur le rejeu même de l'étude ([ADR 0018](../../docs/adr/0018-first-failures-are-a-guardrail-not-an-average.md)).
L'échange a rapporté 0,018 d'APFDc moyen et coûté la propriété qui protégeait le code neuf.

Trente candidats ont essayé de la récupérer avec les signaux de proximité continus, **aucun n'y
arrive** : même à poids 0,1 et appliqués seulement là où l'historique se tait, ils noient le
classement (0,124 → 0,335 sur le bon régime) sans jamais atteindre l'aléatoire sur l'autre. Ce qui
marchait était **sélectif**, déclenché sur une correspondance de radical de fichier, et baisser le
poids d'un signal continu ne le rend pas sélectif.

### Le modèle appris ne passe pas, et la seule chose qu'il améliore

Phase 6, [détail](study/learned.md), [ADR 0031](../../docs/adr/0031-the-learned-model-does-not-ship-and-where-it-wins.md).
Des arbres à gradient boosting sur 29 396 lignes tirées des cinq projets d'entraînement, mesurés
sur les cinq projets de validation que le modèle n'a jamais vus. Mesure principale, APFDc :

| Classement | APFDc moyen | Écart | Intervalle à 95 % | Meilleur sur |
|---|---:|---:|---|---:|
| **classement actuel** | **0,883** | | | |
| modèle appris, divisé par la durée | 0,883 | +0,001 | [−0,013, +0,015] | 3 sur 5 |
| modèle appris, brut | 0,846 | −0,036 | [−0,062, −0,012] | 1 sur 5 |

La règle demandait +0,005 et un intervalle au-dessus de zéro : **rien n'est livré**. Les deux
variantes existent parce que l'heuristique divise son score par la durée attendue ; comparer sans
elle poserait deux questions à la fois, « le modèle estime-t-il mieux le risque » et « diviser par
le coût aide-t-il », à laquelle l'étude a déjà répondu.

**Mais sur la tranche où ce projet est le plus mauvais, le modèle brut est le premier à faire
mieux.** Position du premier test en échec, plus bas = mieux :

| | A déjà échoué (2 717 jobs) | N'a jamais échoué (192 jobs) |
|---|---:|---:|
| classement actuel | **0,127** | 0,740 |
| modèle appris, brut | 0,132 | **0,445** |
| testhunch 0.2.0 | 0,158 | 0,461 |
| aléatoire | 0,451 | 0,455 |

La ligne « aléatoire » vient de la même tranche, mesurée à part sur les mêmes cinq projets
([détail](study/first-failures-validation.md)).

C'est **le premier classement mesuré ici qui ne soit pas plus mauvais que le hasard là où
l'historique se tait**. La marge sur le hasard est d'un centième, ce qui ne revendique aucune
compétence ; ce que c'est, c'est la fin d'une régression que l'étude elle-même avait introduite.

Et c'est une piste, pas un résultat : 192 jobs, un seul modèle, un seul jeu d'hyperparamètres, et
aucun regard sur les projets mis de côté. Un classement qui n'emploierait le modèle que là où
l'historique se tait est le candidat évident, et il n'est pas écrit.

## RTPTorrent : 20 projets Java, 110 126 jobs Travis CI

Méthode : [ADR 0010](../../docs/adr/0010-benchmark-replays-rtptorrent-in-build-order.md). Données :
RTPTorrent 1.1 (Mattis et al., MSR 2020, [doi:10.5281/zenodo.4046180](https://doi.org/10.5281/zenodo.4046180),
CC-BY-4.0). Chaque fichier lu est vérifié par son CRC-32 et listé dans le JSON du projet. Les
résultats sont **par classe de test**, sans relances, et les jobs ont été rejoués dans l'ordre de
leurs identifiants.

**Les deux tableaux qui suivent ne comptent pas les mêmes fautes, et c'est voulu.** Le tableau des
budgets écarte une classe qui a réussi *et* échoué dans le même job : c'est de l'instabilité, pas un
échec manqué ([ADR 0006](../../docs/adr/0006-shadow-mode-measures-misses-without-skipping.md)), et
un job dont tous les échecs sont instables n'y est pas un job en échec. Le tableau d'APFD, lui,
compte toute classe ayant une ligne en échec, comme les ordres des auteurs du jeu de données, pour
que la comparaison porte sur les mêmes fautes. L'écart n'est pas anecdotique : sur les 20 projets,
**197 des 14 679 jobs ayant au moins une classe en échec n'ont que des échecs instables** — 38 sur
132 pour HikariCP, 73 sur 263 pour Graylog2, 41 sur 470 pour jcabi-github, aucun pour onze des vingt
(compté sur le jeu de données avec `collapse`, la fonction que le benchmark lui-même applique).

Médianes des 20 projets, la 0.2.0 entre parenthèses :

| Budget | Jobs en échec rattrapés | Classes en échec lancées | Temps de test lancé |
|---:|---:|---:|---:|
| 10 % | **80,8 %** (78,3 %) — pire : 47,7 % | 55,4 % (59,5 %) | **10,4 %** (21,7 %) — pire : 51,1 % |
| 25 % | **90,4 %** (86,9 %) — pire : 61,7 % | 71,4 % (75,2 %) | **23,6 %** (43,6 %) — pire : 72,8 % |
| 50 % | 91,8 % (**94,1 %**) — pire : 78,7 % | 86,9 % (90,6 %) | **48,5 %** (69,1 %) — pire : 80,9 % |

Un job est rattrapé quand au moins une de ses classes en échec tourne : le build reste rouge
(rappel par changement). Les classes en échec lancées sont le rappel par test. Le temps lancé est la
part de la durée des classes qui aurait tourné ; le reste est le temps économisé.

**Comme ordre d'exécution** (APFD, la mesure du papier RTPTorrent, calculée sur les 6 189 jobs en
échec que couvrent les ordres des auteurs du jeu de données) :

| Ordre | APFD moyen | en 0.2.0 |
|---|---:|---:|
| optimal (connu après coup, borne haute) | 0,926 | 0,926 |
| **recently-failed** (les tests qui ont échoué récemment d'abord) | **0,847** | 0,847 |
| **testhunch** | **0,845** | 0,832 |
| matrice fichiers × tests, naïve | 0,625 | 0,625 |
| matrice fichiers × tests, probabilité conditionnelle | 0,527 | 0,527 |
| aléatoire | 0,499 | 0,499 |
| ordre d'origine | 0,314 | 0,314 |

L'écart avec recently-failed passe de −0,015 à −0,002, et testhunch la devance maintenant sur
**13 projets sur 20**, contre 10 en 0.2.0. L'APFD ignore la durée des tests par construction : il ne
voit donc rien du gain principal de cette version, qui est du temps. C'est la raison pour laquelle
l'étude a pris l'APFDc comme mesure principale (ADR 0014).

### Là où testhunch s'en sort mal

- **Deux projets dépensent beaucoup plus que leur budget.** jade4j lance 29,6 % de ses classes mais
  **51,1 % de son temps** à un budget de 10 %, SonarQube 8,3 % des classes pour 40,7 % du temps. Le
  budget ne gouverne que le temps des classes que testhunch connaît ; celles qu'il n'a jamais vues
  tournent toujours (ADR 0006, 0007), et sur ces deux projets elles sont nombreuses et lentes. Aucun
  classement n'y peut rien : l'étude mesure que même le meilleur ordre possible, connu après coup,
  a besoin de 49 % du temps pour rattraper 90 % des builds cassés.
- **optiq et LittleProxy perdent du rappel par build** : 68,5 % contre 79,2 %, et 63,6 % contre
  76,6 %, à 25 %. Ce sont deux des plus petits échantillons (130 et 77 jobs en échec), mais ce sont
  les pires cas et ils s'affichent.
- **À 50 % du temps, la 0.2.0 rattrapait plus de builds.** Un budget de 50 % du temps lance moins de
  tests qu'un budget de 50 % des tests : c'est le prix de contrôler le coût réel.
- **Le rappel par test reste faible sur plusieurs projets** : à 10 %, 20,3 % des classes en échec
  tournent sur le pire projet. Le build reste souvent rouge quand même, parce qu'une seule classe en
  échec suffit.

### Limites

- Des classes Java, des builds Travis CI que le papier date « de 2007 à 2016 », sans relances : un
  échec instable ne se distingue pas d'un vrai échec.
- SonarQube reste le projet le plus lourd du lot : 53 307 jobs, dont 32 321 sans aucun commit
  associé dans le jeu de données, donc sans fichier modifié connu.
- Les 10 projets de développement ont été rejoués au commit `06e054a`, les 10 projets mis de côté à
  `159548f`. Le code de mesure est identique entre les deux ; seul le garde-fou du registre a changé
  entre-temps, et la différence est vérifiable dans l'historique git.

## Banc d'essai : quatre projets, commit par commit

Méthode : [ADR 0011](../../docs/adr/0011-harness-replays-real-projects-in-pinned-containers.md) et
[ADR 0012](../../docs/adr/0012-mutants-seed-faults-in-the-lines-a-commit-changed.md). Les 200
derniers commits de premier parent de chaque projet ont lancé leur suite complète dans un conteneur.
Les résultats sont **par test**, relancés une fois en cas d'échec. click et cobra servent au
développement, fastapi et ollama sont mis de côté ([ADR 0013](../../docs/adr/0013-development-projects-tune-held-out-projects-measure.md)).

### Mutants dans les lignes changées par chaque commit

Mutants rattrapés, et part du temps de test dépensée ; la 0.2.0 entre parenthèses là où elle a été
mesurée :

| Projet | Mutants détectés | 10 % | 25 % | 50 % |
|---|---:|---:|---:|---:|
| pallets/click | 90 | 81 (76) — 7 % du temps | 86 (83) — 17 % | 86 (87) — 37 % |
| spf13/cobra | 62 | 38 (42) — 24 % | 44 (52) — 24 % | 53 (57) — 24 % |
| fastapi/fastapi *(mis de côté)* | 22 | 18 — 10 % | 20 — 26 % | 22 — 52 % |
| ollama/ollama *(mis de côté)* | 158 | 145 — 1 % | **157 — 11 %** | 158 — 40 % |

- **ollama est le meilleur cas du benchmark** : 157 mutants sur 158 rattrapés pour 11 % du temps de
  test. Ses tests utiles sont rapides, et le classement les met devant.
- **Les 3 vraies régressions d'ollama sont rattrapées dès 10 %**, avec leurs 7 tests cassés, pour un
  temps arrondi à 0 %. Le seul vrai échec de click, un commit annulé le jour même, coûte bien plus
  cher : manqué à 10 %, il n'est rattrapé à 25 % que par 1 de ses 4 tests cassés, et il faut 50 %
  pour les lancer tous les quatre. Aucun d'eux n'avait échoué avant.
- **cobra est le pire cas, et il se dégrade** : 53 mutants sur 62 à 50 %, contre 57 en 0.2.0. Sa
  durée n'est pas mesurable — `go test` écrit la durée de chaque test au centième de seconde et
  presque toutes valent 0 — donc le budget de temps y perd son sens et se comporte comme un budget
  de nombre de tests, sans le contrôler pour autant (sa part de temps reste bloquée à 24 %). Un
  lanceur qui ne rapporte pas de durée utilisable devrait passer `--budget-unit tests`.

### Limites

- Quatre projets, pas un échantillon. Les deux projets de développement ont été choisis avant de
  voir un résultat, les deux projets mis de côté par une règle publiée à l'avance (ADR 0013).
- Un mutant d'un seul jeton, dans un fichier dont le nom ressemble à celui de ses tests, favorise
  testhunch. Les vraies régressions, elles, sont deux cas : trois rattrapées sur ollama, une
  manquée sur click.
- Les images ont été reconstruites à chaque reprise de la collecte. Ce sont les mêmes Dockerfiles,
  avec une image de base épinglée par digest. Chaque JSON liste les ID d'images utilisés.
