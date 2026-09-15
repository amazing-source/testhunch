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

## S'en servir

```bash
eval "$(terraform output -raw port_forward)"   # dans un terminal, laissez-le tourner
curl http://127.0.0.1:8000/readyz              # dans un autre
curl -H "Authorization: Bearer $(terraform output -raw api_token)" \
  http://127.0.0.1:8000/v1/repos
```

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

Environ 18 dollars par mois : à peu près 16 pour l'instance `t3.small`, 2 pour le disque de 20 Go,
le bucket restant dans les centimes. `terraform destroy` supprime tout, y compris l'historique
enregistré dans Postgres, qui vit sur le disque de l'instance et n'est sauvegardé nulle part.

## Ce qui n'y est pas encore

- **Un seul jeton pour tout le monde.** Une fois l'API publique, ce jeton est la seule chose entre
  Internet et la base, et on ne peut pas le révoquer pour un dépôt sans le révoquer pour tous. Les
  jetons par dépôt sont l'item suivant de la feuille de route.
- **Aucune limitation de débit.** Une inondation non authentifiée coûte quand même du CPU.
- **Changer le script de démarrage remplace l'instance**, et le volume Postgres part avec elle.
  C'était sans conséquence tant que la base était vide ; ça n'en sera plus une fois qu'elle portera
  quelque chose. Il faudra un volume qui survive à l'instance, ou une base gérée.
- **Le bucket ne sert à rien pour l'instant.** L'API range ses résultats dans Postgres et ne garde
  aucune copie du XML qu'on lui envoie. Le bucket attend le code qui écrira dedans.
- **L'état Terraform reste sur votre machine**, et il contient les secrets engendrés en clair. Il
  n'est pas versionné. Le déplacer dans S3 avec verrouillage viendra avec le déploiement continu.
- **Pas d'image arm64.** `release.yml` publie en `linux/amd64` seulement, donc pas de Graviton, qui
  serait pourtant moins cher. Le type d'instance refuse `t4g.` pour cette raison.
