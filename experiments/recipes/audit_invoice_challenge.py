"""Check synthetic challenge labels independently of the generation formula."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from audit_invoice_fields import GSTIN, valid_check_digit
from generate_invoice_challenge import rows as generated_rows

ROOT = Path(__file__).resolve().parent / "invoice-fields"


def read(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(encoding="utf-8", newline="") as handle:
        data = list(csv.DictReader(handle))
    for row in data:
        row["text"] = row["text"].replace("\r\n", "\n").replace("\r", "\n")
    return data


def field(text: str, name: str) -> str:
    matches = re.findall(rf"(?m)^{re.escape(name)}: (.+)$", text)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} field")
    return matches[0]


def main() -> None:
    data = read("challenge.csv")
    if len(data) != 60 or data != generated_rows():
        raise ValueError("challenge rows do not match the deterministic generator")
    existing = {" ".join(row["text"].casefold().split()) for name in ("train.csv", "test.csv") for row in read(name)}
    seen, vendors, prefixes, formats = set(), set(), set(), set()
    for row in data:
        text, label = row["text"], json.loads(row["json"])
        normalized = " ".join(text.casefold().split())
        if normalized in existing or normalized in seen:
            raise ValueError("duplicate or existing split input")
        seen.add(normalized)
        if set(label) != {"vendor", "invoice_no", "date", "total", "gstin"}:
            raise ValueError("incorrect label fields")
        for key, name in (("vendor", "Seller"), ("invoice_no", "Document"), ("gstin", "Tax registration")):
            if label[key] != field(text, name):
                raise ValueError(f"incorrect {key} label")
        raw_date = field(text, "Invoice date")
        fmt = "%d/%m/%Y" if "/" in raw_date else "%d %b %Y" if " " in raw_date else "%Y-%m-%d"
        if fmt == "%d %b %Y":
            day, month, year = raw_date.split()
            months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
            parsed_date = date(int(year), months.index(month) + 1, int(day))
        else:
            parsed_date = datetime.strptime(raw_date, fmt).date()
        if parsed_date.isoformat() != label["date"]:
            raise ValueError("incorrect normalized date")
        formats.add(fmt)
        amounts = [Decimal(field(text, name).removeprefix("INR ").replace(",", ""))
                   for name in ("Item A", "Item B", "Tax", "Grand total")]
        if sum(amounts[:3]) != amounts[3] or f"{amounts[3]:.2f}" != label["total"]:
            raise ValueError("incorrect normalized total or line-item arithmetic")
        gstin = label["gstin"]
        if not GSTIN.fullmatch(gstin) or gstin[-1] == valid_check_digit(gstin):
            raise ValueError("expected deliberately invalid GSTIN check digit")
        vendors.add(label["vendor"])
        prefixes.add(gstin[:2])
    assert len(vendors) == 10 and len(prefixes) == 6 and len(formats) == 3
    print(f"{len(data)} rows verified; {len(vendors)} vendors; {len(prefixes)} state prefixes; {len(formats)} date formats; zero exact input overlap")


if __name__ == "__main__":
    main()
