# 🏔 Tibet Compass

**DS5730 Final Project | Dhesel Khando**

An agentic LLM-powered web application that serves as a cultural knowledge companion for Tibetan culture, language, history, and diaspora — built on AWS using the Bedrock Converse API with tool use.

---

## What Makes It Agentic?

Tibet Compass uses **Amazon Nova Lite** (via Bedrock Converse API) to **autonomously decide** which specialized knowledge tool to invoke based on the user's query intent:

| Tool | Triggers When... | Knowledge Source |
|---|---|---|
| `cultural_facts` | Questions about festivals, food, arts, religion | `culture.json` |
| `translate_phrase` | Translation requests, phrase/mantra meaning | `phrases.json` |
| `historical_context` | Historical events, figures, diaspora history | `history.json` |
| `diaspora_resources` | Organizations, scholarships, mental health support | `resources.json` |
| `tell_story` | Story/narrative requests | LLM-generated narrative |
| *(direct)* | General conversation, no tool needed | LLM direct response |

This routing is **non-deterministic** — the LLM reads each tool's description and decides based on query intent, not a hardcoded if/else pipeline.

---

## Architecture

```
Frontend (Amplify) — Tibet-themed chat UI (tool badge, warm crimson/gold colors)
    ↓ POST /ask
API Gateway HTTP API
    ↓
Lambda: tibet-compass-lambda (Python 3.12, 60s, 512MB)
    ↓
Bedrock Converse API (amazon.nova-lite-v1:0)
    ↓ LLM selects tool → up to 2 turns
    ├── cultural_facts    → culture.json keyword search
    ├── translate_phrase  → phrases.json keyword search
    ├── historical_context→ history.json keyword search
    ├── diaspora_resources→ resources.json keyword search
    └── tell_story        → LLM narrative generation
    ↓
DynamoDB: TibetCompassHistory (conversation memory, PK=USER#, SK=CONV#)
DynamoDB: TibetCompassLogs    (observability — tool, latency, error per request)
```

---

## Project Structure

```
TibetCompass/
├── deploy.sh                  # One-command AWS deployment
├── README.md
├── .env.example
├── evaluate.py                # 20-query evaluation runner
├── compute_metrics.py         # P50/P95 latency + tool distribution from DynamoDB
├── frontend/
│   └── index.html             # Bootstrap chat UI (tool badges, sample questions)
├── lambda/
│   ├── lambda_function.py     # Agentic loop: Converse API + tool dispatch + DynamoDB
│   └── knowledge/
│       ├── culture.json       # Festivals, food, arts, religion
│       ├── history.json       # Ancient, modern, diaspora history
│       ├── phrases.json       # Greetings, everyday, spiritual phrases
│       └── resources.json     # Orgs, scholarships, mental health
└── iam/
    ├── trust-policy.json      # Lambda trust policy
    └── lambda-policy.json     # DynamoDB + Bedrock permissions
```

---

## Deployment

### Prerequisites
- AWS CLI configured (`aws configure`)
- Amazon Nova Lite enabled in [Bedrock Model Access](https://console.aws.amazon.com/bedrock/home#/modelaccess)
- `gh` CLI (optional, for GitHub push)

### Deploy
```bash
cd /Users/dhekha/Desktop/TibetCompass
chmod +x deploy.sh
./deploy.sh
```

The script:
1. Checks Nova Lite availability
2. Creates two DynamoDB tables
3. Sets up IAM role + policy
4. Packages and deploys Lambda (includes knowledge/ JSON files)
5. Creates API Gateway HTTP API with `POST /ask` route
6. Injects API URL into frontend HTML
7. Deploys to Amplify
8. Pushes to GitHub (if `gh` is authenticated)

---

## Smoke Tests

After deployment, the script prints 5 ready-to-run curl commands, one per tool:

```bash
# Culture
curl -s -X POST 'YOUR_API_URL' -H 'Content-Type: application/json' \
  -d '{"message": "Tell me about Losar festival", "userId": "test"}' | python3 -m json.tool

# Translation
curl -s -X POST 'YOUR_API_URL' -H 'Content-Type: application/json' \
  -d '{"message": "How do you say thank you in Tibetan?", "userId": "test"}' | python3 -m json.tool

# History
curl -s -X POST 'YOUR_API_URL' -H 'Content-Type: application/json' \
  -d '{"message": "What happened in Tibet in 1959?", "userId": "test"}' | python3 -m json.tool

# Resources
curl -s -X POST 'YOUR_API_URL' -H 'Content-Type: application/json' \
  -d '{"message": "What scholarships are available for Tibetan students?", "userId": "test"}' | python3 -m json.tool

# Story
curl -s -X POST 'YOUR_API_URL' -H 'Content-Type: application/json' \
  -d '{"message": "Tell me a story about a Tibetan family celebrating Losar in exile", "userId": "test"}' | python3 -m json.tool
```

Each response includes `tool_used` field.

---

## Evaluation

### Run 20-query eval:
```bash
python3 evaluate.py --api-url YOUR_API_URL
```
Opens `eval_results.json` — fill in `relevance`, `cultural_accuracy`, `quality` (1–5) for each entry.

**Targets:** 18/20 correct routing · avg quality ≥ 3.5

### Compute metrics from DynamoDB:
```bash
python3 compute_metrics.py
python3 compute_metrics.py --chart --output metrics.json
```
Prints P50/P95 latency and tool distribution.

---

## Metrics Tracked

| Metric | How |
|---|---|
| Tool routing accuracy | 20-query eval, expected vs actual tool |
| Latency P50/P95 | DynamoDB Logs scan → compute_metrics.py |
| Error rate | `error` field in each log entry |
| Tool distribution | Counter across all log entries |

---

## AWS Resources

| Service | Resource |
|---|---|
| DynamoDB | TibetCompassHistory |
| DynamoDB | TibetCompassLogs |
| IAM | tibet-compass-lambda-role |
| Lambda | tibet-compass-lambda (Python 3.12, 60s, 512MB) |
| API Gateway | tibet-compass-api (HTTP API, POST /ask) |
| Amplify | tibet-compass-app |
| Bedrock | amazon.nova-lite-v1:0 |

---

*བཀྲ་ཤིས་བདེ་ལེགས། Tashi Delek!*
