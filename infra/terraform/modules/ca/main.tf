# =============================================================================
# ICU Edge Gateway — Private CA (step-ca, ECS Fargate + EFS)
# Phase 5-Stream Section C. See ../../DESIGN.md §2 for why step-ca was
# chosen over AWS Private CA / Vault PKI.
#
# step-ca terminates its OWN TLS and handles its OWN certificate issuance
# logic -- this module provides only the compute/storage/network shell
# around it (Fargate task, EFS for persistent CA state, NLB for TCP
# passthrough, security groups). The CA's root private key lives ONLY
# inside step-ca's own process/EFS volume -- nothing in this module ever
# touches it directly.
# =============================================================================

resource "aws_efs_file_system" "ca_state" {
  creation_token = "${var.name_prefix}-step-ca-state"
  encrypted      = true # at-rest encryption for the CA's root key material

  tags = {
    Name      = "${var.name_prefix}-step-ca-state"
    Component = "provisioning-ca"
  }
}

resource "aws_efs_mount_target" "ca_state" {
  for_each        = toset(var.private_subnet_ids)
  file_system_id  = aws_efs_file_system.ca_state.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

resource "aws_security_group" "efs" {
  name_prefix = "${var.name_prefix}-step-ca-efs-"
  vpc_id      = var.vpc_id

  ingress {
    description     = "NFS from step-ca's own ECS task"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.step_ca_task.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "step_ca_task" {
  name_prefix = "${var.name_prefix}-step-ca-task-"
  vpc_id      = var.vpc_id

  ingress {
    description     = "step-ca API/ACME port, from allow-listed clients ONLY (provisioning-api's Lambdas) -- never public"
    from_port       = 9000
    to_port         = 9000
    protocol        = "tcp"
    security_groups = var.allowed_client_security_group_ids
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name      = "${var.name_prefix}-step-ca-task"
    Component = "provisioning-ca"
  }
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-ca-cluster"
}

resource "aws_cloudwatch_log_group" "step_ca" {
  name              = "/ecs/${var.name_prefix}-step-ca"
  retention_in_days = 90 # IEC 62304-adjacent audit trail retention, not just default 30d
}

resource "aws_ecs_task_definition" "step_ca" {
  family                   = "${var.name_prefix}-step-ca"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  volume {
    name = "ca-state"
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.ca_state.id
      root_directory  = "/"
    }
  }

  container_definitions = jsonencode([
    {
      name      = "step-ca"
      image     = var.step_ca_image
      essential = true
      portMappings = [
        { containerPort = 9000, protocol = "tcp" }
      ]
      mountPoints = [
        { sourceVolume = "ca-state", containerPath = "/home/step" }
      ]
      environment = [
        { name = "STEPCA_INIT_NAME", value = var.ca_name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.step_ca.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "step-ca"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "step_ca" {
  name            = "${var.name_prefix}-step-ca"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.step_ca.arn
  # Single task: a CA is not a horizontally-scaled stateless service --
  # see DESIGN.md §4 (HA explicitly out of scope for this pass).
  desired_count = 1
  launch_type   = "FARGATE"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.step_ca_task.id]
    # No public IP -- step-ca is reached only via the internal NLB below,
    # from allow-listed security groups.
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.step_ca.arn
    container_name    = "step-ca"
    container_port    = 9000
  }
}

# Internal (not internet-facing) NLB -- TCP passthrough only, step-ca
# terminates its own TLS itself. This is deliberately NOT an ALB with TLS
# termination at the load balancer -- that would mean the CA's TLS
# handshake is handled by something other than step-ca, which is not how
# a private CA should be fronted.
resource "aws_lb" "step_ca" {
  name               = "${var.name_prefix}-step-ca"
  internal           = true
  load_balancer_type = "network"
  subnets            = var.private_subnet_ids
}

resource "aws_lb_target_group" "step_ca" {
  name        = "${var.name_prefix}-step-ca"
  port        = 9000
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "ip" # required for awsvpc-mode Fargate tasks

  health_check {
    protocol = "TCP"
  }
}

resource "aws_lb_listener" "step_ca" {
  load_balancer_arn = aws_lb.step_ca.arn
  port              = 9000
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.step_ca.arn
  }
}

resource "aws_iam_role" "execution" {
  name_prefix        = "${var.name_prefix}-step-ca-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name_prefix        = "${var.name_prefix}-step-ca-task-"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_region" "current" {}
