# Web front end: nginx serves ui/ and forwards /api/* to API Gateway, adding the API key server-side,
# so the key never reaches a browser. (Inference itself runs on Lambda, not on this instance.)
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "web" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.web.name

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    bucket  = aws_s3_bucket.artifacts.id
    region  = var.region
    project = local.name
  })

  tags = { Name = "${local.name}-web" }

  depends_on = [
    aws_s3_object.ui,
    aws_s3_object.deploy,
    aws_ssm_parameter.api_url,
    aws_ssm_parameter.api_key,
    aws_iam_role_policy.web_access,
    aws_iam_role_policy_attachment.web_ssm,
  ]

  lifecycle {
    ignore_changes = [ami] # a newer AL2023 image must not replace the box (and its public IP) mid-semester
  }
}

resource "aws_eip" "web" {
  domain   = "vpc"
  instance = aws_instance.web.id
  tags     = { Name = "${local.name}-web" }

  depends_on = [aws_internet_gateway.igw]
}
