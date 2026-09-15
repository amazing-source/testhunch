# Where an alert goes (docs/adr/0027).
#
# Alertmanager can send mail, but that means an SMTP server and a password kept somewhere on the
# instance. SNS is already in the account, the instance already has a role, and an email
# subscription costs nothing: the alert is signed with the instance's own identity and no secret
# exists to leak. Same address as the budget alert, for the same reason: without an address there
# is nobody to tell, so nothing is created.

resource "aws_sns_topic" "alerts" {
  count = var.alert_email == "" ? 0 : 1

  name = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
  # AWS emails a confirmation link, and nothing is delivered until it is clicked. Terraform cannot
  # wait for that, and reports the subscription as pending rather than failing.
}
