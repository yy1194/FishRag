from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Sample:
    ok: bool
    status_code: int
    duration_ms: float


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a lightweight HTTP smoke load test.")
    parser.add_argument("--url", default="http://localhost:8000/api/v1/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    total_requests = max(1, args.requests)
    concurrency = max(1, args.concurrency)
    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(_request_once, args.url, args.timeout) for _ in range(total_requests)
        ]
        samples = [future.result() for future in as_completed(futures)]
    elapsed_seconds = time.perf_counter() - started_at

    ok_samples = [sample for sample in samples if sample.ok]
    durations = [sample.duration_ms for sample in samples]
    status_counts: dict[int, int] = {}
    for sample in samples:
        status_counts[sample.status_code] = status_counts.get(sample.status_code, 0) + 1

    print(f"url={args.url}")
    print(f"requests={len(samples)} concurrency={concurrency}")
    print(f"success={len(ok_samples)} errors={len(samples) - len(ok_samples)}")
    print(f"rps={len(samples) / elapsed_seconds:.2f}")
    print(f"status_counts={status_counts}")
    print(f"latency_avg_ms={statistics.fmean(durations):.2f}")
    print(f"latency_p95_ms={_percentile(durations, 95):.2f}")
    print(f"latency_max_ms={max(durations):.2f}")


def _request_once(url: str, timeout: float) -> Sample:
    started_at = time.perf_counter()
    try:
        request = Request(url, headers={"User-Agent": "fishrag-perf-smoke"})
        with urlopen(request, timeout=timeout) as response:
            response.read()
            status_code = response.status
    except HTTPError as exc:
        status_code = exc.code
    except URLError:
        status_code = 0
    duration_ms = (time.perf_counter() - started_at) * 1000
    return Sample(ok=200 <= status_code < 400, status_code=status_code, duration_ms=duration_ms)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile / 100)
    return ordered[index]


if __name__ == "__main__":
    main()
