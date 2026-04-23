#!/usr/bin/env python3
"""
Tibet Compass — 20-Query Evaluation Runner
DS5730 Final Project | Dhesel Khando

Sends 20 test queries (4 per domain), records:
  - tool_selected (actual)
  - expected_tool
  - latency_ms
  - response (for manual quality scoring)

Usage:
  python3 evaluate.py --api-url https://YOUR_API.execute-api.us-east-1.amazonaws.com/prod/ask
  python3 evaluate.py --api-url https://... --output results.json

After running, manually score each response 1-5 for:
  - relevance: Does it answer the question?
  - cultural_accuracy: Is the cultural/historical content correct?
  - quality: Overall response quality
"""

import argparse
import json
import time
import uuid
import requests
from datetime import datetime

# ── 20 Evaluation Queries (4 per domain) ──────────────────────────────────────
EVAL_QUERIES = [
    # ── Culture (4) ──
    {"id": 1,  "domain": "culture",    "expected_tool": "cultural_facts",    "query": "Tell me about the Losar festival in Tibet"},
    {"id": 2,  "domain": "culture",    "expected_tool": "cultural_facts",    "query": "What is tsampa and why is it important to Tibetan culture?"},
    {"id": 3,  "domain": "culture",    "expected_tool": "cultural_facts",    "query": "Describe the art of thangka painting"},
    {"id": 4,  "domain": "culture",    "expected_tool": "cultural_facts",    "query": "What is Tibetan butter tea and how is it made?"},

    # ── Translation (4) ──
    {"id": 5,  "domain": "translation","expected_tool": "translate_phrase",  "query": "How do you say hello in Tibetan?"},
    {"id": 6,  "domain": "translation","expected_tool": "translate_phrase",  "query": "What does Om Mani Padme Hum mean?"},
    {"id": 7,  "domain": "translation","expected_tool": "translate_phrase",  "query": "How do you say thank you in Tibetan?"},
    {"id": 8,  "domain": "translation","expected_tool": "translate_phrase",  "query": "Teach me the Tashi Delek greeting and when to use it"},

    # ── History (4) ──
    {"id": 9,  "domain": "history",    "expected_tool": "historical_context","query": "What happened in Tibet in 1959?"},
    {"id": 10, "domain": "history",    "expected_tool": "historical_context","query": "Who was King Songtsen Gampo and what did he accomplish?"},
    {"id": 11, "domain": "history",    "expected_tool": "historical_context","query": "What was the impact of China's Cultural Revolution on Tibetan monasteries?"},
    {"id": 12, "domain": "history",    "expected_tool": "historical_context","query": "When did the Dalai Lama receive the Nobel Peace Prize and why?"},

    # ── Resources (4) ──
    {"id": 13, "domain": "resources",  "expected_tool": "diaspora_resources","query": "What scholarships are available for Tibetan students?"},
    {"id": 14, "domain": "resources",  "expected_tool": "diaspora_resources","query": "Where can Tibetan refugees find mental health support?"},
    {"id": 15, "domain": "resources",  "expected_tool": "diaspora_resources","query": "What organizations advocate for Tibetan human rights?"},
    {"id": 16, "domain": "resources",  "expected_tool": "diaspora_resources","query": "Tell me about Tibetan community organizations in the United States"},

    # ── Story (4) ──
    {"id": 17, "domain": "story",      "expected_tool": "tell_story",        "query": "Tell me a story about a Tibetan family celebrating Losar in exile"},
    {"id": 18, "domain": "story",      "expected_tool": "tell_story",        "query": "Tell a tale about a young monk learning thangka painting in Dharamsala"},
    {"id": 19, "domain": "story",      "expected_tool": "tell_story",        "query": "Narrate the journey of a Tibetan family crossing the Himalayas to freedom"},
    {"id": 20, "domain": "story",      "expected_tool": "tell_story",        "query": "Tell me a story about preserving Tibetan culture in the diaspora"},
]


def run_query(api_url: str, query: str, user_id: str, delay: float = 1.0) -> dict:
    """Send a single query to the Tibet Compass API."""
    try:
        resp = requests.post(
            api_url,
            json={"message": query, "userId": user_id},
            timeout=90
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "tool_selected": data.get("tool_used"),
            "latency_ms": data.get("latency_ms"),
            "response": data.get("response", "")[:500],  # truncate for display
            "conversation_id": data.get("conversationId")
        }
    except requests.Timeout:
        return {"success": False, "error": "Timeout (>90s)", "tool_selected": None, "latency_ms": None, "response": ""}
    except Exception as e:
        return {"success": False, "error": str(e), "tool_selected": None, "latency_ms": None, "response": ""}
    finally:
        time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description="Tibet Compass — 20-Query Evaluation")
    parser.add_argument("--api-url", required=True, help="API Gateway endpoint URL (POST /ask)")
    parser.add_argument("--output",  default="eval_results.json", help="Output JSON file")
    parser.add_argument("--delay",   type=float, default=1.5, help="Delay between queries (seconds)")
    args = parser.parse_args()

    user_id = f"eval_{str(uuid.uuid4())[:8]}"
    results = []
    correct_routing = 0
    latencies = []

    print(f"\n{'='*60}")
    print(f"  Tibet Compass — Evaluation Run")
    print(f"  API: {args.api_url}")
    print(f"  Queries: {len(EVAL_QUERIES)} | User ID: {user_id}")
    print(f"{'='*60}\n")

    for q in EVAL_QUERIES:
        print(f"[{q['id']:02d}/20] [{q['domain'].upper():10s}] {q['query'][:55]}...")
        result = run_query(args.api_url, q['query'], user_id, delay=args.delay)

        routed_correctly = (result.get("tool_selected") == q["expected_tool"])
        if routed_correctly:
            correct_routing += 1
            routing_symbol = "✓"
        else:
            routing_symbol = "✗"

        if result.get("latency_ms"):
            latencies.append(result["latency_ms"])

        status = "OK" if result["success"] else f"ERROR: {result.get('error','?')}"
        lat_str = str(result.get('latency_ms') or '?')
        tool_str = str(result.get('tool_selected') or 'none')
        print(f"         Tool: {tool_str:20s} | Expected: {q['expected_tool']:20s} | {routing_symbol} | {lat_str}ms | {status}")

        record = {
            "id":              q["id"],
            "domain":          q["domain"],
            "query":           q["query"],
            "expected_tool":   q["expected_tool"],
            "actual_tool":     result.get("tool_selected"),
            "routed_correctly":routed_correctly,
            "latency_ms":      result.get("latency_ms"),
            "response":        result.get("response", ""),
            "success":         result["success"],
            "error":           result.get("error", ""),
            # Manual scoring fields (fill in after reviewing responses)
            "relevance":       None,   # 1-5
            "cultural_accuracy": None, # 1-5
            "quality":         None,   # 1-5
        }
        results.append(record)

    # ── Summary ────────────────────────────────────────────────────────────────
    routing_accuracy = correct_routing / len(EVAL_QUERIES) * 100
    p50 = sorted(latencies)[len(latencies)//2] if latencies else None
    p95_idx = int(len(latencies) * 0.95)
    p95 = sorted(latencies)[p95_idx] if latencies else None

    print(f"\n{'='*60}")
    print(f"  EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Routing Accuracy:  {correct_routing}/{len(EVAL_QUERIES)} ({routing_accuracy:.1f}%)")
    print(f"  Target:            18/20 (90%)")
    print(f"  Latency P50:       {p50}ms")
    print(f"  Latency P95:       {p95}ms")
    print(f"  Successful calls:  {sum(1 for r in results if r['success'])}/{len(results)}")
    print(f"\n  NOTE: Manually score each response 1-5 for:")
    print(f"    relevance, cultural_accuracy, quality")
    print(f"    Target: avg quality >= 3.5")
    print(f"{'='*60}\n")

    # ── Write results ──────────────────────────────────────────────────────────
    output = {
        "run_timestamp":      datetime.utcnow().isoformat(),
        "api_url":            args.api_url,
        "user_id":            user_id,
        "total_queries":      len(EVAL_QUERIES),
        "routing_correct":    correct_routing,
        "routing_accuracy_pct": routing_accuracy,
        "latency_p50_ms":     p50,
        "latency_p95_ms":     p95,
        "results":            results
    }
    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to: {args.output}")
    print("Open the file and fill in relevance/cultural_accuracy/quality scores (1-5) for each entry.\n")


if __name__ == "__main__":
    main()
