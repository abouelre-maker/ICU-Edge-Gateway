# =============================================================================
# ICU Edge Gateway — public roots-proxy (resolves HAZARD-STREAM-012 gap 1)
# Phase 5-Stream Section C, follow-up.
#
# DESIGN.md §4 / modules/ca/main.tf's HAZARD-STREAM-012 docstring both
# document the same inconsistency: DESIGN.md §1's bootstrap flow describes
# an operator running `curl .../roots.pem` against step-ca directly, but
# modules/ca's step-ca is reachable ONLY via its internal NLB, from
# security groups explicitly allow-listed in
# modules/ca's allowed_client_security_group_ids -- an operator's laptop
# is not one of those, so that curl, as literally described, requires
# separate VPN/bastion access into the VPC that DESIGN.md never mentions.
#
# THE DECISION (this module): a narrow public-facing proxy for EXACTLY
# GET /roots.pem, nothing else. Modeled directly on
# modules/provisioning-api's ALB + Lambda-target pattern (same shape: a
# public ALB, a Lambda inside the VPC allow-listed into modules/ca's
# security group the same way provisioning-api's Lambdas already are),
# because that pattern is already this codebase's precedent for "a
# narrowly-scoped Lambda reaches step-ca over the internal NLB" -- this
# module does not introduce a new trust mechanism, it reuses the existing
# one for one more, even narrower, purpose.
#
# WHY NOT open a public listener directly on modules/ca's own NLB: an NLB
# is TCP passthrough only (see modules/ca/main.tf's header) -- it has no
# concept of "this path, not that one". Exposing it publicly at all would
# expose step-ca's admin/ACME/signing surface (same port 9000) right along
# with /roots.pem, defeating the entire point. Only an L7-aware layer (ALB
# listener rules, as used here) can enforce "this path and method, nothing
# else" -- so a separate ALB it is, never a change to modules/ca's own NLB
# or its security group's existing ingress rule.
#
# WHAT THIS MODULE DOES NOT TOUCH: modules/ca's aws_lb.step_ca (still
# internal = true, unchanged), its aws_lb_listener (still port 9000,
# unchanged), and its aws_security_group.step_ca_task's existing ingress
# rule (still scoped to var.allowed_client_security_group_ids -- this
# module's Lambda SG is ADDED to that list at the env level, see
# envs/dev/main.tf, exactly the same trust level provisioning-api's
# Lambdas already have, not a new or broader one). The admin/ACME/signing
# surface is exactly as restricted as it was before this module existed.
#
# See ../../DESIGN.md §4 for the manual verification steps proving the
# admin/ACME/signing path stays unreachable through this new public route.
# =============================================================================

data "archive_file" "roots_proxy" {
  type        = "zip"
  source_file = "${path.module}/lambda_src/roots_proxy.py"
  output_path = "${path.module}/.build/roots_proxy.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name_prefix        = "${var.name_prefix}-roots-proxy-lambda-"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_security_group" "lambda" {
  name_prefix = "${var.name_prefix}-roots-proxy-lambda-"
  vpc_id      = var.vpc_id

  # Narrower than modules/provisioning-api's Lambda SG (which needs
  # 0.0.0.0/0 egress for DynamoDB/Secrets Manager calls): this Lambda
  # calls exactly one thing, step-ca's own port, over the internal NLB.
  egress {
    description     = "step-ca API port, over modules/ca's internal NLB -- the ONLY outbound call this Lambda makes"
    from_port       = 9000
    to_port         = 9000
    protocol        = "tcp"
    security_groups = [var.step_ca_task_security_group_id]
  }

  tags = {
    Name      = "${var.name_prefix}-roots-proxy-lambda"
    Component = "provisioning-ca-public-proxy"
  }
}

resource "aws_lambda_function" "roots_proxy" {
  function_name    = "${var.name_prefix}-roots-proxy"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "roots_proxy.handler"
  runtime          = "python3.12"
  timeout          = 10
  filename         = data.archive_file.roots_proxy.output_path
  source_code_hash = data.archive_file.roots_proxy.output_base64sha256

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      STEP_CA_ENDPOINT = var.step_ca_endpoint
    }
  }
}

resource "aws_lambda_permission" "roots_proxy_alb" {
  statement_id  = "AllowALBInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.roots_proxy.function_name
  principal     = "elasticloadbalancing.amazonaws.com"
  source_arn    = aws_lb_target_group.roots_proxy.arn
}

# ── Public ALB: exactly one route, GET /roots.pem, everything else denied ──
resource "aws_security_group" "alb" {
  name_prefix = "${var.name_prefix}-roots-proxy-alb-"
  vpc_id      = var.vpc_id

  ingress {
    description = "Public bootstrap endpoint for fetching step-ca's root cert (DESIGN.md §1) -- unlike modules/ca's own NLB, this IS meant to be internet-reachable, but only for the one path the listener rule below permits."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "roots_proxy" {
  name               = "${var.name_prefix}-roots-proxy"
  internal           = false
  load_balancer_type = "application"
  subnets            = var.private_subnet_ids
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "roots_proxy" {
  name        = "${var.name_prefix}-roots-proxy"
  target_type = "lambda"
}

resource "aws_lb_target_group_attachment" "roots_proxy" {
  target_group_arn = aws_lb_target_group.roots_proxy.arn
  target_id        = aws_lambda_function.roots_proxy.arn
  depends_on        = [aws_lambda_permission.roots_proxy_alb]
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.roots_proxy.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  # Default-deny: anything not matching the listener rule below (wrong
  # path, wrong method, or both) gets this, never the Lambda. This is the
  # ALB-level enforcement of "GET /roots.pem and nothing else" -- the
  # Lambda itself also refuses non-GET requests (see lambda_src/
  # roots_proxy.py) as a second, independent layer, not reliance on this
  # rule alone.
  default_action {
    type = "fixed-response"
    fixed_response {
      status_code  = "403"
      content_type = "text/plain"
      message_body = "forbidden"
    }
  }
}

resource "aws_lb_listener_rule" "roots_pem" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.roots_proxy.arn
  }

  # BOTH conditions must match -- ALB listener rule conditions are
  # AND'ed together, not OR'ed (AWS's documented semantics for multiple
  # condition blocks on one rule). Anything else (POST /roots.pem,
  # GET /1.0/sign, GET /roots.pem/../anything, etc.) falls through to the
  # listener's default_action above.
  condition {
    path_pattern {
      values = ["/roots.pem"]
    }
  }

  condition {
    http_request_method {
      values = ["GET"]
    }
  }
}
