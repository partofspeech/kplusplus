"""Remove K+ service headers from decision text."""
import re


def clean_decision_text(text: str) -> str:
    # Match whole UI lines only: fractions and mentions inside the decision
    # itself must remain untouched.
    text = re.sub(
        r"(?im)^[^\S\n]*(?:См\.[^\S\n]*также[^\S\n]*:[^\S\n]*)?Краткий пересказ[^\S\n]*$",
        "", text,
    )
    text = re.sub(
        r"(?im)^[^\S\n]*Документ[^\S\n]*:[^\S\n]*\d+[^\S\n]*/[^\S\n]*\d+[^\S\n]*$",
        "", text,
    )
    text = re.sub(r"(?m)^КонсультантПлюс\s*$", "", text)
    text = re.sub(r"(?m)^надежная правовая поддержка www\.consultant\.ru Страница\s+\d+\s+из\s+\d+\s*$", "", text)
    text = re.sub(r"(?m)^Документ предоставлен КонсультантПлюс\s*$", "", text)
    text = re.sub(r"(?m)^Дата сохранения:\s*\d{2}\.\d{2}\.\d{4}\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
