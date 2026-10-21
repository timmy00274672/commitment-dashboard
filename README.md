# Commitment Dashboard

Generate a self-contained HTML dashboard from a Lenovo resource commitment workbook. The dashboard supports filters for escalation path, person, month, and project, plus a workload matrix with per-cell allocation details.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Refresh the dashboard

```bash
.venv/bin/python build_commitment_dashboard.py '/path/to/commitment-workbook.xlsm'
```

Open `commitment_analysis/commitment_dashboard.html` in a browser. Each refresh regenerates the CSV reports and dashboard from the workbook without modifying the source Excel file.

## Outputs

- `person_month_totals.csv`: total workload per person and month.
- `over_allocations.csv`: person-months whose workload exceeds 1.0.
- `allocation_contributions.csv`: project-level assignments, including escalation path.
- `rows_without_email.csv`: TBH/TBD or other workload rows without a parseable engineer email.
- `commitment_dashboard.html`: interactive local dashboard.
