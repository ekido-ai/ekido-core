"""Generates experiments/pii/pii-set.jsonl: 300 labelled lines for measuring PII stripping.

    python -I experiments/pii/generate_pii_set.py [--out path/to/pii-set.jsonl]

Everything is made up, and no identifier can belong to a real person. Names, places and amounts are drawn from short lists of
common words. Phone numbers, Aadhaar, PAN, GSTIN and UPI IDs have the right shape but cannot be issued:
- Aadhaar numbers pass the Verhoeff check but start with 0 or 1, which UIDAI never issues;
- mobile numbers start with 5, a series India does not allocate (real mobiles start with 6 to 9), and are always written with a
  +91 or 0 prefix or with a space or hyphen inside, never as a bare ten-digit string;
- PANs use a 4th letter that is not one of the ten holder-type codes (P C H F A T B L J G), so no PAN carries it;
- GSTINs pass their own check digit but contain such a PAN, so none can be real.
Emails use the reserved example.com / example.org / example.net domains. The
output is fixed by the seed, so the same command always writes the same file. Span offsets are computed while the
text is built, never typed by hand.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

SEED = 20261117
PII_LINES, CLEAN_LINES = 240, 60

# (Roman, Devanagari) pairs, so a Devanagari line and a Roman line draw from the same pool.
FIRST = [("Rahul", "राहुल"), ("Priya", "प्रिया"), ("Amit", "अमित"), ("Sneha", "स्नेहा"), ("Vikram", "विक्रम"),
         ("Anjali", "अंजलि"), ("Rohan", "रोहन"), ("Pooja", "पूजा"), ("Karan", "करण"), ("Neha", "नेहा"),
         ("Suresh", "सुरेश"), ("Kavita", "कविता"), ("Deepak", "दीपक"), ("Meena", "मीना"), ("Arjun", "अर्जुन"),
         ("Divya", "दिव्या"), ("Manoj", "मनोज"), ("Sunita", "सुनीता"), ("Ravi", "रवि"), ("Isha", "ईशा")]
LAST = [("Sharma", "शर्मा"), ("Verma", "वर्मा"), ("Gupta", "गुप्ता"), ("Singh", "सिंह"), ("Patel", "पटेल"),
        ("Iyer", "अय्यर"), ("Reddy", "रेड्डी"), ("Nair", "नायर"), ("Joshi", "जोशी"), ("Mehta", "मेहता"),
        ("Kulkarni", "कुलकर्णी"), ("Yadav", "यादव"), ("Das", "दास"), ("Bansal", "बंसल"), ("Chauhan", "चौहान")]
AREA = [("Shanti Nagar", "शांति नगर"), ("Gandhi Road", "गांधी रोड"), ("Lake View Colony", "लेक व्यू कॉलोनी"),
        ("Sector 14", "सेक्टर 14"), ("Nehru Park", "नेहरू पार्क"), ("Civil Lines", "सिविल लाइन्स"),
        ("Model Town", "मॉडल टाउन"), ("Green Park", "ग्रीन पार्क")]
CITY = [("Pune", "पुणे", "411001"), ("Jaipur", "जयपुर", "302001"), ("Indore", "इंदौर", "452001"),
        ("Lucknow", "लखनऊ", "226001"), ("Nagpur", "नागपुर", "440001"), ("Surat", "सूरत", "395003"),
        ("Bhopal", "भोपाल", "462001"), ("Kochi", "कोच्चि", "682001")]
UPI_HANDLES = ["okaxis", "oksbi", "okhdfcbank", "ybl", "paytm", "ibl"]
EMAIL_DOMAINS = ["example.com", "example.org", "example.net"]
GST_STATES = ["27", "07", "29", "33", "24", "09", "08", "23"]
PRODUCTS = ["blue kurta", "steel bottle", "cotton bedsheet", "phone cover", "leather wallet", "desk lamp"]

_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def verhoeff_ok(digits: str) -> bool:
    check = 0
    for position, digit in enumerate(reversed(digits)):
        check = _D[check][_P[position % 8][int(digit)]]
    return check == 0


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def aadhaar_digits(rng: random.Random) -> str:
    while True:
        body = rng.choice("01") + digits(rng, 10)  # 0 and 1 are never the first digit of an issued Aadhaar number
        for last in "0123456789":
            if verhoeff_ok(body + last):
                return body + last


def not_aadhaar_digits(rng: random.Random) -> str:
    """Twelve digits that look like an Aadhaar number but fail the checksum (a reference number, not PII)."""
    while True:
        candidate = rng.choice("23456789") + digits(rng, 11)
        if not verhoeff_ok(candidate):
            return candidate


ISSUED_PAN_TYPES = "PCHFATBLJG"  # the 4th letter of a real PAN is one of these ten holder types
UNUSED_PAN_TYPES = "DEKMNQRSUVWXYZ"  # letters that are not a holder type, so no real PAN has them


def pan(rng: random.Random) -> str:
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return "".join(rng.choice(letters) for _ in range(3)) + rng.choice(UNUSED_PAN_TYPES) + rng.choice(letters) + digits(rng, 4) + rng.choice(letters)


def gstin(rng: random.Random) -> str:
    body = rng.choice(GST_STATES) + pan(rng) + rng.choice("123456789") + "Z"
    total = 0
    for index, char in enumerate(body):
        value = GST_CHARS.index(char) * (1 if index % 2 == 0 else 2)
        total += value // 36 + value % 36
    return body + GST_CHARS[(36 - total % 36) % 36]


class Maker:
    """Draws one value per placeholder. `script` is "roman" or "deva" and only changes names and places."""

    def __init__(self, rng: random.Random, script: str) -> None:
        self.rng, self.deva = rng, script == "deva"

    def name(self) -> str:
        first, last = self.rng.choice(FIRST), self.rng.choice(LAST)
        return f"{first[1]} {last[1]}" if self.deva else f"{first[0]} {last[0]}"

    def first_name(self) -> str:
        first = self.rng.choice(FIRST)
        return first[1] if self.deva else first[0]

    def phone(self) -> str:
        number = "5" + digits(self.rng, 9)  # India allocates no mobile series starting with 5, so this is nobody's number
        style = self.rng.randrange(4)
        if style == 0:
            return "+91" + number
        if style == 1:
            return f"+91 {number[:5]} {number[5:]}"
        if style == 2:
            return "0" + number
        return f"{number[:5]}-{number[5:]}"

    def email(self) -> str:
        first, last = self.rng.choice(FIRST)[0].lower(), self.rng.choice(LAST)[0].lower()
        sep = self.rng.choice([".", "_", ""])
        return f"{first}{sep}{last}{self.rng.choice(['', digits(self.rng, 2)])}@{self.rng.choice(EMAIL_DOMAINS)}"

    def aadhaar(self) -> str:
        raw = aadhaar_digits(self.rng)
        return self.rng.choice([raw, f"{raw[:4]} {raw[4:8]} {raw[8:]}", f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"])

    def pan(self) -> str:
        return pan(self.rng)

    def gstin(self) -> str:
        return gstin(self.rng)

    def upi(self) -> str:
        first = self.rng.choice(FIRST)[0].lower()
        tail = self.rng.choice(["", digits(self.rng, 2), digits(self.rng, 4)])
        if self.rng.random() < 0.3:
            return f"{digits(self.rng, 10)}@{self.rng.choice(UPI_HANDLES)}"
        return f"{first}{tail}@{self.rng.choice(UPI_HANDLES)}"

    def address(self) -> str:
        area = self.rng.choice(AREA)
        city = self.rng.choice(CITY)
        house = self.rng.randint(1, 450)
        if self.deva:
            return f"फ्लैट {house}, {area[1]}, {city[1]} {city[2]}"
        return self.rng.choice([f"Flat {house}, {area[0]}, {city[0]} {city[2]}", f"House No. {house}, {area[0]}, {city[0]}, {city[2]}"])

    # Placeholders that are not PII, used to make lines distinct and to build the tricky clean lines.
    def order(self) -> str:
        return f"ORD{digits(self.rng, 6)}"

    def amount(self) -> str:
        return str(self.rng.choice([199, 349, 499, 899, 1250, 2499, 3999]) + self.rng.randint(0, 40))

    def long_ref(self) -> str:  # 10 digits: looks like a phone number but is a tracking number (starts with 5, so it is nobody's number)
        return "5" + digits(self.rng, 9)

    def bare_ref(self) -> str:  # 12 digits that fail Verhoeff: looks like Aadhaar but is not
        return not_aadhaar_digits(self.rng)

    def pan_like(self) -> str:  # coupon code shaped like a PAN: five letters, four digits, a letter (4th letter never a holder type)
        letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
        return "".join(self.rng.choice(letters) for _ in range(3)) + self.rng.choice(UNUSED_PAN_TYPES) + self.rng.choice(letters) + digits(self.rng, 4) + self.rng.choice(letters)

    def product(self) -> str:
        return self.rng.choice(PRODUCTS)

    def city(self) -> str:
        city = self.rng.choice(CITY)
        return city[1] if self.deva else city[0]

    def qty(self) -> str:
        return str(self.rng.randint(2, 12))

    def pincode_only(self) -> str:
        return self.rng.choice(CITY)[2]

    def invoice(self) -> str:
        return f"INV-{self.rng.randint(2025, 2026)}-{digits(self.rng, 5)}"

    def awb(self) -> str:
        return self.long_ref()


SPAN_TYPES = {"NAME": "name", "PHONE": "phone", "EMAIL": "email", "AADHAAR": "aadhaar", "PAN": "pan",
              "GSTIN": "gstin", "UPI_ID": "upi", "ADDRESS": "address"}
OTHER = {"FIRST": "first_name", "ORDER": "order", "AMOUNT": "amount", "REF": "long_ref", "BARE": "bare_ref",
         "COUPON": "pan_like", "PRODUCT": "product", "CITY": "city", "QTY": "qty", "PIN": "pincode_only",
         "INVOICE": "invoice", "AWB": "awb"}

# Lines that contain PII. {TYPE} marks a labelled span; {ORDER}, {AMOUNT} and the like are plain filler.
PII_TEMPLATES = {
    "en": [
        "Hi, my name is {NAME} and my number is {PHONE}. Please call me about order {ORDER}.",
        "Please send the invoice to {EMAIL} for {PRODUCT}, total Rs {AMOUNT}.",
        "Ship it to {NAME}, {ADDRESS}. Contact {PHONE}.",
        "My Aadhaar is {AADHAAR}, please update the KYC for my account.",
        "PAN {PAN} is on the GST invoice, can you confirm it?",
        "Our GSTIN is {GSTIN}. Please raise the bill in the company name.",
        "I paid through UPI {UPI_ID}, order {ORDER} still shows unpaid.",
        "Refund of Rs {AMOUNT} should go back to {UPI_ID}.",
        "{NAME} here, email {EMAIL}, phone {PHONE}. My {PRODUCT} arrived damaged.",
        "Deliver to {ADDRESS}. If I am out, call {PHONE}.",
        "Invoice {INVOICE}: bill to {NAME}, GSTIN {GSTIN}, PAN {PAN}.",
        "Customer {NAME} ({EMAIL}) asked to cancel order {ORDER}.",
        "Aadhaar {AADHAAR} and PAN {PAN} attached for the loan form of {NAME}.",
        "Please change my delivery address to {ADDRESS}.",
        "Reach the owner, {NAME}, on {PHONE} or {EMAIL}.",
        "Seller GSTIN {GSTIN}, contact {EMAIL}, Rs {AMOUNT} for {QTY} {PRODUCT}.",
    ],
    "hinglish": [
        "Mera naam {NAME} hai, mujhe {PHONE} pe call karo, order {ORDER} ka kya hua?",
        "Bill {EMAIL} pe bhej do, {PRODUCT} ka Rs {AMOUNT} ka.",
        "Parcel {NAME} ke naam pe bhejna, pata hai {ADDRESS}. Phone {PHONE}.",
        "Mera Aadhaar number {AADHAAR} hai, KYC update kar do.",
        "PAN {PAN} hai mera, GST bill me daal dena.",
        "Hamari firm ka GSTIN {GSTIN} hai, usi pe invoice banana.",
        "UPI se {UPI_ID} se paisa bheja tha par order {ORDER} abhi bhi pending hai.",
        "Refund Rs {AMOUNT} mere UPI {UPI_ID} pe wapas karo.",
        "{NAME} bol raha hoon, email {EMAIL}, number {PHONE}. {PRODUCT} toota hua aaya.",
        "Delivery {ADDRESS} pe karna, ghar pe na mile to {PHONE} pe call karna.",
        "Invoice {INVOICE} me {NAME} ka PAN {PAN} aur GSTIN {GSTIN} daal diya hai.",
        "{NAME} ji ne order {ORDER} cancel karne ko kaha hai, unka mail {EMAIL}.",
        "Loan form ke liye {NAME} ka Aadhaar {AADHAAR} aur PAN {PAN} laga diya.",
        "Mera address badal do: {ADDRESS}.",
        "Malik {NAME} se {PHONE} ya {EMAIL} pe baat kar lo.",
        "Supplier ka GSTIN {GSTIN}, mail {EMAIL}, {QTY} {PRODUCT} ke Rs {AMOUNT}.",
    ],
    "deva": [
        "मेरा नाम {NAME} है, मुझे {PHONE} पर फ़ोन करो।",
        "बिल {EMAIL} पर भेज दो, कुल रकम Rs {AMOUNT}।",
        "पार्सल {NAME} के नाम से भेजना, पता {ADDRESS}।",
        "मेरा आधार नंबर {AADHAAR} है, केवाईसी अपडेट कर दो।",
        "मेरा पैन {PAN} है, जीएसटी बिल में लिख देना।",
        "हमारी फर्म का GSTIN {GSTIN} है।",
        "मैंने UPI {UPI_ID} से पैसे भेजे थे, ऑर्डर {ORDER} अभी भी पेंडिंग है।",
        "रिफंड {UPI_ID} पर वापस कर दो।",
        "{NAME} बोल रहा हूँ, ईमेल {EMAIL}, फ़ोन {PHONE}।",
        "डिलीवरी {ADDRESS} पर करना। फ़ोन {PHONE}।",
        "{NAME} का आधार {AADHAAR} और पैन {PAN} लगा दिया है।",
        "मेरा पता बदल दो: {ADDRESS}।",
    ],
}

# Lines with no PII at all, including the tricky look-alikes (order numbers that look like phone numbers, and so on).
CLEAN_TEMPLATES = {
    "en": [
        "Where is my order {ORDER}? It was supposed to arrive yesterday.",
        "Tracking number {AWB} shows out for delivery for {QTY} {PRODUCT}.",
        "Please send {QTY} more {PRODUCT} for Rs {AMOUNT} each.",
        "Invoice {INVOICE} total is Rs {AMOUNT}, due in 15 days.",
        "Use coupon {COUPON} at checkout to get 10 percent off.",
        "Reference {BARE} was issued by the courier for return pickup.",
        "The {PRODUCT} is great, delivery was fast, will order again.",
        "Do you have {PRODUCT} in stock in {CITY}?",
        "Please confirm the price of the {PRODUCT} before I pay.",
        "Pickup scheduled for order {ORDER}, courier reference {AWB}.",
    ],
    "hinglish": [
        "Mera order {ORDER} kab aayega? Kal tak aana tha.",
        "Tracking number {AWB} dikha raha hai out for delivery, {QTY} {PRODUCT} ka.",
        "{QTY} aur {PRODUCT} bhej do, Rs {AMOUNT} wale.",
        "Invoice {INVOICE} ka total Rs {AMOUNT} hai, 15 din me dena hai.",
        "Checkout pe coupon {COUPON} lagao, 10 percent off milega.",
        "Courier ne return pickup ke liye reference {BARE} diya hai.",
        "{PRODUCT} bahut badhiya hai, delivery fast thi, dobara lunga.",
        "{CITY} me {PRODUCT} stock me hai kya?",
        "Paisa dene se pehle {PRODUCT} ka rate confirm kar do.",
        "Order {ORDER} ka pickup lag gaya, courier reference {AWB}.",
    ],
    "deva": [
        "मेरा ऑर्डर {ORDER} कब आएगा? कल तक आना था।",
        "ट्रैकिंग नंबर {AWB} आउट फ़ॉर डिलीवरी दिखा रहा है।",
        "चालान {INVOICE} का कुल योग Rs {AMOUNT} है।",
        "चेकआउट पर कूपन {COUPON} लगाओ, 10 प्रतिशत छूट मिलेगी।",
        "कूरियर ने वापसी के लिए संदर्भ {BARE} दिया है।",
        "सामान बहुत अच्छा है, डिलीवरी तेज़ थी।",
        "{CITY} में स्टॉक है क्या?",
    ],
}

SLOT = re.compile(r"\{([A-Z_]+)\}")


def render(template: str, maker: Maker) -> tuple[str, list[dict]]:
    text, spans, cursor = "", [], 0
    for match in SLOT.finditer(template):
        text += template[cursor:match.start()]
        slot = match.group(1)
        if slot in SPAN_TYPES:
            value = getattr(maker, SPAN_TYPES[slot])()
            spans.append({"start": len(text), "end": len(text) + len(value), "type": slot})
        else:
            value = getattr(maker, OTHER[slot])()
        text += value
        cursor = match.end()
    return text + template[cursor:], spans


def build() -> list[dict]:
    rng = random.Random(SEED)
    # The mix: about 45% English, 40% Roman Hinglish, 15% Devanagari, for PII lines and clean lines alike.
    plan = {"en": 0.45, "hinglish": 0.40, "deva": 0.15}
    records, seen = [], set()
    for pool, total in ((PII_TEMPLATES, PII_LINES), (CLEAN_TEMPLATES, CLEAN_LINES)):
        for language, share in plan.items():
            count = round(total * share)
            templates = pool[language]
            index = 0
            while count > 0:
                template = templates[index % len(templates)]
                index += 1
                text, spans = render(template, Maker(rng, "deva" if language == "deva" else "roman"))
                if text in seen:
                    continue
                seen.add(text)
                records.append({"text": text, "spans": spans})
                count -= 1
    rng.shuffle(records)
    return records


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "pii-set.jsonl")
    args = parser.parse_args(argv)
    records = build()
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} lines to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
