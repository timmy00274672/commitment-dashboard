#!/usr/bin/env python3
"""Read a Lenovo project commitment .xlsm and report monthly over-allocation by email.

The source workbook is opened read-only. Each project's monthly values are summed
across all its resource rows and then across projects for the same normalized
engineer email. An over-allocation is a person-month total strictly above 1.0.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
EXCLUDED_SHEETS = {
    "Project Resource Template",
    "Rules & Guidelines",
    "Change History",
    "Project List",
    "Resource overview",
}


def as_email(value):
    if value is None:
        return ""
    match = EMAIL_RE.search(str(value))
    return match.group(0).strip().lower() if match else ""


def as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def month_label(value):
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m")
    return ""


def write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze(workbook_path: Path, output_dir: Path, threshold: float):
    # data_only reads the saved/cached numeric values; the workbook is never saved.
    wb = openpyxl.load_workbook(workbook_path, read_only=False, data_only=True)
    project_totals = defaultdict(float)  # (email, month, project) -> allocation
    person_names = defaultdict(set)
    person_functions = defaultdict(set)
    contribution_rows = []
    missing_email_rows = []
    project_sheets = []
    skipped_sheets = []

    for ws in wb.worksheets:
        if ws.title in EXCLUDED_SHEETS:
            skipped_sheets.append(ws.title)
            continue
        if ws.cell(1, 1).value != "Project:":
            skipped_sheets.append(ws.title)
            continue
        project = str(ws.cell(1, 2).value or ws.title).strip()
        # Locate the resource table by its email header; template variants shift rows.
        header_row = None
        for row_idx in range(1, min(ws.max_row, 20) + 1):
            if any(str(ws.cell(row_idx, col).value or "").strip().lower() == "engineer email"
                   for col in range(1, min(ws.max_column, 20) + 1)):
                header_row = row_idx
                break
        if header_row is None:
            skipped_sheets.append(f"{ws.title} (resource header not found)")
            continue
        headers = {str(ws.cell(header_row, c).value or "").strip().lower(): c
                   for c in range(1, ws.max_column + 1)}
        email_col = headers.get("engineer email")
        name_col = headers.get("name")
        function_col = headers.get("function")
        if not email_col:
            skipped_sheets.append(f"{ws.title} (email column not found)")
            continue

        # Dates are directly above the resource table on normal sheets, and can
        # be two rows above on template variants. Use actual date-valued cells.
        date_row = None
        for candidate in range(max(1, header_row - 3), header_row):
            if any(isinstance(ws.cell(candidate, c).value, (date, datetime))
                   for c in range(1, ws.max_column + 1)):
                date_row = candidate
        if date_row is None:
            skipped_sheets.append(f"{ws.title} (month row not found)")
            continue
        month_cols = [(c, month_label(ws.cell(date_row, c).value))
                      for c in range(1, ws.max_column + 1)
                      if month_label(ws.cell(date_row, c).value)]
        if not month_cols:
            skipped_sheets.append(f"{ws.title} (no month columns)")
            continue
        project_sheets.append(project)

        for r in range(header_row + 1, ws.max_row + 1):
            raw_email = ws.cell(r, email_col).value
            email = as_email(raw_email)
            name = str(ws.cell(r, name_col).value or "").strip() if name_col else ""
            function = str(ws.cell(r, function_col).value or "").strip() if function_col else ""
            allocations = []
            for c, month in month_cols:
                value = as_number(ws.cell(r, c).value)
                if value is not None and abs(value) > 1e-12:
                    allocations.append((month, value))
            if not allocations:
                continue
            if not email:
                missing_email_rows.append({
                    "project": project,
                    "sheet": ws.title,
                    "row": r,
                    "name": name,
                    "function": function,
                    "email_cell": str(raw_email or ""),
                    "monthly_allocations": "; ".join(f"{m}={v:.4g}" for m, v in allocations),
                })
                continue
            key = (email, name)
            if name:
                person_names[email].add(name)
            if function:
                person_functions[email].add(function)
            for month, value in allocations:
                project_totals[(email, month, project)] += value
                contribution_rows.append({
                    "email": email,
                    "name": name,
                    "project": project,
                    "function": function,
                    "sheet": ws.title,
                    "row": r,
                    "month": month,
                    "allocation": round(value, 6),
                })

    person_month_totals = defaultdict(float)
    person_month_projects = defaultdict(list)
    for (email, month, project), total in project_totals.items():
        person_month_totals[(email, month)] += total
        if abs(total) > 1e-12:
            person_month_projects[(email, month)].append((project, total))

    total_rows = []
    violation_rows = []
    for (email, month), total in sorted(person_month_totals.items()):
        projects = sorted(person_month_projects[(email, month)])
        name_list = sorted(person_names[email])
        base = {
            "email": email,
            "names_in_workbook": " / ".join(name_list),
            "month": month,
            "total_allocation": round(total, 6),
            "over_threshold": "YES" if total > threshold + 1e-9 else "NO",
            "projects_and_allocations": "; ".join(f"{p}={v:.4g}" for p, v in projects),
        }
        total_rows.append(base)
        if total > threshold + 1e-9:
            violation_rows.append(base)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "person_month_totals.csv", [
        "email", "names_in_workbook", "month", "total_allocation", "over_threshold",
        "projects_and_allocations",
    ], total_rows)
    write_csv(output_dir / "over_allocations.csv", [
        "email", "names_in_workbook", "month", "total_allocation", "over_threshold",
        "projects_and_allocations",
    ], violation_rows)
    write_csv(output_dir / "allocation_contributions.csv", [
        "email", "name", "project", "function", "sheet", "row", "month", "allocation",
    ], sorted(contribution_rows, key=lambda x: (x["email"], x["month"], x["project"], x["row"])))
    write_csv(output_dir / "rows_without_email.csv", [
        "project", "sheet", "row", "name", "function", "email_cell", "monthly_allocations",
    ], missing_email_rows)

    print(f"Workbook: {workbook_path}")
    print(f"Project sheets analyzed: {len(project_sheets)}")
    print(f"Skipped non-project/control sheets: {len(skipped_sheets)}")
    print(f"Unique email identities: {len(person_names)}")
    print(f"Person-months over {threshold:g}: {len(violation_rows)}")
    print(f"Rows with nonzero workload but no parseable engineer email: {len(missing_email_rows)}")
    print(f"Reports: {output_dir}")
    if skipped_sheets:
        print("Skipped: " + ", ".join(skipped_sheets))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="Path to the downloaded .xlsm")
    parser.add_argument("--output-dir", type=Path, default=Path("commitment_analysis"))
    parser.add_argument("--threshold", type=float, default=1.0,
                        help="Flag monthly totals strictly greater than this value (default: 1.0)")
    args = parser.parse_args()
    analyze(args.workbook, args.output_dir, args.threshold)


if __name__ == "__main__":
    main()
