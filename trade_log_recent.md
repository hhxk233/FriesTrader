# 2026-09-24

Phase B ran in `live` mode. Five ordinary long candidates were considered. One order was reviewed, but the repository's execution-evidence hook blocked placement, so no live order was placed.

## Loss limits

- Daily realized P&L: $0.00 (0.00% of $1,000.00 starting capital); 5.00% loss limit not breached.
- Weekly realized P&L: $0.00 (0.00% of $1,000.00 starting capital); 10.00% loss limit not breached.
- New entries and top-ups remained enabled.

## Separate cash-reserve sleeve

- BOXX was classified as the operator-authorized separate cash-reserve sleeve and excluded from ordinary Phase B candidates, stock risk checks, exit handling, stock-slot counts, and order preview/placement. Full broker total value included BOXX, while its value was not treated as cash.

## Candidates

- INOD (new, high): rejected because its $70.49 ask was 22.9178% above the 20-day average, exceeding the 10% extension cap.
- DOCU (new, high): rejected by sizing because a $201.99 allocation would leave $98.06 cash, below the $101.00 minimum buffer.
- BRZE (new, medium): approved and sized at $121.20; Robinhood preview succeeded with no alerts, but placement was blocked by `verified_regular_session_evidence_not_met`.
- IOT (new, medium): rejected by sizing because a $121.20 allocation after the higher-ranked approval would leave $57.65 cash, below the $101.00 minimum buffer.
- TRMD (new, medium): rejected by sizing because a $121.20 allocation after the higher-ranked approval would leave $57.65 cash, below the $101.00 minimum buffer.
