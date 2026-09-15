# Héberger testhunch

Un seul serveur sur AWS, décrit par Terraform : Postgres, la migration et l'API en conteneurs, plus
un bucket S3 pour les rapports bruts. Le pourquoi de cette forme est dans
[l'ADR 0020](../docs/adr/0020-one-server-reached-only-through-ssm.md).

**Le serveur n'a aucune entrée ouverte.** Pas de règle entrante, pas de clé SSH. On l'atteint par
SSM Session Manager, qui sort depuis l'instance. L'API écoute sur la boucle locale de la machine, et
pour s'en servir on ramène son port 8000 sur le sien.

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

## Ce que ça coûte

Environ 18 dollars par mois : à peu près 16 pour l'instance `t3.small`, 2 pour le disque de 20 Go,
le bucket restant dans les centimes. `terraform destroy` supprime tout, y compris l'historique
enregistré dans Postgres, qui vit sur le disque de l'instance et n'est sauvegardé nulle part.

## Ce qui n'y est pas encore

- **Pas de TLS ni d'adresse publique.** Une CI ne peut donc pas y envoyer son historique : il faut
  un nom de domaine, un certificat et une règle entrante, et c'est une décision à part.
- **Le bucket ne sert à rien pour l'instant.** L'API range ses résultats dans Postgres et ne garde
  aucune copie du XML qu'on lui envoie. Le bucket attend le code qui écrira dedans.
- **L'état Terraform reste sur votre machine**, et il contient les secrets engendrés en clair. Il
  n'est pas versionné. Le déplacer dans S3 avec verrouillage viendra avec le déploiement continu.
- **Pas d'image arm64.** `release.yml` publie en `linux/amd64` seulement, donc pas de Graviton, qui
  serait pourtant moins cher. Le type d'instance refuse `t4g.` pour cette raison.
