# Tibet Compass

**Dhesel Khando**

---

## a. Problem and Use Case

### What problem are you solving?

Tibetan culture, language, and history are among the least accessible knowledge domains on the internet. For members of the Tibetan diaspora - particularly younger generations born outside Tibet - finding accurate, culturally grounded information requires navigating fragmented, often politically skewed sources. A Tibetan-American student in Nashville who wants to learn the correct pronunciation of a mantra, understand the historical significance of 1959, or find a scholarship specifically for Tibetan students has no single trusted, conversational resource.

Tibet Compass solves this by providing a single intelligent interface that routes questions to the right knowledge domain automatically, giving rich, culturally accurate answers in natural language.

### Who is the user?

- Members of the Tibetan diaspora (US, India, Europe) seeking cultural connection
- Students researching Tibetan history, religion, or language
- Educators and journalists needing accurate cultural context
- Anyone curious about Tibetan Buddhism, art, food, or history

### What does the application do?

Tibet Compass is a chat-based web application where users ask questions in natural language. The LLM reads each question and decides which of five specialized knowledge tools to invoke - or answers directly from its training if no tool is needed. It returns a rich, contextual response with a visible "tool badge" showing which domain was consulted.

---

## b. System Design

### High-level architecture

```
User (Browser)
    ↓ POST /ask (JSON: message, userId, conversationId)
AWS Amplify (Frontend - index.html)
    ↓
API Gateway HTTP API - tibet-compass-api
    ↓
AWS Lambda - tibet-compass-lambda (Python 3.12, 60s, 512MB)
    ↓
Amazon Bedrock - Converse API (amazon.nova-lite-v1:0)
    ↓ LLM selects tool
    ├── cultural_facts    → culture.json keyword search
    ├── translate_phrase  → phrases.json lookup
    ├── historical_context→ history.json keyword search
    ├── diaspora_resources→ resources.json keyword search
    └── tell_story        → LLM narrative generation (Turn 2)
    ↓
DynamoDB: TibetCompassHistory  (conversation memory)
DynamoDB: TibetCompassLogs     (observability - one record per request)
```

### Main components

| Component | Service | Purpose |
|---|---|---|
| Frontend | AWS Amplify | Tibet-themed Bootstrap chat UI. Tool badges display which domain was used per response. |
| API | API Gateway HTTP API | Single route: `POST /ask`. CORS-enabled. |
| Backend | AWS Lambda | Agentic loop: Bedrock Converse API + tool dispatch + DynamoDB read/write |
| LLM | Bedrock (Nova Lite) | Reads tool descriptions, selects the right tool, synthesizes final response |
| Knowledge Base | JSON files (in Lambda package) | Four domain-specific files: culture, history, phrases, resources |
| Memory | DynamoDB TibetCompassHistory | Per-user conversation history (PK=USER#, SK=CONV#) enabling multi-turn dialogue |
| Observability | DynamoDB TibetCompassLogs | One structured log record per request |

### How the agentic behavior is implemented

The agentic loop runs inside Lambda in two turns using the Bedrock Converse API:

**Turn 1:** The full message history + user input + all 5 tool definitions (toolConfig) are sent to Nova Lite. The LLM reads each tool's description and decides whether to call one, which one, and with what input - or returns an answer directly (`end_turn`).

**Turn 2 (if tool used):** The tool executes locally (keyword search against JSON), the result is appended to the message history as a `toolResult`, and a second Converse call generates the final natural-language response incorporating the retrieved knowledge.

```
Turn 1: LLM → stopReason == "tool_use" → execute tool locally
Turn 2: LLM + tool result → final response

OR

Turn 1: LLM → stopReason == "end_turn" → return directly (no tool)
```

---

## c. Why the System is Agentic

### What decisions is the LLM making?

On every request, the LLM makes two independent decisions:

1. **Whether to use a tool at all.** For a greeting like "Tashi Delek! What can you help me with?" - the model returns directly with no tool invoked (`tool_used: null`).
2. **Which of the five tools to invoke.** The model reads each tool's description and maps the user's intent: a question about "thangka painting" routes to `cultural_facts`; "what does Om Mani Padme Hum mean?" routes to `translate_phrase`; "what happened in 1959?" routes to `historical_context`. These are genuinely different behaviors with different knowledge sources.

### What tools or workflow choices does it control?

The LLM controls:
- Tool selection from 5 options (plus direct response)
- The input it passes to the tool (e.g., the exact query string used for keyword search)
- For `tell_story`, it controls the narrative structure in Turn 2 based on the theme it identified

### Why is this meaningfully agentic rather than just a fixed pipeline?

A fixed pipeline would use keyword matching or regex rules to route queries: "if 'festival' in query → call culture tool." Tibet Compass does not do this. The routing logic is embedded in natural language tool descriptions that the LLM interprets at inference time. This means:

- "What do Tibetans eat?" and "Tell me about traditional Tibetan food" both route to `cultural_facts` despite having no overlapping keywords with the tool name
- Ambiguous queries (e.g., "Tell me about the Dalai Lama's life") correctly route to `historical_context` even though "culture" might seem relevant
- Conversational questions with no clear domain route directly with no tool - the LLM decides a tool is unnecessary
- The routing is non-deterministic: different phrasings of the same question may produce different (but reasonable) tool selections

In our 20-query evaluation, the system achieved 100% correct routing - but more importantly, every routing decision was made by the LLM reading intent, not by a hardcoded rule.

---

## d. Technical Choices and Rationale

### Model: Amazon Nova Lite (`amazon.nova-lite-v1:0`)

Nova Lite was chosen because it supports the Bedrock Converse API with tool use natively, requires no model access approval form (unlike Claude on Bedrock), and is fast enough for sub-5 second responses. Nova Pro or Claude would give richer responses but at higher cost and latency. For a knowledge companion focused on retrieval + synthesis, Nova Lite performs well - as confirmed by our evaluation results.

### Orchestration: Custom (no framework)

No LangGraph, CrewAI, or LangChain was used. The agentic loop is 30 lines of Python in `lambda_function.py`. This was intentional: the two-turn Converse API pattern is simple enough that a framework would add complexity without benefit. Custom orchestration also makes the system easier to debug (direct CloudWatch logs) and cheaper to run (no framework overhead).

### Knowledge Base: JSON files (keyword search)

The domain knowledge is stored as structured JSON files bundled inside the Lambda package. Retrieval is a simple keyword intersection between the query words and each entry's `keywords[]` array. This is not RAG - there is no vector database. The choice was deliberate:

- The knowledge domain is small and curated (< 100 entries across 4 files)
- Keyword search is deterministic, zero-latency, and zero-cost
- It loads once at cold start and is cached on warm invocations
- For a project of this scope, semantic search would add infrastructure complexity with minimal benefit

If the system scaled to thousands of entries, migrating to OpenSearch or pgvector would be the natural next step.

### Database: DynamoDB (on-demand)

DynamoDB was chosen for consistency with the course's AWS ecosystem and because the data model is simple key-value (no joins needed). Two tables with `PK/SK` composite keys handle both conversation memory and observability logs. On-demand billing means zero cost when idle.

### Deployment: Lambda + API Gateway + Amplify

All three are AWS managed services requiring no server provisioning. Lambda handles compute elasticity; API Gateway provides a clean HTTP interface with CORS; Amplify serves the static frontend with a CDN. This mirrors the HW2 architecture and is appropriate for a project with unpredictable, bursty traffic.

---

## e. Observability

### What was implemented

Every Lambda invocation writes one structured record to the `TibetCompassLogs` DynamoDB table, regardless of success or failure:

```json
{
  "PK": "LOG#<userId>",
  "SK": "TS#<epoch_ms>#<uuid8>",
  "user_input": "...",
  "tool_selected": "cultural_facts",
  "tool_input": "{\"query\": \"Losar festival\"}",
  "tool_output": "...(first 500 chars)...",
  "final_response": "...(first 500 chars)...",
  "latency_ms": 3045,
  "timestamp": "2026-04-23T22:30:00",
  "conversation_id": "...",
  "error": ""
}
```

### What it captures

- **User input:** Full text of every message sent
- **Tool calls:** Which tool was selected (or `none`) and the exact input passed to it
- **Tool output:** First 500 chars of the knowledge base result returned to the LLM
- **Model output:** First 500 chars of the final response
- **Latency:** End-to-end Lambda execution time in milliseconds
- **Errors:** Any exception message if the agentic loop failed

### How it helps inspect system behavior

- **Routing inspection:** Scan all logs and count `tool_selected` values to see distribution - done by `compute_metrics.py`
- **Failure debugging:** Filter `error != ""` to find all failed requests and read the exception
- **Latency tracking:** Sort by `latency_ms` to identify slow queries; P95 outliers are visible in the scan
- **Conversation replay:** All turns for a given `conversation_id` can be reconstructed by querying PK=`LOG#<userId>`

From our 57 logged requests, 2 errors (3.5%) were identified - both were early invocations before the `toolConfig` bug fix was deployed.

---

## f. Metrics

### Metric 1: Tool Routing Accuracy (Quality metric)

**Definition:** The fraction of queries where the LLM selects the expected tool domain.

**Why it matters:** Tool routing is the core agentic behavior of Tibet Compass. If the LLM routes "What happened in 1959?" to `translate_phrase`, the answer will be wrong or missing. Routing accuracy directly measures whether the agentic decision-making is working correctly.

**How tracked:** `evaluate.py` sends 20 representative queries (4 per domain), compares `actual_tool` against `expected_tool`, and reports accuracy. The tool selection is also logged in DynamoDB for ongoing monitoring.

**Result:** **20/20 (100%)** - all queries routed to the correct tool domain.

| Domain | Queries | Correct |
|---|---|---|
| Culture | 4 | 4 |
| Translation | 4 | 4 |
| History | 4 | 4 |
| Resources | 4 | 4 |
| Story | 4 | 4 |
| **Total** | **20** | **20 (100%)** |

### Metric 2: Response Latency P50 / P95 (Operations metric)

**Definition:** The 50th and 95th percentile of end-to-end Lambda execution time (ms), measured from request receipt to response body written.

**Why it matters:** Latency directly affects user experience. A cultural knowledge tool that takes 10+ seconds per response will be abandoned. P50 measures typical user experience; P95 exposes the tail cases that frustrate users.

**How tracked:** `latency_ms` is recorded in every DynamoDB log entry. `compute_metrics.py` scans the table and computes percentiles.

**Results (57 requests):**

| Metric | Value |
|---|---|
| P50 (median) | 2,813 ms |
| P95 | 6,684 ms |
| Mean | 2,919 ms |
| Min | 792 ms |
| Max | 8,471 ms |

The 2-turn agentic loop (tool invocation + synthesis) accounts for the ~3s median. Single-turn direct responses are faster (~1–1.5s). P95 of 6.7s represents complex story generation queries where Nova Lite produces longer narrative outputs.

### Tool Distribution (Bonus metric from DynamoDB scan)

| Tool | Count | % |
|---|---|---|
| cultural_facts | 12 | 21.1% |
| historical_context | 11 | 19.3% |
| diaspora_resources | 11 | 19.3% |
| translate_phrase | 10 | 17.5% |
| tell_story | 9 | 15.8% |
| none (direct) | 4 | 7.0% |

Tool usage is remarkably balanced across all domains, confirming the tool descriptions are well-calibrated and the system is genuinely routing by intent rather than defaulting to one tool.

---

## g. Evaluation

### Methodology

20 representative queries were sent to the live API (4 per domain). For each, the expected tool was specified and compared against the actual `tool_used` field in the response. Responses were reviewed for cultural accuracy and relevance.

### Routing Accuracy: 20/20 (100%)

Every query was routed to the correct tool. This exceeded the target of 18/20 (90%).

### Representative successes

**Culture - Thangka painting:**
> "Describe the art of thangka painting"
> → Tool: `cultural_facts` | Latency: 2,061ms
> Response correctly described canvas material, iconographic rules, silk brocade mounting, and meditation use - all sourced from the knowledge base and expanded by Nova Lite.

**Translation - Mantra:**
> "What does Om Mani Padme Hum mean?"
> → Tool: `translate_phrase` | Latency: 1,981ms
> Response included Tibetan script (ཨོཾ་མ་ཎི་པདྨེ་ཧཱུྂ།), Wylie romanization, syllable-by-syllable meaning, and cultural context about Chenrezig.

**Story generation:**
> "Narrate the journey of a Tibetan family crossing the Himalayas to freedom"
> → Tool: `tell_story` | Latency: 3,448ms
> Produced a 4-paragraph narrative with culturally specific details (mani stones, Dharamsala, tsampa) - the LLM correctly used the tool sentinel to generate a narrative in Turn 2 rather than a fact lookup.

**Direct (no tool):**
> "Tashi Delek! What can you help me with?"
> → Tool: `none` | Latency: 1,181ms
> Correctly identified this as a conversational greeting requiring no knowledge retrieval, responded directly with a friendly domain overview.

### Failure cases and limitations

1. **Knowledge base gaps:** The JSON files cover approximately 25 topics per domain. Questions about very specific topics (e.g., "Tell me about the Gesar epic") return accurate but less detailed answers, supplemented from Nova Lite's training data rather than the curated knowledge base.

2. **Story quality variability:** The `tell_story` tool produces consistently structured narratives, but occasionally uses slightly generic "exile diaspora" framing without enough specificity to the requested theme. More detailed story templates would help.

3. **Multi-domain queries:** A question like "Tell me the history of thangka painting and teach me to say 'beautiful painting' in Tibetan" would ideally call two tools. The current single-tool loop will route to one domain and ignore the other. A multi-step planner would address this.

4. **Latency on cold start:** First invocation after idle periods takes ~1.5s extra due to Lambda cold start and knowledge base loading (~5–6s total for first request). Provisioned concurrency would eliminate this.

### Tradeoffs observed

- **Keyword search vs. semantic retrieval:** Keyword matching is fast and free but misses synonyms. A question about "Tibetan butter tea" finds the `po cha` entry correctly (keyword "butter tea" matches), but "What is yak butter beverage?" would miss it. Semantic embeddings would improve recall.
- **Nova Lite vs. Claude:** Nova Lite is faster and cheaper but occasionally produces longer, more verbose responses than necessary. Claude Haiku would give more concise, sharper answers but requires a different approval process.
- **Two-turn loop vs. streaming:** The two-turn loop adds ~1–2s compared to a direct call. Streaming would make the latency feel shorter to the user even if total time is the same.

### What would be improved next

1. Add multi-tool calling support for complex queries spanning multiple domains
2. Expand knowledge base to 200+ entries per domain
3. Add semantic search (OpenSearch or DynamoDB with embedding vectors)
4. Stream responses to improve perceived latency
5. Add user feedback buttons (thumbs up/down) to collect quality signal automatically

---

## h. Deployment

### Where and how

| Layer | Service | Details |
|---|---|---|
| Frontend | AWS Amplify | Manual deployment via S3 presigned URL. URL: https://main.d3k747k0gvjsw5.amplifyapp.com |
| API | AWS API Gateway (HTTP API) | `POST /ask` route, prod stage. URL: https://yyll5i6nsc.execute-api.us-east-1.amazonaws.com/prod/ask |
| Backend | AWS Lambda | `tibet-compass-lambda`, Python 3.12, 512MB, 60s timeout, us-east-1 |
| Database | AWS DynamoDB | Two tables: `TibetCompassHistory`, `TibetCompassLogs` - on-demand billing |
| Model | Amazon Bedrock | `amazon.nova-lite-v1:0` - enabled via Bedrock model access console |

### Deployment process

All infrastructure was provisioned via `deploy.sh` - a Bash script that creates all AWS resources in order: DynamoDB tables → IAM role → Lambda → API Gateway → Amplify. The script is idempotent: re-running it skips already-existing resources and only updates what changed.

### Practical constraints

- **Model availability:** Nova Lite must be explicitly enabled in the Bedrock console before the first invocation. The deploy script checks availability and exits with a clear error if not enabled.
- **IAM propagation:** After creating the IAM role, a 10-second sleep is required before Lambda can assume it.
- **Amplify manual deployment:** Amplify's `create-deployment` API uses a `zipUploadUrl` (not `fileUploadUrls`) for zip-based uploads. The index.html must be at the zip root.
- **Knowledge base size:** All four JSON files total ~60KB and load at cold start. No external database calls are made for retrieval - this keeps latency low.

---

## i. Reflection

### What I learned

1. **Bedrock Converse API tool use requires `toolConfig` in every call** - not just Turn 1. If the message history contains `toolUse` or `toolResult` blocks, Bedrock validates that `toolConfig` is present in the subsequent call. This caught me by surprise and required a quick fix after deployment.

2. **Nova Lite surfaces its reasoning in `<thinking>` tags** that appear in the response text. These needed to be stripped with a regex before returning to the user. This is a model-specific quirk not documented prominently.

3. **Well-written tool descriptions do most of the work.** I initially had brief one-line descriptions for each tool. After expanding them to include specific example triggers ("Use for 'how do you say X in Tibetan'") the routing accuracy jumped significantly. The tool description IS the routing logic in an LLM-based system.

4. **Keyword search is surprisingly effective at small scale.** I expected to need vector search, but simple word intersection with curated `keywords[]` arrays handles all 20 evaluation queries correctly because the knowledge entries are specific and non-overlapping.

5. **AWS Amplify's manual deployment API is counterintuitive** - `create-deployment` returns a `zipUploadUrl` for uploading a zip file, not per-file URLs. The zip must contain `index.html` at the root (not in a subdirectory).

### What would I improve with more time

1. **Semantic retrieval:** Replace keyword matching with embedding-based similarity search. This would handle paraphrasing ("yak butter beverage" → po cha) and cross-lingual queries.
2. **Multi-tool calling:** Handle queries that span two domains in a single response by chaining tool calls.
3. **User feedback loop:** Add thumbs up/down buttons that write quality signals back to DynamoDB, enabling continuous improvement monitoring.
4. **Streaming responses:** Implement Bedrock `ConverseStream` so users see tokens appearing rather than waiting 3s for the full response.
5. **Expand knowledge base:** Grow from ~25 to 200+ entries per domain, covering Tibetan medicine (Sowa Rigpa), regional dialects (Amdo, Kham, Lhasa), and contemporary diaspora issues.

### What design choices I would revisit

- **JSON keyword search:** It works at this scale, but I'd architect the retrieval layer with a cleaner interface from the start so swapping to semantic search is a one-line change.
- **`tell_story` sentinel pattern:** Returning `"STORY_THEME:<theme>"` as a string sentinel is fragile. A cleaner design would have `tell_story` return a structured dict with `{"mode": "narrative", "theme": "..."}` that the Lambda interprets before building the Turn 2 prompt.
- **Single DynamoDB table:** The history and logs tables could share one table with different PK prefixes (`USER#`, `LOG#`), reducing the number of resources to manage.

---

## Acknowledgements

This report's grammar and language were refined with the assistance of the Claude language model (Anthropic, 2024).
