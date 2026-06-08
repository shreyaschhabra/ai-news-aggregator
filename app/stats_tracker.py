"""
StatsTracker — pipeline run metrics collector.

Tracks 4 metrics across a full pipeline run:
  1. Token Compression Ratio       (docling HTML → Markdown)
  2. API Call Reduction             (batch curation vs N individual calls)
  3. Schema Validation Success Rate (Pydantic v2 model_validate_json)
  4. API Throughput                 (actual RPM vs 15 RPM free-tier limit)

Usage (singleton — import and use directly):
    from app.stats_tracker import tracker
    tracker.record_api_call()
    tracker.record_validation_success()
    tracker.print_summary()

Call tracker.reset() at the start of run_daily_pipeline() to ensure
metrics are isolated to a single run when main.py is imported as a module.
"""

import time


class StatsTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._start_time: float = time.time()
        self._compression_samples: list[tuple[int, int]] = []  # (raw_html_len, markdown_len)
        self._articles_evaluated: int = 0
        self._validation_successes: int = 0
        self._validation_failures: int = 0
        self._api_calls: int = 0

    # ------------------------------------------------------------------ #
    # Recording methods — call these from pipeline / agent code            #
    # ------------------------------------------------------------------ #

    def record_compression(self, raw_html_len: int, markdown_len: int) -> None:
        """Record one HTML → Markdown conversion for Metric 1."""
        if raw_html_len > 0 and markdown_len > 0:
            self._compression_samples.append((raw_html_len, markdown_len))

    def record_articles_evaluated(self, n: int) -> None:
        """Record total digests sent to CuratorAgent for Metric 2."""
        self._articles_evaluated = n

    def record_validation_success(self) -> None:
        """Call after each successful model_validate_json() for Metric 3."""
        self._validation_successes += 1

    def record_validation_failure(self) -> None:
        """Call inside except ValidationError blocks for Metric 3."""
        self._validation_failures += 1

    def record_api_call(self) -> None:
        """Call once per Gemini API request, before time.sleep(), for Metric 4."""
        self._api_calls += 1

    # ------------------------------------------------------------------ #
    # Computed properties                                                  #
    # ------------------------------------------------------------------ #

    @property
    def avg_compression_pct(self) -> float:
        if not self._compression_samples:
            return 0.0
        return sum(
            (raw - md) / raw * 100
            for raw, md in self._compression_samples
        ) / len(self._compression_samples)

    @property
    def batch_reduction_pct(self) -> float:
        n = self._articles_evaluated
        return ((n - 1) / n * 100) if n > 1 else 0.0

    @property
    def validation_success_rate(self) -> float:
        total = self._validation_successes + self._validation_failures
        return (self._validation_successes / total * 100) if total > 0 else 0.0

    @property
    def actual_rpm(self) -> float:
        elapsed_min = (time.time() - self._start_time) / 60
        return (self._api_calls / elapsed_min) if elapsed_min > 0 else 0.0

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self._start_time

    # ------------------------------------------------------------------ #
    # Terminal output                                                      #
    # ------------------------------------------------------------------ #

    def print_summary(self) -> None:
        n = self._articles_evaluated
        total_val = self._validation_successes + self._validation_failures
        w = 64
        sep = "=" * w
        div = "-" * w

        def row(label: str, value: str) -> str:
            return f"  {label:<42}{value:>20}"

        print(f"\n{sep}")
        print(f"  Pipeline Run Metrics")
        print(sep)

        # Metric 1
        print(row("Token Compression Ratio (avg)", f"{self.avg_compression_pct:.1f}%"))
        print(row("  articles converted", str(len(self._compression_samples))))
        print(row("  formula", "(HTML_len - MD_len) / HTML_len"))
        print(div)

        # Metric 2
        hypothetical = str(n) if n > 0 else "N/A"
        print(row("API Call Reduction via Batch Curation", f"{self.batch_reduction_pct:.1f}%"))
        print(row("  calls made vs hypothetical", f"1  vs  {hypothetical}"))
        print(row("  formula", f"(N-1)/N  where N={n}"))
        print(div)

        # Metric 3
        print(row("Schema Validation Success Rate", f"{self.validation_success_rate:.1f}%"))
        print(row("  passed / total", f"{self._validation_successes} / {total_val}"))
        print(row("  agents tracked", "DigestAgent, CuratorAgent, EmailAgent"))
        print(div)

        # Metric 4
        print(row("Actual API Throughput", f"{self.actual_rpm:.2f} RPM"))
        print(row("  total Gemini API calls", str(self._api_calls)))
        print(row("  pipeline duration", f"{self.elapsed_seconds:.1f}s"))
        print(row("  free-tier limit", "15.00 RPM"))
        print(row("  headroom", f"{15.0 - self.actual_rpm:.2f} RPM"))
        print(f"{sep}\n")


# Module-level singleton — import `tracker` directly everywhere
tracker = StatsTracker()
