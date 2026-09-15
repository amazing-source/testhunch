# The alarm for the card, not for the credit.
#
# A budget measures net cost by default, which is what is left after credits are applied. While the
# credit lasts that number stays near zero, so a budget on net cost says nothing about how much is
# being consumed, and everything about the moment the credit stops covering it. That moment is
# exactly the one worth an email, so this budget keeps the default and sets a low limit: it fires
# when AWS actually starts charging.
#
# Set alert_email to turn it on. With no address there is nobody to notify, so the budget is not
# created at all rather than created deaf.

variable "alert_email" {
  description = "Where the budget alert is sent. Empty means no budget is created."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Monthly net cost, after credits, above which the alert fires."
  type        = number
  default     = 5
}

resource "aws_budgets_budget" "monthly" {
  count = var.alert_email == "" ? 0 : 1

  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # What is already charged this month.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  # What the month is heading towards, which arrives before the charge does.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
