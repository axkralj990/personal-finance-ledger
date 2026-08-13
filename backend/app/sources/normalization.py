import unicodedata


def normalize_description(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
