output "instance_id" {
  description = "The server. There is no address to give: nothing routes to it from outside."
  value       = aws_instance.server.id
}

output "reports_bucket" {
  description = "Object storage for the raw reports. Provisioned; nothing writes to it yet."
  value       = aws_s3_bucket.reports.bucket
}

output "port_forward" {
  description = "Reach the API from your machine: run this, then curl http://127.0.0.1:8000/readyz"
  value = join(" ", [
    "aws ssm start-session --region ${var.region} --target ${aws_instance.server.id}",
    "--document-name AWS-StartPortForwardingSession",
    "--parameters '{\"portNumber\":[\"8000\"],\"localPortNumber\":[\"8000\"]}'",
  ])
}

output "api_token" {
  description = "The bearer token the API expects. `terraform output -raw api_token` to read it."
  value       = random_password.api_token.result
  sensitive   = true
}
