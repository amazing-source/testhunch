# Opening the API to the internet, on one name, behind a certificate (docs/adr/0021).
#
# Everything here is off when api_domain is empty: no address is reserved, no port is opened, and
# the server stays exactly as ADR 0020 describes it, reachable only through SSM.

variable "api_domain" {
  description = "The name the API answers on, e.g. api.testhunch.xyz. Empty keeps it closed."
  type        = string
  default     = ""
}

# A fixed address, because a DNS record has to point at something that does not move: the address
# AWS assigns on its own changes the first time the instance stops. AWS bills every public IPv4
# address, so a reserved one attached to a running instance costs no more than the one it replaces.
resource "aws_eip" "server" {
  count = var.api_domain == "" ? 0 : 1

  instance = aws_instance.server.id
  domain   = "vpc"

  tags = {
    Name = "${var.name}-server"
  }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  count = var.api_domain == "" ? 0 : 1

  security_group_id = aws_security_group.server.id
  # No apostrophe: AWS refuses a rule description outside a-zA-Z0-9 and a short set of symbols.
  description = "The HTTP-01 challenge, and the redirect to HTTPS"
  ip_protocol = "tcp"
  from_port   = 80
  to_port     = 80
  cidr_ipv4   = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  count = var.api_domain == "" ? 0 : 1

  security_group_id = aws_security_group.server.id
  description       = "The API, behind Caddy"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

output "server_address" {
  description = "The fixed address to point an A record at. Empty while the API stays closed."
  value       = var.api_domain == "" ? "" : aws_eip.server[0].public_ip
}

output "api_url" {
  value = var.api_domain == "" ? "" : "https://${var.api_domain}"
}
