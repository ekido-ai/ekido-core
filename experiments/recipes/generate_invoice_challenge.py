"""Generate a supplementary synthetic invoice stress set; it is not the quality gate."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from generate_invoice_fields import ALPHABET, gstin_check_character

ROOT = Path(__file__).resolve().parent / "invoice-fields"
VENDORS = (
    "Fictional Amber Kite Supplies", "Fictional Blue Elm Workshop",
    "Fictional Copper Lake Goods", "Fictional Ivory Finch Traders",
    "Fictional Violet Reed Tools", "Fictional Silver Fern Textiles",
    "Fictional Cedar Moon Parts", "Fictional Paper Cloud Studio",
    "Fictional Coral Grove Store", "Fictional Maple Stone Materials",
)
STATES = ("07", "09", "19", "27", "29", "33")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def rows() -> list[dict[str, str]]:
    result = []
    for index in range(60):
        vendor = VENDORS[index % len(VENDORS)]
        invoice_no = (f"AK/{2024 + index % 3}/{index + 130:04d}" if index % 2
                      else f"DOC-{index + 731:04d}-X")
        # Day > 12 makes DD/MM/YYYY unambiguous without a locale assumption.
        day = date(2024 + index // 48, 1 + (index // 4) % 12, 13 + 4 * (index % 4))
        printed_date = (day.isoformat(), day.strftime("%d/%m/%Y"),
                        f"{day.day:02d} {MONTHS[day.month - 1]} {day.year}")[index % 3]
        # Whole-rupee line items keep the arithmetic independently checkable.
        first, second = 900 + index * 13, 300 + index * 7
        tax = 37 + index
        total = first + second + tax
        printed_total = f"{total:,}.00" if index % 2 else f"{total}.00"
        prefix = f"{STATES[index % len(STATES)]}ZZZPZ{index + 500:04d}Z1Z"
        valid = gstin_check_character(prefix)
        gstin = prefix + ALPHABET[(ALPHABET.index(valid) + 1) % len(ALPHABET)]
        fields = {"vendor": vendor, "invoice_no": invoice_no, "date": day.isoformat(),
                  "total": f"{total}.00", "gstin": gstin}
        seller = f"Seller: {vendor}\nTax registration: {gstin}"
        document = f"Document: {invoice_no}\nInvoice date: {printed_date}"
        lines = f"Item A: INR {first}.00\nItem B: INR {second}.00\nTax: INR {tax}.00"
        address = "Address: Fictional Lane, Example District"
        payable = f"Grand total: INR {printed_total}"
        layouts = (
            (seller, address, document, lines, payable),
            (document, seller, lines, address, payable),
            (payable, document, address, lines, seller),
            (address, seller, payable, lines, document),
            (lines, document, seller, payable, address),
        )
        details = "\n".join(layouts[index % len(layouts)])
        result.append({"text": details, "json": json.dumps(fields, ensure_ascii=False)})
    return result


def main() -> None:
    with (ROOT / "challenge.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("text", "json"))
        writer.writeheader()
        writer.writerows(rows())
    print("challenge:", len(rows()), "examples")


if __name__ == "__main__":
    main()
