"""Explainable Russian recruitment-spam filter, no external dependencies."""
import re
import unicodedata
from dataclasses import dataclass


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    text = "".join(c for c in text if unicodedata.category(c) not in {"Cf", "Mn"})
    # Replace visually similar Latin letters only inside mixed Cyrillic words.
    table = str.maketrans("aceopxyktmhb", "асеорхук тмнв".replace(" ", ""))
    text = re.sub(r"[a-zа-я]+", lambda m: m[0].translate(table)
                  if re.search("[а-я]", m[0]) else m[0], text)
    text = re.sub(r"под[\W_]*работ", "подработ", text)
    return re.sub(r"\s+", " ", text).strip()


RULES = [
    ("recruitment", 3, r"(?:ищу|ищем|возьму|возьмем|нужн\w*|надо|требу\w*|набира\w*)\b.{0,65}\b(?:чел\w*|люд\w*|сотрудник\w*|помощник\w*)"),
    ("side_job", 2, r"\b(?:подработ\w*|заработ\w*)\b"),
    ("easy", 2, r"(?:ни\s*чего|не\s*чего)\s+сложного|без\s+опыта|легк\w*\s+(?:деньги|работ\w*|доход)|пару\s+часов"),
    ("cash", 3, r"\b(?:плачу|заплачу|оплат\w*|выплат\w*|на\s+руки|налич\w*|отда[мю]\s+нал|дам\s+нал)\b"),
    ("amount", 2, r"\b\d{3,6}\b|\b\d+(?:[.,]\d+)?\s*(?:(?:к|k|р|p|тыс\w*|руб\w*)\b|₽)"),
    ("short_shift", 2, r"\bза\s+\d{1,2}\s*(?:час\w*|ч\b)"),
    ("private_contact", 1, r"\b(?:пиш\w*|напиш\w*|отпиш\w*)\s+(?:мне\s+)?(?:в\s+)?(?:лс|лич\w*|директ)\b"),
    ("scheme", 4, r"\b(?:вписа\w*|влет\w*|залет\w*)\b.{0,35}\bтем\w*|\bкто\s+свободен\b"),
]
COMPILED = [(name, weight, re.compile(pattern)) for name, weight, pattern in RULES]


@dataclass(frozen=True)
class Verdict:
    spam: bool
    score: int
    reasons: tuple[str, ...]


def classify(text: str, threshold: int = 7) -> Verdict:
    normalized = normalize(text)
    matches = [(name, weight) for name, weight, pattern in COMPILED if pattern.search(normalized)]
    found = {name for name, _ in matches}
    def has(pattern):
        return bool(re.search(pattern, normalized))

    # Campaign rules require several independent signals, never a specific username.
    crypto = has(r"\bкрипт\w*\b")
    contact = has(r"(?<!\w)@[a-z0-9_]{5,32}\b|\bt\.me/|\b(?:в\s+лич\w*|в\s+лс)\b")
    training = has(r"\bобуч\w*\s+бесплатно|\bс\s+нуля\b|\bкуратор\b")
    tasks = has(r"\bнесложн\w*\s+задач\w*|\bонлайн[\s-]+доход\w*|\bбизнес\w*")
    if crypto and contact and ("recruitment" in found or (training and tasks)):
        matches.append(("crypto_promotion", 7))
    # The user also marked cash cryptocurrency exchange solicitation as unwanted.
    exchange = has(r"\bобменник\w*|\bобмен[\s-]+крипт\w*")
    request = has(r"\b(?:кто[\s-]+то\s+знает|ищу|подскаж\w*)\b")
    purchase = has(r"\bкупить\b|\bпродает\b|\bпродаст\b")
    if crypto and exchange and request and purchase and "cash" in found:
        matches.append(("crypto_cash_exchange", 7))
    if ("amount" in found
            and has(r"\b(?:оставить|написать|напиши\w*|оставь\w*)\s+(?:\w+\s+){0,2}(?:отзыв\w*|фидб[еэ]к\w*)\b")):
        matches.append(("paid_review", 7))
    alcohol = has(r"\b(?:мартини|алкогол\w*|вин[оа]|пив[оа]|шампанск\w*)\b")
    delivery = has(r"\b(?:купить|принести|привезти)\b")
    reward = has(r"\bбутылк\w*\s+за\s+помощь\b")
    if {"recruitment", "amount"} <= found and alcohol and delivery and reward:
        matches.append(("alcohol_errand", 2))
    reasons = tuple(name for name, _ in matches)
    score = sum(weight for _, weight in matches)
    # Require both recruitment context and an incentive, never a single keyword.
    context = bool(set(reasons) & {"recruitment", "side_job", "scheme"})
    incentive = bool(set(reasons) & {"cash", "amount", "easy", "short_shift"})
    campaign = bool(set(reasons) & {"crypto_promotion", "crypto_cash_exchange", "paid_review"})
    return Verdict(((context and incentive) or campaign) and score >= threshold, score, reasons)
