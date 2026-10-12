from treasurypilot_worker.agent import (
    AiConfig,
    InMemoryBudgetLedger,
    Usage,
    cost_usd_micros,
)


def test_cost_is_integer_micros_rounded_up(repo_config: AiConfig) -> None:
    sonnet = repo_config.prices["claude-sonnet-5-5"]

    # 1,000 in * 2 USD/MTok + 500 out * 10 USD/MTok = 0.002 + 0.005 USD = 7,000 micros
    assert cost_usd_micros(sonnet, Usage(input_tokens=1_000, output_tokens=500)) == 7_000
    # 1 input token = 2 micros exactly; 1 cache-read token = 0.1 micros -> rounds up to 1
    assert cost_usd_micros(sonnet, Usage(input_tokens=1, output_tokens=0)) == 2
    assert cost_usd_micros(sonnet, Usage(0, 0, cache_read_tokens=1)) == 1


def test_cache_tokens_are_priced_separately(repo_config: AiConfig) -> None:
    opus = repo_config.prices["claude-opus-5-5"]
    usage = Usage(
        input_tokens=0, output_tokens=0, cache_write_tokens=1_000, cache_read_tokens=10_000
    )

    # 1,000 * 5 USD/MTok + 10,000 * 0.20 USD/MTok = 5,000 + 2,000 micros
    assert cost_usd_micros(opus, usage) == 7_000


def test_haiku_long_prompt_tier_applies_above_threshold(repo_config: AiConfig) -> None:
    haiku = repo_config.prices["claude-haiku-5-5"]

    short = Usage(input_tokens=100_000, output_tokens=0)
    long = Usage(input_tokens=90_000, output_tokens=0, cache_read_tokens=10_001)

    assert cost_usd_micros(haiku, short) == 10_000  # 100k * 0.10 USD/MTok
    # 90k * 0.50 + 10,001 * 0.05 USD/MTok = 45,000 + 500.05 -> 45,501 micros
    assert cost_usd_micros(haiku, long) == 45_501


def test_in_memory_ledger_tracks_per_org_and_month() -> None:
    ledger = InMemoryBudgetLedger()

    ledger.record("org-a", "2026-10", 1_500)
    ledger.record("org-a", "2026-10", 500)
    ledger.record("org-a", "2026-11", 7)
    ledger.record("org-b", "2026-10", 9)

    assert ledger.spent("org-a", "2026-10") == 2_000
    assert ledger.spent("org-a", "2026-11") == 7
    assert ledger.spent("org-b", "2026-10") == 9
    assert ledger.spent("org-c", "2026-10") == 0
