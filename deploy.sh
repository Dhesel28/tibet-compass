#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Tibet Compass — Automated AWS Deployment Script
# DS5730 Final Project | Dhesel Khando
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────
LAMBDA_NAME="tibet-compass-lambda"
DYNAMO_TABLE_HISTORY="TibetCompassHistory"
DYNAMO_TABLE_LOGS="TibetCompassLogs"
API_NAME="tibet-compass-api"
AMPLIFY_APP_NAME="tibet-compass-app"
IAM_ROLE_NAME="tibet-compass-lambda-role"
REGION="us-east-1"
RUNTIME="python3.12"
TIMEOUT=60
MEMORY=512
MODEL_ID="amazon.nova-lite-v1:0"
FALLBACK_MODEL="amazon.nova-pro-v1:0"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; }
info() { echo -e "${CYAN}[→]${NC} $*"; }

echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        Tibet Compass — AWS Deployment             ║${NC}"
echo -e "${BLUE}║        DS5730 Final Project | Dhesel Khando       ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# ─── Step 0: Pre-flight checks ────────────────────────────────────────────────
info "Step 0: Pre-flight checks..."

# Check AWS CLI
if ! aws sts get-caller-identity --region $REGION &>/dev/null; then
    err "AWS CLI not configured or no credentials. Run: aws configure"
    exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "AWS Account: $ACCOUNT_ID | Region: $REGION"

# Check Nova Lite availability
info "Checking Nova Lite (${MODEL_ID}) availability..."
NOVA_LITE=$(aws bedrock list-foundation-models --region $REGION \
  --query "modelSummaries[?modelId=='${MODEL_ID}'].modelId" \
  --output text 2>/dev/null || echo "")

if [ -z "$NOVA_LITE" ]; then
    warn "amazon.nova-lite-v1:0 not found via API listing."
    warn "This may be a listing issue. Checking nova-pro as fallback reference..."
    NOVA_PRO=$(aws bedrock list-foundation-models --region $REGION \
      --query "modelSummaries[?contains(modelId,'nova')].modelId" \
      --output text 2>/dev/null || echo "")
    if [ -z "$NOVA_PRO" ]; then
        err "No Nova models available. Enable them at:"
        err "https://console.aws.amazon.com/bedrock/home#/modelaccess"
        err "Enable: Amazon Nova Lite, then re-run this script."
        exit 1
    fi
    warn "Nova models found: $NOVA_PRO"
    warn "Will use ${MODEL_ID} — if it fails at runtime, update MODEL_ID in lambda to ${FALLBACK_MODEL}"
else
    log "Nova Lite confirmed available: $NOVA_LITE"
fi

# ─── Step 1: DynamoDB Tables ──────────────────────────────────────────────────
info "Step 1: Creating DynamoDB tables..."

create_table() {
    local TABLE_NAME=$1
    EXISTING=$(aws dynamodb list-tables --region $REGION \
      --query "TableNames[?@=='${TABLE_NAME}']" --output text 2>/dev/null || echo "")
    if [ -n "$EXISTING" ]; then
        log "Table $TABLE_NAME already exists — skipping"
    else
        aws dynamodb create-table \
          --table-name "$TABLE_NAME" \
          --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
          --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
          --billing-mode PAY_PER_REQUEST \
          --region $REGION > /dev/null
        log "Created DynamoDB table: $TABLE_NAME"
        aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region $REGION
        log "$TABLE_NAME is ACTIVE"
    fi
}

create_table "$DYNAMO_TABLE_HISTORY"
create_table "$DYNAMO_TABLE_LOGS"

# ─── Step 2: IAM Role ─────────────────────────────────────────────────────────
info "Step 2: Setting up IAM role..."

ROLE_ARN=$(aws iam get-role --role-name "$IAM_ROLE_NAME" \
  --query "Role.Arn" --output text 2>/dev/null || echo "")

if [ -z "$ROLE_ARN" ]; then
    ROLE_ARN=$(aws iam create-role \
      --role-name "$IAM_ROLE_NAME" \
      --assume-role-policy-document file://iam/trust-policy.json \
      --query "Role.Arn" --output text)
    log "Created IAM role: $IAM_ROLE_NAME"
    sleep 10  # propagation delay
else
    log "IAM role $IAM_ROLE_NAME already exists"
fi
log "Role ARN: $ROLE_ARN"

# Attach/update inline policy
aws iam put-role-policy \
  --role-name "$IAM_ROLE_NAME" \
  --policy-name "${IAM_ROLE_NAME}-policy" \
  --policy-document file://iam/lambda-policy.json
log "IAM policy attached"

# Attach AWSLambdaBasicExecutionRole
aws iam attach-role-policy \
  --role-name "$IAM_ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
  2>/dev/null || true
log "AWSLambdaBasicExecutionRole attached"

# ─── Step 3: Lambda Function ──────────────────────────────────────────────────
info "Step 3: Packaging and deploying Lambda..."

# Build deployment package
rm -rf package/ tibet_compass.zip
mkdir -p package

# Copy function code
cp lambda/lambda_function.py package/
cp -r lambda/knowledge/ package/knowledge/

# Zip it
cd package && zip -r ../tibet_compass.zip . -x "*.pyc" -x "*__pycache__*" > /dev/null && cd ..
log "Lambda package built: tibet_compass.zip ($(du -sh tibet_compass.zip | cut -f1))"

# Check if function exists
FUNC_EXISTS=$(aws lambda get-function --function-name "$LAMBDA_NAME" \
  --region $REGION --query "Configuration.FunctionName" --output text 2>/dev/null || echo "")

if [ -z "$FUNC_EXISTS" ]; then
    aws lambda create-function \
      --function-name "$LAMBDA_NAME" \
      --runtime "$RUNTIME" \
      --role "$ROLE_ARN" \
      --handler "lambda_function.lambda_handler" \
      --zip-file fileb://tibet_compass.zip \
      --timeout $TIMEOUT \
      --memory-size $MEMORY \
      --environment "Variables={HISTORY_TABLE=${DYNAMO_TABLE_HISTORY},LOGS_TABLE=${DYNAMO_TABLE_LOGS}}" \
      --region $REGION > /dev/null
    log "Lambda function created: $LAMBDA_NAME"
    aws lambda wait function-active --function-name "$LAMBDA_NAME" --region $REGION
else
    # Update existing
    aws lambda update-function-code \
      --function-name "$LAMBDA_NAME" \
      --zip-file fileb://tibet_compass.zip \
      --region $REGION > /dev/null
    aws lambda wait function-updated --function-name "$LAMBDA_NAME" --region $REGION

    aws lambda update-function-configuration \
      --function-name "$LAMBDA_NAME" \
      --timeout $TIMEOUT \
      --memory-size $MEMORY \
      --environment "Variables={HISTORY_TABLE=${DYNAMO_TABLE_HISTORY},LOGS_TABLE=${DYNAMO_TABLE_LOGS}}" \
      --region $REGION > /dev/null
    aws lambda wait function-updated --function-name "$LAMBDA_NAME" --region $REGION
    log "Lambda function updated: $LAMBDA_NAME"
fi

LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_NAME" \
  --region $REGION --query "Configuration.FunctionArn" --output text)
log "Lambda ARN: $LAMBDA_ARN"

# ─── Step 4: API Gateway (HTTP API) ───────────────────────────────────────────
info "Step 4: Setting up API Gateway..."

# Check if API already exists
API_ID=$(aws apigatewayv2 get-apis --region $REGION \
  --query "Items[?Name=='${API_NAME}'].ApiId" --output text 2>/dev/null || echo "")

if [ -z "$API_ID" ]; then
    API_ID=$(aws apigatewayv2 create-api \
      --name "$API_NAME" \
      --protocol-type HTTP \
      --cors-configuration AllowOrigins='*',AllowMethods='POST,OPTIONS',AllowHeaders='Content-Type' \
      --region $REGION \
      --query "ApiId" --output text)
    log "Created HTTP API: $API_NAME (ID: $API_ID)"
else
    log "API $API_NAME already exists (ID: $API_ID)"
fi

# Lambda integration
INTEGRATION_ID=$(aws apigatewayv2 get-integrations \
  --api-id "$API_ID" --region $REGION \
  --query "Items[0].IntegrationId" --output text 2>/dev/null || echo "")

if [ -z "$INTEGRATION_ID" ] || [ "$INTEGRATION_ID" == "None" ]; then
    INTEGRATION_ID=$(aws apigatewayv2 create-integration \
      --api-id "$API_ID" \
      --integration-type AWS_PROXY \
      --integration-uri "$LAMBDA_ARN" \
      --payload-format-version "2.0" \
      --region $REGION \
      --query "IntegrationId" --output text)
    log "Created Lambda integration: $INTEGRATION_ID"
fi

# Create route POST /ask
ROUTE_EXISTS=$(aws apigatewayv2 get-routes --api-id "$API_ID" --region $REGION \
  --query "Items[?RouteKey=='POST /ask'].RouteId" --output text 2>/dev/null || echo "")
if [ -z "$ROUTE_EXISTS" ] || [ "$ROUTE_EXISTS" == "None" ]; then
    aws apigatewayv2 create-route \
      --api-id "$API_ID" \
      --route-key "POST /ask" \
      --target "integrations/$INTEGRATION_ID" \
      --region $REGION > /dev/null
    log "Created route: POST /ask"
fi

# Create/update stage
STAGE_EXISTS=$(aws apigatewayv2 get-stages --api-id "$API_ID" --region $REGION \
  --query "Items[?StageName=='prod'].StageName" --output text 2>/dev/null || echo "")
if [ -z "$STAGE_EXISTS" ]; then
    aws apigatewayv2 create-stage \
      --api-id "$API_ID" \
      --stage-name "prod" \
      --auto-deploy \
      --region $REGION > /dev/null
    log "Created stage: prod"
else
    log "Stage prod already exists"
fi

# Lambda permission for API Gateway
aws lambda add-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id "allow-apigw-${API_ID}" \
  --action "lambda:InvokeFunction" \
  --principal "apigateway.amazonaws.com" \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*" \
  --region $REGION > /dev/null 2>&1 || true

API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com/prod/ask"
log "API Gateway URL: $API_URL"

# ─── Step 5: Inject API URL into frontend ────────────────────────────────────
info "Step 5: Injecting API URL into frontend..."
sed -i.bak "s|__API_GATEWAY_URL__|${API_URL}|g" frontend/index.html
log "API URL injected into frontend/index.html"

# ─── Step 6: Amplify Deployment ───────────────────────────────────────────────
info "Step 6: Deploying frontend to Amplify..."

# Check if Amplify app already exists
AMPLIFY_APP_ID=$(aws amplify list-apps --region $REGION \
  --query "apps[?name=='${AMPLIFY_APP_NAME}'].appId" --output text 2>/dev/null || echo "")

if [ -z "$AMPLIFY_APP_ID" ]; then
    AMPLIFY_APP_ID=$(aws amplify create-app \
      --name "$AMPLIFY_APP_NAME" \
      --region $REGION \
      --query "app.appId" --output text)
    log "Created Amplify app: $AMPLIFY_APP_NAME (ID: $AMPLIFY_APP_ID)"
else
    log "Amplify app $AMPLIFY_APP_NAME already exists (ID: $AMPLIFY_APP_ID)"
fi

# Create branch 'main'
BRANCH_EXISTS=$(aws amplify list-branches --app-id "$AMPLIFY_APP_ID" --region $REGION \
  --query "branches[?branchName=='main'].branchName" --output text 2>/dev/null || echo "")
if [ -z "$BRANCH_EXISTS" ]; then
    aws amplify create-branch \
      --app-id "$AMPLIFY_APP_ID" \
      --branch-name "main" \
      --region $REGION > /dev/null
    log "Created Amplify branch: main"
fi

# Create zip of frontend for Amplify (index.html at root of zip)
cd frontend
zip -j ../frontend.zip index.html > /dev/null
cd ..
log "Frontend zip created"

# Create deployment — returns zipUploadUrl
DEPLOYMENT=$(aws amplify create-deployment \
  --app-id "$AMPLIFY_APP_ID" \
  --branch-name "main" \
  --region $REGION)
JOB_ID=$(echo "$DEPLOYMENT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['jobId'])")
ZIP_UPLOAD_URL=$(echo "$DEPLOYMENT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['zipUploadUrl'])")

# Upload zip to Amplify presigned URL
curl -s -X PUT \
  -H "Content-Type: application/zip" \
  --data-binary @frontend.zip \
  "$ZIP_UPLOAD_URL" > /dev/null
log "Frontend uploaded to Amplify"

# Start deployment
aws amplify start-deployment \
  --app-id "$AMPLIFY_APP_ID" \
  --branch-name "main" \
  --job-id "$JOB_ID" \
  --region $REGION > /dev/null

AMPLIFY_URL="https://main.${AMPLIFY_APP_ID}.amplifyapp.com"
log "Amplify URL: $AMPLIFY_URL"

# ─── Step 7: GitHub Setup ─────────────────────────────────────────────────────
info "Step 7: GitHub setup..."

# Create .gitignore
cat > .gitignore << 'GITEOF'
.env
*.zip
package/
__pycache__/
*.pyc
.DS_Store
frontend/index.html.bak
GITEOF

if ! git rev-parse --git-dir &>/dev/null; then
    git init
    log "Git repo initialized"
fi

if ! gh auth status &>/dev/null; then
    warn "GitHub CLI not authenticated. Skipping GitHub push."
    warn "Run: gh auth login && gh repo create tibet-compass --public --source=. --remote=origin --push"
else
    git add -A
    git commit -m "Tibet Compass: agentic LLM app — DS5730 final project" --allow-empty 2>/dev/null || true

    REPO_EXISTS=$(gh repo view tibet-compass &>/dev/null && echo "yes" || echo "")
    if [ -z "$REPO_EXISTS" ]; then
        gh repo create tibet-compass --public --source=. --remote=origin --push
        log "GitHub repo created and pushed: tibet-compass"
    else
        git push origin main --force 2>/dev/null || true
        log "GitHub repo updated"
    fi
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              Tibet Compass — Deployment Complete!         ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
log "API Endpoint:   $API_URL"
log "Frontend:       $AMPLIFY_URL"
log "Lambda:         $LAMBDA_NAME (timeout=${TIMEOUT}s, memory=${MEMORY}MB)"
log "DynamoDB:       $DYNAMO_TABLE_HISTORY + $DYNAMO_TABLE_LOGS"
echo ""
info "Smoke test — run these curls to verify each tool:"
echo ""
echo "  # Culture"
echo "  curl -s -X POST '$API_URL' -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"Tell me about Losar festival\", \"userId\": \"test\"}' | python3 -m json.tool"
echo ""
echo "  # Translation"
echo "  curl -s -X POST '$API_URL' -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"How do you say thank you in Tibetan?\", \"userId\": \"test\"}' | python3 -m json.tool"
echo ""
echo "  # History"
echo "  curl -s -X POST '$API_URL' -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"What happened in Tibet in 1959?\", \"userId\": \"test\"}' | python3 -m json.tool"
echo ""
echo "  # Resources"
echo "  curl -s -X POST '$API_URL' -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"What scholarships are available for Tibetan students?\", \"userId\": \"test\"}' | python3 -m json.tool"
echo ""
echo "  # Story"
echo "  curl -s -X POST '$API_URL' -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"Tell me a story about a Tibetan family celebrating Losar in exile\", \"userId\": \"test\"}' | python3 -m json.tool"
echo ""
log "Tashi Delek! (བཀྲ་ཤིས་བདེ་ལེགས།)"

# -------------------------------------------------------------------------------
# This code was developed with assistance from Claude (Anthropic AI).
# Claude was used to help with code structure, refactoring, and debugging.
# Final implementation, testing, and validation were done by the author.
# -------------------------------------------------------------------------------
