# Héberger testhunch

Un seul serveur sur AWS, décrit par Terraform : Postgres, la migration et l'API en conteneurs, plus
un bucket S3 pour les rapports bruts. Le pourquoi de cette forme est dans
[l'ADR 0020](../docs/adr/0020-one-server-reached-only-through-ssm.md).

**Par défaut, le serveur n'a aucune entrée ouverte.** Pas de règle entrante, pas de clé SSH. On
l'atteint par SSM Session Manager, qui sort depuis l'instance. L'API écoute sur la boucle locale de
la machine, et pour s'en servir on ramène son port 8000 sur le sien.

En donnant un nom à l'API, on ouvre 80 et 443 et on met Caddy devant, qui obtient et renouvelle seul
son certificat Let's Encrypt ([ADR 0021](../docs/adr/0021-the-api-answers-on-one-public-name.md)) :

```bash
terraform apply -var "api_domain=api.exemple.fr"
```

Il faut alors un enregistrement `A` chez le registrar, de ce nom vers l'adresse que
`terraform output server_address` donne. Caddy réessaie toutes les minutes tant que le nom ne
résout pas, donc l'ordre entre les deux n'a pas d'importance.

## Ce qu'il faut avant

- Terraform et l'AWS CLI.
- Des identifiants AWS (`aws configure`, ou `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY`).
- Le plugin Session Manager de l'AWS CLI, pour le tunnel.

## Monter la pile

```bash
cd infra/terraform
terraform init
terraform plan     # à lire en entier : c'est ce qui sera facturé
terraform apply
```

Le premier démarrage installe Docker, télécharge les images et lance la pile ; comptez deux à trois
minutes après la fin de `apply` avant que l'API réponde. Sur l'instance, le journal de cette
installation est `/var/log/testhunch-setup.log`.

## Déployer

Chaque commit de `main` qui passe la CI est publié comme image
([ADR 0025](../docs/adr/0025-main-is-deployable-without-a-release.md)), puis déployé tout seul
([ADR 0026](../docs/adr/0026-a-deployment-names-an-image-it-does-not-run-a-command.md)). Il n'y a
rien à taper : fusionner, c'est déployer.

Ce que fait le job `deploy` de la CI, et ce que vous pouvez faire à la main pour revenir en arrière :

```bash
aws ssm put-parameter --name /testhunch/image --type String --overwrite \
  --value "ghcr.io/amazing-source/testhunch:sha-<commit>"
aws ssm send-command --document-name testhunch-deploy \
  --targets "Key=tag:Name,Values=testhunch-server"
```

L'image est un **paramètre**, pas une ligne de cette configuration : Terraform lui donne sa première
valeur puis n'y touche plus, et le script de démarrage la relit à chaque démarrage. Un déploiement
et un `terraform apply` ne peuvent donc pas être en désaccord sur ce qui tourne, et une instance
remplacée revient sur l'image déployée. Le redémarrage coupe l'API quelques secondes.

Pour que GitHub puisse déployer, il faut nommer le dépôt et poser la variable `AWS_DEPLOY_ROLE` :

```bash
terraform apply -var "github_repository=votre-compte/testhunch"
gh variable set AWS_DEPLOY_ROLE --body "$(terraform output -raw deploy_role)"
```

Sans `github_repository`, aucune identité de déploiement n'est créée. L'identité créée ne sait faire
que deux choses : écrire ce paramètre, et lancer ce document sur cette instance. Elle n'ouvre pas de
shell et ne lit aucun secret.

## S'en servir

```bash
eval "$(terraform output -raw port_forward)"   # dans un terminal, laissez-le tourner
curl http://127.0.0.1:8000/readyz              # dans un autre
curl -H "Authorization: Bearer $(terraform output -raw api_token)" \
  http://127.0.0.1:8000/v1/repos
```

Ce jeton-là est celui de l'exploitant : il ouvre tout. Une CI reçoit le sien, qui n'ouvre qu'un
dépôt, frappé sur le serveur par `testhunch token create <dépôt>`
([ADR 0022](../docs/adr/0022-a-token-opens-one-repository.md)).

## L'alerte de facturation

```bash
terraform apply -var "alert_email=vous@exemple.fr"
```

Sans adresse, aucun budget n'est créé. Avec une adresse, AWS écrit dès que le coût **net**, celui
qui reste une fois les crédits appliqués, dépasse 5 dollars dans le mois, et dès que le mois se
dirige vers ce montant. Tant que le crédit couvre tout, ce coût net reste à zéro : cette alerte ne
mesure donc pas ce que vous consommez, elle prévient au moment où AWS commence vraiment à
facturer. C'est le signal qui compte quand on paie avec du crédit.

## Ce que ça coûte

Environ 20 dollars par mois : à peu près 16 pour l'instance `t3.small`, 2 pour son disque et 2 pour
le disque de données, le bucket restant dans les centimes.

## Détruire la pile

`terraform destroy` **échoue volontairement** sur le disque de données, qui porte l'historique de
tous les dépôts ([ADR 0024](../docs/adr/0024-the-data-outlives-the-server.md)). Pour détruire quand
même, il faut le dire explicitement :

```bash
terraform state rm aws_ebs_volume.data   # le disque quitte l'état, et reste dans le compte
terraform destroy                        # puis supprimez le disque à la main si vous le voulez
```

Le disque n'est sauvegardé nulle part : le perdre, c'est perdre l'historique.

## Ce qui n'y est pas encore

- **Aucune limitation de débit.** Une inondation non authentifiée coûte quand même du CPU.
- **Aucune sauvegarde.** Le disque de données survit au remplacement de l'instance, mais rien ne le
  copie : un instantané programmé est l'étape suivante évidente, et elle n'est pas faite.
- **Le bucket ne sert à rien pour l'instant.** L'API range ses résultats dans Postgres et ne garde
  aucune copie du XML qu'on lui envoie. Le bucket attend le code qui écrira dedans.
- **L'état Terraform reste sur votre machine**, et il contient les secrets engendrés en clair. Il
  n'est pas versionné. C'est assumé : les changements d'infrastructure sont rares, et ce sont eux
  qui peuvent détruire le disque, donc ils n'ont rien à faire dans un fichier de workflow
  ([ADR 0026](../docs/adr/0026-a-deployment-names-an-image-it-does-not-run-a-command.md)). Le
  déploiement continu ne concerne que l'application.
- **Pas d'image arm64.** Les deux workflows publient en `linux/amd64` seulement, donc pas de
  Graviton, qui serait pourtant moins cher. Le type d'instance refuse `t4g.` pour cette raison.
