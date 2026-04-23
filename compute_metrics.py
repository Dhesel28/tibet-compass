#!/usr/bin/env python3
"""
Tibet Compass — Metrics Computer
DS5730 Final Project | Dhesel Khando

Scans TibetCompassLogs DynamoDB table and computes:
  - Tool distribution (count + % per tool)
  - Latency P50 and P95 (ms)
  - Error rate
  - Total request count

Usage:
  python3 compute_metrics.py
  python3 compute_metrics.py --table TibetCompassLogs --region us-east-1
  python3 compute_metrics.py --chart  (requires matplotlib)
"""

import argparse
import json
import statistics
import boto3
from collections import Counter
from datetime import datetime


def scan_logs(table_name: str, region: str) -> list[dict]:
    """Full scan of the logs DynamoDB table."""
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    items = []
    last_key = None

    while True:
        kwargs = {}
        if last_key:
            kwargs['ExclusiveStartKey'] = last_key
        resp = table.scan(**kwargs)
        items.extend(resp.get('Items', []))
        last_key = resp.get('LastEvaluatedKey')
        if not last_key:
            break

    return items


def compute_metrics(items: list[dict]) -> dict:
    """Compute all metrics from raw log items."""
    total = len(items)
    if total == 0:
        return {"total_requests": 0, "error": "No log entries found"}

    tools      = [item.get('tool_selected', 'none') for item in items]
    latencies  = [int(item['latency_ms']) for item in items if item.get('latency_ms')]
    errors     = [item for item in items if item.get('error', '')]

    # Tool distribution
    tool_counts = Counter(tools)
    tool_dist = {
        tool: {"count": count, "pct": round(count / total * 100, 1)}
        for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1])
    }

    # Latency stats
    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    p50 = latencies_sorted[n // 2] if n > 0 else None
    p95 = latencies_sorted[int(n * 0.95)] if n > 0 else None
    mean_lat = round(statistics.mean(latencies), 1) if latencies else None

    return {
        "computed_at":       datetime.utcnow().isoformat(),
        "total_requests":    total,
        "error_count":       len(errors),
        "error_rate_pct":    round(len(errors) / total * 100, 1),
        "latency": {
            "p50_ms":  p50,
            "p95_ms":  p95,
            "mean_ms": mean_lat,
            "min_ms":  latencies_sorted[0] if latencies else None,
            "max_ms":  latencies_sorted[-1] if latencies else None,
            "samples": n,
        },
        "tool_distribution": tool_dist,
    }


def print_metrics(m: dict) -> None:
    """Pretty-print metrics to terminal."""
    print(f"\n{'='*58}")
    print(f"  TIBET COMPASS — METRICS REPORT")
    print(f"  Computed: {m.get('computed_at','')[:19]}")
    print(f"{'='*58}")

    print(f"\n  REQUESTS")
    print(f"    Total:      {m.get('total_requests', 0):,}")
    print(f"    Errors:     {m.get('error_count', 0)} ({m.get('error_rate_pct', 0)}%)")

    lat = m.get('latency', {})
    print(f"\n  LATENCY")
    print(f"    P50:        {lat.get('p50_ms','N/A')} ms")
    print(f"    P95:        {lat.get('p95_ms','N/A')} ms")
    print(f"    Mean:       {lat.get('mean_ms','N/A')} ms")
    print(f"    Min/Max:    {lat.get('min_ms','N/A')} / {lat.get('max_ms','N/A')} ms")
    print(f"    Samples:    {lat.get('samples', 0)}")

    tool_dist = m.get('tool_distribution', {})
    if tool_dist:
        print(f"\n  TOOL DISTRIBUTION")
        for tool, stats in tool_dist.items():
            bar = '█' * int(stats['pct'] / 2)
            print(f"    {tool:22s} {stats['count']:4d}  {stats['pct']:5.1f}%  {bar}")
    print(f"\n{'='*58}\n")


def plot_chart(m: dict) -> None:
    """Optional: plot tool distribution bar chart."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("[!] matplotlib not installed — skipping chart. Run: pip install matplotlib")
        return

    tool_dist = m.get('tool_distribution', {})
    if not tool_dist:
        return

    labels = list(tool_dist.keys())
    counts = [tool_dist[t]['count'] for t in labels]
    colors = ['#e65100','#2e7d32','#1565c0','#7b1fa2','#f57f17','#616161'][:len(labels)]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.barh(labels, counts, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xlabel('Request Count', fontsize=11)
    ax.set_title('Tibet Compass — Tool Distribution', fontsize=13, fontweight='bold', color='#8B0000')
    ax.bar_label(bars, padding=4, fontsize=10)
    ax.set_xlim(0, max(counts) * 1.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()

    fname = 'tool_distribution.png'
    plt.savefig(fname, dpi=150)
    print(f"[✓] Chart saved: {fname}")
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="Tibet Compass — DynamoDB Metrics")
    parser.add_argument("--table",   default="TibetCompassLogs",  help="DynamoDB logs table name")
    parser.add_argument("--region",  default="us-east-1",         help="AWS region")
    parser.add_argument("--output",  default=None,                 help="Save metrics to JSON file")
    parser.add_argument("--chart",   action="store_true",          help="Generate matplotlib bar chart")
    args = parser.parse_args()

    print(f"\n[→] Scanning DynamoDB table: {args.table} ({args.region})...")
    try:
        items = scan_logs(args.table, args.region)
    except Exception as e:
        print(f"[✗] Failed to scan DynamoDB: {e}")
        print("    Make sure AWS credentials are configured and the table exists.")
        return

    print(f"[✓] Retrieved {len(items)} log entries")

    metrics = compute_metrics(items)
    print_metrics(metrics)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(metrics, f, indent=2)
        print(f"[✓] Metrics saved to: {args.output}")

    if args.chart:
        plot_chart(metrics)


if __name__ == "__main__":
    main()

# -------------------------------------------------------------------------------
# This code was developed with assistance from Claude (Anthropic AI).
# Claude was used to help with code structure, refactoring, and debugging.
# Final implementation, testing, and validation were done by the author.
# -------------------------------------------------------------------------------
