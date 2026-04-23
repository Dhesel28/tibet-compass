import json
import os
import re
import time
import uuid
import boto3
from datetime import datetime

# ─── AWS Clients ────────────────────────────────────────────────────────────────
bedrock  = boto3.client('bedrock-runtime', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

MODEL_ID      = 'amazon.nova-lite-v1:0'
HISTORY_TABLE = os.environ.get('HISTORY_TABLE', 'TibetCompassHistory')
LOGS_TABLE    = os.environ.get('LOGS_TABLE',    'TibetCompassLogs')

# ─── Knowledge Base (loaded once at cold start, cached on warm invocations) ─────
KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), 'knowledge')

def _load(fname):
    with open(os.path.join(KNOWLEDGE_DIR, fname)) as f:
        return json.load(f)

CULTURE_KB   = _load('culture.json')
HISTORY_KB   = _load('history.json')
PHRASES_KB   = _load('phrases.json')
RESOURCES_KB = _load('resources.json')

# ─── System Prompt ───────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are Tibet Compass, a knowledgeable and warm cultural guide for Tibetan history,
culture, language, and diaspora. You have access to specialized tools for different domains:

- cultural_facts: For questions about Tibetan festivals, food, arts, religion, and traditions
- translate_phrase: For translating or explaining Tibetan words, phrases, or mantras
- historical_context: For questions about Tibetan history, political events, and important figures
- diaspora_resources: For questions about Tibetan community organizations, scholarships, and support
- tell_story: For requests to tell a story, narrative, or creative account about Tibet

Always respond with warmth, cultural sensitivity, and depth. When you invoke a tool, use the knowledge
it returns to give a rich, contextual answer. If the knowledge base doesn't have a perfect match,
supplement with your broader knowledge while staying culturally accurate.

Tashi Delek! (བཀྲ་ཤིས་བདེ་ལེགས།)"""

# ─── Tool Definitions ────────────────────────────────────────────────────────────
TOOLS = [
    {
        "toolSpec": {
            "name": "cultural_facts",
            "description": "Look up information about Tibetan culture including festivals (Losar, Saga Dawa, Shoton), traditional foods (tsampa, butter tea, momos), arts (thangka, sand mandala, cham dance), and religion (Buddhism, Bon, prayer flags, mantras). Use for any question about Tibetan cultural practices and traditions.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The cultural topic or question to look up (e.g., 'Losar festival', 'butter tea', 'thangka painting')"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "translate_phrase",
            "description": "Translate or explain Tibetan words, phrases, greetings, and mantras. Provides Tibetan script, Wylie romanization, pronunciation, and cultural context. Use for 'how do you say X in Tibetan', 'what does X mean', 'teach me a Tibetan phrase', or any translation/language question.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "phrase": {
                            "type": "string",
                            "description": "The phrase, word, or concept to look up in Tibetan (e.g., 'hello', 'thank you', 'Om Mani Padme Hum', 'Tashi Delek')"
                        }
                    },
                    "required": ["phrase"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "historical_context",
            "description": "Retrieve historical information about Tibet including ancient history (Tibetan Empire, Songtsen Gampo, Samye monastery), modern history (1950 Chinese invasion, 1959 uprising and Dalai Lama's exile, Cultural Revolution), and diaspora history (settlements in India, US Tibetan community). Use for any historical question about Tibet.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "The historical topic or event to look up (e.g., '1959 uprising', 'Tibetan Empire', 'Dalai Lama exile', 'Cultural Revolution')"
                        }
                    },
                    "required": ["topic"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "diaspora_resources",
            "description": "Find information about Tibetan diaspora organizations, scholarships, mental health support, and community resources. Includes information about CTA, Tibet Fund, Students for a Free Tibet, scholarships for Tibetan students, and mental health services. Use when someone asks about support, organizations, scholarships, or diaspora community resources.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "need": {
                            "type": "string",
                            "description": "The type of resource or need (e.g., 'scholarship', 'mental health', 'community organization', 'advocacy', 'student support')"
                        }
                    },
                    "required": ["need"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "tell_story",
            "description": "Generate a narrative story, poem, or creative account related to Tibetan culture, history, or diaspora experience. Use when someone asks you to 'tell me a story', 'tell a tale', 'narrate', or requests a creative/narrative response about Tibet.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "theme": {
                            "type": "string",
                            "description": "The story theme or subject (e.g., 'a Tibetan family crossing the Himalayas', 'Losar celebration in exile', 'a young monk learning thangka painting')"
                        }
                    },
                    "required": ["theme"]
                }
            }
        }
    }
]

# ─── Keyword Search Helper ───────────────────────────────────────────────────────
def keyword_search(kb, query, max_results=3):
    """Search all items in a nested knowledge base dict by keyword intersection."""
    query_words = set(query.lower().split())
    scored = []

    def search_items(items):
        if isinstance(items, list):
            for item in items:
                kws = set(k.lower() for k in item.get('keywords', []))
                score = len(query_words & kws)
                if score > 0:
                    scored.append((score, item))
        elif isinstance(items, dict):
            for v in items.values():
                search_items(v)

    search_items(kb)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]

# ─── Tool Executors ───────────────────────────────────────────────────────────────
def run_cultural_facts(query):
    results = keyword_search(CULTURE_KB, query)
    if not results:
        return f"No specific cultural entry found for '{query}', but Tibet has a rich cultural heritage. Please ask me more specifically about festivals, food, arts, or religion."
    parts = []
    for r in results:
        name = r.get('name', 'Unknown')
        desc = r.get('description', '')
        parts.append(f"**{name}**: {desc}")
    return "\n\n".join(parts)

def run_translate_phrase(phrase):
    results = keyword_search(PHRASES_KB, phrase)
    if not results:
        return f"No exact match found for '{phrase}' in the phrase database. Common Tibetan phrases include: Tashi Delek (hello/blessings), Thuk-je Che (thank you), Om Mani Padme Hum (compassion mantra)."
    parts = []
    for r in results:
        parts.append(
            f"**{r.get('pronunciation', 'N/A')}** ({r.get('wylie', 'N/A')})\n"
            f"Script: {r.get('tibetan_script', '')}\n"
            f"Meaning: {r.get('meaning', '')}\n"
            f"Usage: {r.get('usage', '')}"
        )
    return "\n\n".join(parts)

def run_historical_context(topic):
    results = keyword_search(HISTORY_KB, topic)
    if not results:
        return f"No specific historical entry found for '{topic}'. Key periods in Tibetan history include: the Tibetan Empire (7th–9th century), 1950 Chinese invasion, 1959 uprising and the Dalai Lama's exile, and the Cultural Revolution (1966–76)."
    parts = []
    for r in results:
        period = r.get('period', r.get('year', 'Unknown period'))
        event = r.get('event', 'Historical event')
        desc = r.get('description', '')
        parts.append(f"**{period} — {event}**: {desc}")
    return "\n\n".join(parts)

def run_diaspora_resources(need):
    results = keyword_search(RESOURCES_KB, need)
    if not results:
        return f"No specific resource found for '{need}'. Key Tibetan diaspora resources include: Central Tibetan Administration (tibet.net), Tibet Fund (tibetfund.org), Students for a Free Tibet (studentsforafreetibet.org), and International Campaign for Tibet (savetibet.org)."
    parts = []
    for r in results:
        name = r.get('name', 'Resource')
        rtype = r.get('type', '')
        desc = r.get('description', '')
        contact = r.get('contact', '')
        parts.append(f"**{name}** ({rtype})\n{desc}\n📞 {contact}")
    return "\n\n".join(parts)

def run_tell_story(theme):
    return f"STORY_THEME:{theme}"  # Sentinel — signals LLM to generate narrative in turn 2

# Tool dispatcher
TOOL_DISPATCH = {
    'cultural_facts':    lambda inp: run_cultural_facts(inp.get('query', '')),
    'translate_phrase':  lambda inp: run_translate_phrase(inp.get('phrase', '')),
    'historical_context':lambda inp: run_historical_context(inp.get('topic', '')),
    'diaspora_resources':lambda inp: run_diaspora_resources(inp.get('need', '')),
    'tell_story':        lambda inp: run_tell_story(inp.get('theme', '')),
}

# ─── DynamoDB Helpers ────────────────────────────────────────────────────────────
def load_history(user_id, conversation_id):
    table = dynamodb.Table(HISTORY_TABLE)
    try:
        resp = table.get_item(Key={'PK': f'USER#{user_id}', 'SK': f'CONV#{conversation_id}'})
        return resp.get('Item', {}).get('messages', [])
    except Exception:
        return []

def save_history(user_id, conversation_id, messages):
    table = dynamodb.Table(HISTORY_TABLE)
    try:
        table.put_item(Item={
            'PK': f'USER#{user_id}',
            'SK': f'CONV#{conversation_id}',
            'messages': messages,
            'updated_at': datetime.utcnow().isoformat()
        })
    except Exception as e:
        print(f"[WARN] Failed to save history: {e}")

def write_log(user_id, log_item):
    table = dynamodb.Table(LOGS_TABLE)
    epoch_ms = int(time.time() * 1000)
    uid8 = str(uuid.uuid4())[:8]
    try:
        table.put_item(Item={
            'PK': f'LOG#{user_id}',
            'SK': f'TS#{epoch_ms}#{uid8}',
            **log_item
        })
    except Exception as e:
        print(f"[WARN] Failed to write log: {e}")

# ─── Core Agentic Loop ────────────────────────────────────────────────────────────
def run_agent(user_input, history_messages, user_id, conversation_id):
    """
    Agentic loop using Bedrock Converse API with tool use.
    Turn 1: LLM decides whether to call a tool or respond directly.
    Turn 2 (if tool called): LLM incorporates tool result into final response.
    Returns: (response_text, tool_selected, tool_input, tool_output)
    """
    # Build message list for Converse API
    messages = list(history_messages)  # copy
    messages.append({"role": "user", "content": [{"text": user_input}]})

    tool_selected = None
    tool_input_data = None
    tool_output_data = None

    # ── Turn 1 ──
    response1 = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=messages,
        toolConfig={"tools": TOOLS},
        inferenceConfig={"maxTokens": 1024, "temperature": 0.7}
    )

    stop_reason = response1['stopReason']
    assistant_content = response1['output']['message']['content']

    # Append assistant turn to messages
    messages.append({"role": "assistant", "content": assistant_content})

    if stop_reason == 'tool_use':
        # Find the tool_use block
        tool_use_block = next((b for b in assistant_content if 'toolUse' in b), None)
        if tool_use_block:
            tool_name  = tool_use_block['toolUse']['name']
            tool_input = tool_use_block['toolUse']['input']
            tool_use_id = tool_use_block['toolUse']['toolUseId']

            tool_selected   = tool_name
            tool_input_data = json.dumps(tool_input)

            # Execute the tool
            tool_result = TOOL_DISPATCH.get(tool_name, lambda _: "Tool not found.")(tool_input)
            tool_output_data = tool_result

            # Handle tell_story sentinel
            if isinstance(tool_result, str) and tool_result.startswith("STORY_THEME:"):
                theme = tool_result.replace("STORY_THEME:", "")
                tool_result = f"The user wants a story about: {theme}. Please write a vivid, culturally rich narrative (3-4 paragraphs) that authentically portrays Tibetan life, culture, or history related to this theme."

            # Build tool result message
            tool_result_message = {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": str(tool_result)}]
                        }
                    }
                ]
            }
            messages.append(tool_result_message)

            # ── Turn 2 ── (toolConfig required whenever history contains toolUse/toolResult blocks)
            response2 = bedrock.converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig={"tools": TOOLS},
                inferenceConfig={"maxTokens": 1024, "temperature": 0.7}
            )
            final_text = ""
            for block in response2['output']['message']['content']:
                if 'text' in block:
                    final_text += block['text']

            # Append final assistant response to messages
            messages.append(response2['output']['message'])
        else:
            # No tool_use block found despite tool_use stop reason
            final_text = ""
            for block in assistant_content:
                if 'text' in block:
                    final_text += block['text']
    else:
        # end_turn — LLM responded directly without tool
        final_text = ""
        for block in assistant_content:
            if 'text' in block:
                final_text += block['text']

    # Strip Nova Lite's <thinking>...</thinking> reasoning blocks
    final_text = re.sub(r'<thinking>.*?</thinking>\s*', '', final_text, flags=re.DOTALL).strip()

    return final_text, tool_selected, tool_input_data, tool_output_data, messages

# ─── Lambda Handler ───────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    start_ms = int(time.time() * 1000)

    # CORS preflight
    if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'POST,OPTIONS'
            },
            'body': ''
        }

    try:
        body = json.loads(event.get('body', '{}'))
    except Exception:
        body = {}

    user_input      = body.get('message', '').strip()
    user_id         = body.get('userId', 'anonymous')
    conversation_id = body.get('conversationId', str(uuid.uuid4()))

    if not user_input:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'No message provided'})
        }

    # Load conversation history
    history = load_history(user_id, conversation_id)

    error_str = None
    tool_selected = None
    tool_input_data = None
    tool_output_data = None
    final_response = "I'm sorry, I encountered an error. Please try again."

    try:
        final_response, tool_selected, tool_input_data, tool_output_data, updated_messages = \
            run_agent(user_input, history, user_id, conversation_id)

        # Save updated history (keep last 10 turns to avoid oversized items)
        save_history(user_id, conversation_id, updated_messages[-20:])

    except Exception as e:
        error_str = str(e)
        print(f"[ERROR] Agent loop failed: {e}")

    end_ms    = int(time.time() * 1000)
    latency   = end_ms - start_ms

    # Write observability log
    write_log(user_id, {
        'user_input':       user_input,
        'tool_selected':    tool_selected or 'none',
        'tool_input':       tool_input_data or '',
        'tool_output':      (tool_output_data or '')[:500],  # truncate for DDB
        'final_response':   final_response[:500],
        'latency_ms':       latency,
        'timestamp':        datetime.utcnow().isoformat(),
        'conversation_id':  conversation_id,
        'error':            error_str or ''
    })

    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Origin': '*',
            'Content-Type': 'application/json'
        },
        'body': json.dumps({
            'response':     final_response,
            'tool_used':    tool_selected,
            'latency_ms':   latency,
            'conversationId': conversation_id
        })
    }
