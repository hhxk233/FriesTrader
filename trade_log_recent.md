# 2026-09-25

Phase B ran in `live` mode. Four ordinary long candidates were considered. Two orders were reviewed; no order was placed.

## Loss limits

- Daily realized P&L: $0.00 (0.00% of $1,000.00 starting capital); 5.00% loss limit not breached.
- Weekly realized P&L: $0.00 (0.00% of $1,000.00 starting capital); 10.00% loss limit not breached.
- New entries and top-ups remained enabled.

## Separate cash-reserve sleeve

- BOXX was classified as the operator-authorized separate cash-reserve sleeve and excluded from ordinary candidates, stock risk checks, exit handling, stock-slot counts, and order preview/placement. Its value remained in broker total value and was not treated as cash.

## Candidates

- IOT (new, high): rejected by sizing because a $202.02 allocation would leave $98.03 cash, below the $101.01 minimum buffer.
- FRO (new, high): the 0.5302% price-gap recheck found no thesis invalidation; rejected by sizing because a $202.02 allocation would leave $98.03 cash, below the $101.01 minimum buffer.
- AKAM (new, low): the 1.0301% price-gap recheck found no thesis invalidation; approved and sized at $60.61. Robinhood preview succeeded with no alerts, but placement was blocked by `unverified_net_deposit_basis`.
- DOCU (new, low): approved and sized at $60.61. Robinhood preview succeeded with no alerts, but placement was not attempted after the controlling runtime denial.
