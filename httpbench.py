#!/usr/bin/env python3
"""
HttpBench — Lightweight HTTP benchmarking tool.
Pure Python standard library. Zero external dependencies.

Usage:
    python httpbench.py <url> [options]
    python -m httpbench <url> [options]
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import statistics
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Result:
    """Result of a single HTTP request."""
    status: Optional[int] = None
    latency_ms: float = 0.0
    error: Optional[str] = None
    bytes_received: int = 0
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class HttpBench:
    """HTTP benchmark engine — thread-pool based, keep-alive aware."""

    def __init__(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        concurrency: int = 1,
        timeout: float = 30.0,
        keep_alive: bool = True,
    ):
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.body = body
        self.concurrency = max(1, concurrency)
        self.timeout = timeout
        self.keep_alive = keep_alive

        parsed = urllib.parse.urlparse(url)
        self.scheme = parsed.scheme.lower()
        if self.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported scheme '{self.scheme}'. Use http or https.")
        self.host = parsed.hostname or ""
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.path = parsed.path or "/"
        if parsed.query:
            self.path += "?" + parsed.query

        self.results: List[Result] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._completed = 0
        self._actual_duration = 0.0

    # -- low-level request -------------------------------------------------

    def _send(self, conn: http.client.HTTPConnection) -> Result:
        t0 = time.perf_counter()
        result = Result(timestamp=time.time())
        try:
            conn.request(self.method, self.path, body=self.body, headers=self.headers)
            resp = conn.getresponse()
            data = resp.read()
            result.status = resp.status
            result.bytes_received = len(data)
            result.latency_ms = (time.perf_counter() - t0) * 1000
        except socket.timeout:
            result.error = "timeout"
            result.latency_ms = (time.perf_counter() - t0) * 1000
        except OSError as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.latency_ms = (time.perf_counter() - t0) * 1000
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.latency_ms = (time.perf_counter() - t0) * 1000
        return result

    def _conn_cls(self):
        return (
            http.client.HTTPSConnection
            if self.scheme == "https"
            else http.client.HTTPConnection
        )

    def _new_conn(self):
        return self._conn_cls()(self.host, self.port, timeout=self.timeout)

    # -- workers -----------------------------------------------------------

    def _worker_count(self, target: int):
        """Send exactly *target* requests."""
        Conn = self._conn_cls()
        conn = None
        if self.keep_alive:
            try:
                conn = Conn(self.host, self.port, timeout=self.timeout)
            except Exception:
                conn = None

        try:
            for _ in range(target):
                if self._stop.is_set():
                    break
                if conn is None:
                    try:
                        conn = Conn(self.host, self.port, timeout=self.timeout)
                    except Exception as exc:
                        r = Result(error=f"connect:{type(exc).__name__}")
                        with self._lock:
                            self.results.append(r)
                            self._completed += 1
                        continue

                r = self._send(conn)
                if r.error and self.keep_alive:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None

                with self._lock:
                    self.results.append(r)
                    self._completed += 1
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _worker_time(self):
        """Send requests until stopped."""
        Conn = self._conn_cls()
        conn = None
        if self.keep_alive:
            try:
                conn = Conn(self.host, self.port, timeout=self.timeout)
            except Exception:
                conn = None

        try:
            while not self._stop.is_set():
                if conn is None:
                    try:
                        conn = Conn(self.host, self.port, timeout=self.timeout)
                    except Exception as exc:
                        r = Result(error=f"connect:{type(exc).__name__}")
                        with self._lock:
                            self.results.append(r)
                            self._completed += 1
                        time.sleep(0.01)
                        continue

                r = self._send(conn)
                if r.error and self.keep_alive:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None

                with self._lock:
                    self.results.append(r)
                    self._completed += 1
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # -- public runners ----------------------------------------------------

    def run_count(self, total: int, quiet: bool = False) -> List[Result]:
        self.results.clear()
        self._completed = 0
        self._stop.clear()

        base = total // self.concurrency
        extra = total % self.concurrency

        threads = []
        for i in range(self.concurrency):
            n = base + (1 if i < extra else 0)
            t = threading.Thread(target=self._worker_count, args=(n,))
            threads.append(t)
            t.start()

        t0 = time.time()
        if not quiet:
            self._show_progress_count(total)
        for t in threads:
            t.join()
        self._actual_duration = time.time() - t0
        return self.results

    def run_duration(self, seconds: float, quiet: bool = False) -> List[Result]:
        self.results.clear()
        self._completed = 0
        self._stop.clear()

        threads = []
        for _ in range(self.concurrency):
            t = threading.Thread(target=self._worker_time)
            threads.append(t)
            t.start()

        t0 = time.time()
        if not quiet:
            self._show_progress_time(seconds)
        time.sleep(seconds)
        self._stop.set()
        for t in threads:
            t.join()
        self._actual_duration = time.time() - t0
        return self.results

    # -- progress ----------------------------------------------------------

    def _show_progress_count(self, total: int):
        while self._completed < total:
            done = self._completed
            pct = done * 100 // total if total else 0
            bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
            sys.stdout.write(f"\r  [{bar}] {done}/{total} ({pct}%)")
            sys.stdout.flush()
            time.sleep(0.05)
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()

    def _show_progress_time(self, seconds: float):
        t0 = time.time()
        while time.time() - t0 < seconds and not self._stop.is_set():
            elapsed = time.time() - t0
            pct = int(elapsed * 100 / seconds) if seconds else 0
            bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
            done = self._completed
            sys.stdout.write(f"\r  [{bar}] {done} req  {elapsed:.1f}s/{seconds:.0f}s")
            sys.stdout.flush()
            time.sleep(0.05)
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()

    # -- statistics --------------------------------------------------------

    def compute_stats(self) -> Dict:
        if not self.results:
            return {}

        ok = [r for r in self.results if r.error is None]
        failed = [r for r in self.results if r.error is not None]
        latencies = [r.latency_ms for r in ok]

        statuses: Dict[int, int] = {}
        errors: Dict[str, int] = {}
        for r in self.results:
            if r.status:
                statuses[r.status] = statuses.get(r.status, 0) + 1
            if r.error:
                errors[r.error] = errors.get(r.error, 0) + 1

        total = len(self.results)
        success = len(ok)

        if not latencies:
            return {
                "total": total,
                "success": 0,
                "failed": total,
                "error_breakdown": errors,
                "status_codes": statuses,
                "rps": 0.0,
                "total_mb": 0.0,
                "duration_sec": round(self._actual_duration, 3),
            }

        latencies.sort()
        n = len(latencies)

        def pct(p: float) -> float:
            idx = int(n * p / 100.0)
            return latencies[max(0, min(idx, n - 1))]

        duration = self._actual_duration if self._actual_duration > 0 else 0.001
        total_bytes = sum(r.bytes_received for r in ok)

        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "error_breakdown": errors,
            "status_codes": statuses,
            "rps": round(success / duration, 2),
            "total_mb": round(total_bytes / (1024 * 1024), 3),
            "duration_sec": round(duration, 3),
            "latency_min_ms": round(latencies[0], 2),
            "latency_max_ms": round(latencies[-1], 2),
            "latency_mean_ms": round(statistics.mean(latencies), 2),
            "latency_median_ms": round(statistics.median(latencies), 2),
            "latency_std_ms": round(statistics.stdev(latencies) if n > 1 else 0.0, 2),
            "latency_p50_ms": round(pct(50), 2),
            "latency_p75_ms": round(pct(75), 2),
            "latency_p90_ms": round(pct(90), 2),
            "latency_p95_ms": round(pct(95), 2),
            "latency_p99_ms": round(pct(99), 2),
            "latency_p999_ms": round(pct(99.9), 2),
        }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _bar_ascii(percent: float, width: int = 30) -> str:
    filled = int(width * percent / 100.0)
    return "█" * filled + "░" * (width - filled)


def _histogram(latencies: List[float], bins: int = 8) -> List[Tuple[float, float, int, float]]:
    if not latencies:
        return []
    lo, hi = min(latencies), max(latencies)
    if lo == hi:
        return [(lo, hi, len(latencies), 100.0)]
    size = (hi - lo) / bins
    counts = [0] * bins
    for v in latencies:
        idx = min(int((v - lo) / size), bins - 1)
        counts[idx] += 1
    total = len(latencies)
    return [
        (lo + i * size, lo + (i + 1) * size, c, c * 100.0 / total)
        for i, c in enumerate(counts)
    ]


def print_terminal(bench: HttpBench, stats: Dict):
    print()
    print(f"  URL:       {bench.url}")
    print(f"  Method:    {bench.method}")
    print(f"  Duration:  {stats.get('duration_sec', 0):.3f}s")
    print(f"  Requests:  {stats['total']} total  |  {stats['success']} success  |  {stats['failed']} failed")
    print(f"  RPS:       {stats['rps']}")
    print(f"  Data:      {stats['total_mb']} MB received")
    print()

    # Latency table
    print("  Latency Distribution")
    print("  " + "─" * 44)
    rows = [
        ("Min",    stats["latency_min_ms"]),
        ("Mean",   stats["latency_mean_ms"]),
        ("Median", stats["latency_median_ms"]),
        ("StdDev", stats["latency_std_ms"]),
        ("Max",    stats["latency_max_ms"]),
    ]
    for label, val in rows:
        print(f"    {label:8} {val:>10.2f} ms")
    print("  " + "─" * 44)
    rows = [
        ("P50",  stats["latency_p50_ms"]),
        ("P75",  stats["latency_p75_ms"]),
        ("P90",  stats["latency_p90_ms"]),
        ("P95",  stats["latency_p95_ms"]),
        ("P99",  stats["latency_p99_ms"]),
        ("P99.9", stats["latency_p999_ms"]),
    ]
    for label, val in rows:
        print(f"    {label:8} {val:>10.2f} ms")
    print()

    # ASCII histogram
    ok = [r for r in bench.results if r.error is None]
    latencies = [r.latency_ms for r in ok]
    if latencies:
        hist = _histogram(latencies, bins=8)
        max_count = max(h[2] for h in hist) if hist else 1
        print("  Latency Histogram")
        print("  " + "─" * 44)
        for lo, hi, count, _ in hist:
            pct = count * 100.0 / max_count if max_count else 0
            bar = _bar_ascii(pct, width=20)
            print(f"    {lo:>8.1f}-{hi:>8.1f} ms  {bar}  {count}")
        print()

    # Status codes
    if stats.get("status_codes"):
        print("  Status Codes")
        print("  " + "─" * 44)
        for code, count in sorted(stats["status_codes"].items()):
            print(f"    HTTP {code}: {count}")
        print()

    # Errors
    if stats.get("error_breakdown"):
        print("  Errors")
        print("  " + "─" * 44)
        for err, count in sorted(stats["error_breakdown"].items(), key=lambda x: -x[1]):
            print(f"    {err}: {count}")
        print()


def generate_html(stats: Dict, url: str, method: str) -> str:
    """Self-contained dark-themed HTML report."""

    def rows() -> str:
        lines = []
        for label, key in [
            ("Min", "latency_min_ms"),
            ("Mean", "latency_mean_ms"),
            ("Median", "latency_median_ms"),
            ("StdDev", "latency_std_ms"),
            ("Max", "latency_max_ms"),
            ("P50", "latency_p50_ms"),
            ("P75", "latency_p75_ms"),
            ("P90", "latency_p90_ms"),
            ("P95", "latency_p95_ms"),
            ("P99", "latency_p99_ms"),
            ("P99.9", "latency_p999_ms"),
        ]:
            lines.append(f"<tr><td>{label}</td><td>{stats.get(key, 0):.2f} ms</td></tr>")
        return "\n".join(lines)

    def status_cards() -> str:
        items = stats.get("status_codes", {})
        if not items:
            return '<div class="card" style="text-align:center;color:#94a3b8;">No data</div>'
        out = []
        for code, count in sorted(items.items()):
            color = "#4ade80" if 200 <= code < 300 else "#fbbf24" if 300 <= code < 400 else "#f87171"
            out.append(
                f'<div class="card" style="text-align:center;">'
                f'<div style="font-size:1.4rem;font-weight:700;color:{color};">{code}</div>'
                f'<div style="font-size:0.8rem;color:#94a3b8;margin-top:0.3rem;">{count} requests</div>'
                f'</div>'
            )
        return "\n".join(out)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HttpBench Report</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
.container{{max-width:980px;margin:0 auto}}
h1{{font-size:1.8rem;margin-bottom:.3rem;color:#fff}}
.subtitle{{color:#94a3b8;margin-bottom:2rem;font-size:.95rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:2rem}}
.card{{background:#1e293b;border-radius:12px;padding:1.2rem}}
.card-label{{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4rem}}
.card-value{{font-size:1.5rem;font-weight:700;color:#fff}}
.ok{{color:#4ade80}} .warn{{color:#fbbf24}} .err{{color:#f87171}}
table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden;margin-bottom:2rem}}
th,td{{padding:.8rem 1rem;text-align:left}}
th{{background:#334155;font-weight:600;font-size:.82rem;text-transform:uppercase;letter-spacing:.05em;color:#cbd5e1}}
tr:nth-child(even){{background:#253249}}
td{{font-size:.95rem}}
.footer{{text-align:center;color:#64748b;font-size:.8rem;margin-top:2rem}}
</style>
</head>
<body>
<div class="container">
<h1>HttpBench Report</h1>
<div class="subtitle">{method} {url}</div>

<div class="grid">
<div class="card"><div class="card-label">Total</div><div class="card-value">{stats['total']}</div></div>
<div class="card"><div class="card-label">Success</div><div class="card-value ok">{stats['success']}</div></div>
<div class="card"><div class="card-label">Failed</div><div class="card-value {'err' if stats['failed']>0 else 'ok'}">{stats['failed']}</div></div>
<div class="card"><div class="card-label">RPS</div><div class="card-value">{stats['rps']}</div></div>
<div class="card"><div class="card-label">Duration</div><div class="card-value">{stats.get('duration_sec',0):.3f}s</div></div>
<div class="card"><div class="card-label">Data</div><div class="card-value">{stats['total_mb']} MB</div></div>
</div>

<h2 style="margin-bottom:1rem;font-size:1.2rem;">Latency Distribution</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{rows()}
</table>

<h2 style="margin-bottom:1rem;font-size:1.2rem;">Status Codes</h2>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(110px,1fr));">
{status_cards()}
</div>

<div class="footer">Generated by HttpBench v{__version__}</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_headers(raw: List[str]) -> Dict[str, str]:
    headers = {}
    for h in raw:
        if ":" not in h:
            continue
        k, v = h.split(":", 1)
        headers[k.strip()] = v.strip()
    return headers


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="httpbench",
        description="Lightweight HTTP benchmarking tool. Pure Python, zero dependencies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://example.com
  %(prog)s https://api.example.com/data -n 1000 -c 50
  %(prog)s https://api.example.com -d 30 -c 10
  %(prog)s https://api.example.com -X POST -H "Authorization: Bearer xxx" --data '{{"key":"val"}}'
  %(prog)s https://example.com -n 500 -o json
  %(prog)s https://example.com -n 1000 --report report.html
        """.strip(),
    )
    parser.add_argument("url", help="Target URL to benchmark")
    parser.add_argument(
        "-n", "--requests", type=int, default=100, help="Total number of requests (default: 100)"
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=1, help="Concurrent connections (default: 1)"
    )
    parser.add_argument(
        "-d", "--duration", type=float, help="Duration in seconds (overrides -n)"
    )
    parser.add_argument(
        "-X", "--method", default="GET", help="HTTP method (default: GET)"
    )
    parser.add_argument(
        "-H", "--header", action="append", default=[], help="Add header (repeatable)"
    )
    parser.add_argument("--data", help="Request body as string")
    parser.add_argument("--data-file", help="Read request body from file")
    parser.add_argument(
        "-t", "--timeout", type=float, default=30.0, help="Request timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--no-keepalive", action="store_true", help="Disable HTTP keep-alive"
    )
    parser.add_argument(
        "-o", "--output", choices=["terminal", "json", "html"], default="terminal",
        help="Output format (default: terminal)"
    )
    parser.add_argument(
        "--report", metavar="FILE", help="Write HTML report to file"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress bar"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args(argv)

    # Body
    body: Optional[bytes] = None
    if args.data_file:
        with open(args.data_file, "rb") as f:
            body = f.read()
    elif args.data:
        body = args.data.encode("utf-8")

    headers = parse_headers(args.header)
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    # Run
    bench = HttpBench(
        url=args.url,
        method=args.method,
        headers=headers,
        body=body,
        concurrency=args.concurrency,
        timeout=args.timeout,
        keep_alive=not args.no_keepalive,
    )

    print(f"Benchmarking {args.url} ...")
    print(f"  {args.concurrency} concurrent connection(s)")
    if args.duration:
        print(f"  Duration: {args.duration}s")
        bench.run_duration(args.duration, quiet=args.quiet)
    else:
        print(f"  Requests: {args.requests}")
        bench.run_count(args.requests, quiet=args.quiet)

    stats = bench.compute_stats()

    # Output
    if args.output == "json":
        print(json.dumps(stats, indent=2))
    elif args.output == "html":
        print(generate_html(stats, args.url, args.method))
    else:
        print_terminal(bench, stats)

    if args.report:
        html = generate_html(stats, args.url, args.method)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Report saved: {args.report}")

    return 0 if stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
