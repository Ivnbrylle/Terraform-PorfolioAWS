# Terraform-PortfolioAWS

A serverless AWS contact form backend for a personal portfolio, fully provisioned with Terraform.

## Architecture

```
User → API Gateway (HTTP API) → Lambda (Python 3.12) → DynamoDB
                                        ↓
                                       SES (Email Notification)
```

| Resource                  | Name                                | Purpose                          |
| ------------------------- | ----------------------------------- | -------------------------------- |
| API Gateway (HTTP API v2) | `PortfolioContactAPI`               | Exposes `POST /contact` endpoint |
| Lambda                    | `SubmitContactForm`                 | Handles form submissions         |
| DynamoDB                  | `PortfolioMessages`                 | Stores all contact messages      |
| SES                       | `rempisivan@gmail.com`              | Sends email notifications        |
| S3                        | `ivan-terraform-state-<account-id>` | Remote Terraform state           |
| DynamoDB                  | `terraform-state-locking`           | Terraform state locking          |

## Features

- **Rate limiting** — max 10 submissions per IP per hour, 5 per email per hour
- **Duplicate detection** — content hashing prevents identical message spam
- **Input validation** — rejects missing name, email, or message fields
- **DDoS protection** — API Gateway throttling (burst: 2, rate: 5 req/s)
- **CORS enabled** — ready to connect to any frontend
- **Email notifications** — via AWS SES on every successful submission

## Project Structure

```
portfolio-infra/
├── main.tf          # All AWS resources (S3, DynamoDB, Lambda, API GW, SES, IAM)
├── outputs.tf       # Outputs the live API endpoint URL
├── variables.tf     # Input variables
└── lambda/
    └── index.py     # Python Lambda handler
```

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.5
- [AWS CLI](https://aws.amazon.com/cli/) configured with appropriate credentials
- An AWS account with SES in sandbox or production mode
- SES email identity verified (`rempisivan@gmail.com`)

## Usage

### 1. Initialize Terraform

```bash
cd portfolio-infra
terraform init
```

### 2. Review the plan

```bash
terraform plan
```

### 3. Deploy

```bash
terraform apply
```

### 4. Get the API endpoint

After a successful apply, Terraform will output:

```
contact_api_url = "https://<id>.execute-api.ap-southeast-1.amazonaws.com/contact"
```

### 5. Test the endpoint

```bash
curl -X POST https://<id>.execute-api.ap-southeast-1.amazonaws.com/contact \
  -H "Content-Type: application/json" \
  -d '{"name": "John Doe", "email": "john@example.com", "message": "Hello!"}'
```

### 6. Destroy

```bash
terraform destroy
```

## API Reference

**`POST /contact`**

| Field     | Type   | Required | Description            |
| --------- | ------ | -------- | ---------------------- |
| `name`    | string | Yes      | Sender's name          |
| `email`   | string | Yes      | Sender's email address |
| `message` | string | Yes      | Message body           |

**Responses**

| Status | Meaning                                   |
| ------ | ----------------------------------------- |
| `200`  | Message saved and email sent successfully |
| `400`  | Missing required fields                   |
| `409`  | Duplicate message detected                |
| `429`  | Rate limit exceeded                       |
| `500`  | Internal server error                     |

## Region

All resources are deployed to `ap-southeast-1` (Singapore).
