# 2026-09-25

Phase B ran in `live` mode. Four ordinary long candidates were considered. Two orders were reviewed; no order was placed.

## Loss limits

- Daily realized P&L: $0.00 (0.00% of $1,009.85 starting capital); 5.00% loss limit not breached.
- Weekly realized P&L: $0.00 (0.00% of $1,009.85 starting capital); 10.00% loss limit not breached.
- New entries and top-ups remained enabled.

## Separate cash-reserve sleeve

- BOXX was classified as the operator-authorized separate cash-reserve sleeve and excluded from ordinary candidates, stock risk checks, exit handling, stock-slot counts, and order preview/placement. Its value remained in broker total value and was not treated as cash.

## Candidates

- IOT (new, high): passed the entry gate, then was rejected by sizing because a $202.01 allocation would leave $98.04 cash, below the $101.01 minimum buffer.
- DOCU (new, high): passed the entry gate, then was rejected by sizing because a $202.01 allocation would leave $98.04 cash, below the $101.01 minimum buffer.
- AKAM (new, low): passed the entry gate and was approved at $60.60. The Robinhood preview succeeded with no alerts, but placement was blocked by `evidence_validation_failed`.
- WTTR (new, low): passed the entry gate and was approved at $60.60. The Robinhood preview succeeded with no alerts; placement was not attempted after the controlling AKAM denial.
