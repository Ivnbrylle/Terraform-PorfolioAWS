# 1. The S3 Bucket for State
resource "aws_s3_bucket" "terraform_state" {
  bucket        = "ivan-terraform-state-${data.aws_caller_identity.current.account_id}" # Dynamic name to ensure uniqueness
  force_destroy = true                                                                  # Useful for students, allows deleting the bucket even if it has files
}

# 2. Enable Versioning (Crucial for state files)
resource "aws_s3_bucket_versioning" "enabled" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

# 3. DynamoDB for State Locking
resource "aws_dynamodb_table" "terraform_locks" {
  name         = "terraform-state-locking"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

data "aws_caller_identity" "current" {}

terraform {
  backend "s3" {
    bucket       = "ivan-terraform-state-405483480953"
    key          = "state/terraform.tfstate"
    region       = "ap-southeast-1" # Fixed to match your bucket's actual location
    use_lockfile = true             # The modern, non-deprecated way to lock state
    encrypt      = true
  }
}

# 1. DynamoDB Table for Contact Messages
resource "aws_dynamodb_table" "portfolio_messages" {
  name         = "PortfolioMessages"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "MessageId"

  attribute {
    name = "MessageId"
    type = "S"
  }

  attribute {
    name = "ContentHash"
    type = "S"
  }

  attribute {
    name = "SourceIP"
    type = "S"
  }

  global_secondary_index {
    name            = "ContentHashIndex"
    hash_key        = "ContentHash"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "SourceIPIndex"
    hash_key        = "SourceIP"
    projection_type = "ALL"
  }
}

# 2. IAM Role for Lambda
resource "aws_iam_role" "lambda_exec" {
  name = "portfolio_contact_lambda_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Attach policy to allow Lambda to write to DynamoDB and CloudWatch
resource "aws_iam_role_policy" "lambda_policy" {
  name = "portfolio_lambda_policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = ["dynamodb:PutItem", "dynamodb:Scan", "dynamodb:Query"]
        Effect = "Allow"
        Resource = [
          aws_dynamodb_table.portfolio_messages.arn,
          "${aws_dynamodb_table.portfolio_messages.arn}/index/*"
        ]
      },
      {
        # Broaden this to ensure SES has full access to send
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# 3. Zip the Lambda Code
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/index.py"
  output_path = "${path.module}/lambda_function.zip"
}

# 4. Lambda Function
resource "aws_lambda_function" "contact_handler" {
  filename      = data.archive_file.lambda_zip.output_path
  function_name = "SubmitContactForm"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.lambda_handler" # Matches index.py and the function name inside
  runtime       = "python3.12"
  timeout       = 15 # Increase from default 3s to handle DynamoDB queries

  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
}

# 5. API Gateway (HTTP API)
resource "aws_apigatewayv2_api" "contact_api" {
  name          = "PortfolioContactAPI"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = ["*"] # Change this to your domain later for security
    allow_methods = ["POST", "OPTIONS"]
    allow_headers = ["content-type"]
  }
}

resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id           = aws_apigatewayv2_api.contact_api.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.contact_handler.invoke_arn
}

resource "aws_apigatewayv2_route" "contact_route" {
  api_id    = aws_apigatewayv2_api.contact_api.id
  route_key = "POST /contact"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

# Deployment Stage (Auto-deploys changes)
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.contact_api.id
  name        = "$default"
  auto_deploy = true

  # This is the DDoS protection / Rate Limiting block
  default_route_settings {
    throttling_burst_limit = 2 # Max requests at a single millisecond
    throttling_rate_limit  = 5 # Max requests per second
  }
}

# Permission for API Gateway to call Lambda
resource "aws_lambda_permission" "api_gw" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.contact_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.contact_api.execution_arn}/*/*"
}


# Create the SES Email Identity
resource "aws_ses_email_identity" "my_email" {
  email = "rempisivan@gmail.com"
}

