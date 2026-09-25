# 2026-09-25

Phase B ran in `live` mode. Five ordinary long candidates were considered. Two orders were reviewed, but the repository's enforcement hook blocked live placement because net-deposit basis was unverified, so no order was placed.

## Loss limits

- Daily realized P&L: $0.00 (0.00% of $1,000.00 starting capital); 5.00% loss limit not breached.
- Weekly realized P&L: $0.00 (0.00% of $1,000.00 starting capital); 10.00% loss limit not breached.
- New entries and top-ups remained enabled.

## Separate cash-reserve sleeve

- BOXX was classified as the operator-authorized separate cash-reserve sleeve and excluded from ordinary Phase B candidates, stock risk checks, exit handling, stock-slot counts, and order preview/placement. Full broker total value included BOXX, while its value was not treated as cash.

## Candidates

- INOD (new, high): rejected because its $69.32 ask was 19.2115% above the 20-day average, exceeding the 10% extension cap.
- ZS (new, medium): approved and sized at $121.22; Robinhood preview succeeded with no alerts, but placement was blocked by `unverified_net_deposit_basis`.
- NVT (new, medium): rejected by sizing because a $121.22 allocation would leave $57.61 cash, below the $101.02 minimum buffer.
- AKAM (new, low): approved and sized at $60.61 after the 2.3222% gap re-check found no thesis invalidation; Robinhood preview succeeded with no alerts, but placement was not attempted after the controlling runtime denial.
- DOCU (new, low): rejected by sizing because a $60.61 allocation would leave $57.61 cash, below the $101.02 minimum buffer.
