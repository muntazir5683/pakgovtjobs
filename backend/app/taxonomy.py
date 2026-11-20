"""Controlled vocabularies used by the extractor, the DB and the filters."""
import re

SECTORS = [
    "Federal",
    "Provincial",
    "Armed Forces",
    "Police",
    "Medical",
    "Testing",
    "Development & Societies",
    "Banking & Finance",
]

PROVINCES = [
    "All Pakistan",
    "Islamabad",
    "Punjab",
    "Sindh",
    "Khyber Pakhtunkhwa",
    "Balochistan",
    "Azad Kashmir",
    "Gilgit-Baltistan",
]

EDUCATION_LEVELS = [
    "Matric",
    "Intermediate",
    "Diploma",
    "Bachelor",
    "Master",
    "MPhil/PhD",
    "MBBS/BDS",
    "Engineering",
    "Other",
]

_SECTOR_ALIASES = {
    "armed forces": "Armed Forces",
    "army": "Armed Forces",
    "defence": "Armed Forces",
    "defense": "Armed Forces",
    "health": "Medical",
    "healthcare": "Medical",
    "medical": "Medical",
    "police": "Police",
    "federal": "Federal",
    "provincial": "Provincial",
    "testing": "Testing",
    "development": "Development & Societies",
    "development authority": "Development & Societies",
    "development authorities": "Development & Societies",
    "societies": "Development & Societies",
    "society": "Development & Societies",
    "housing": "Development & Societies",
    "housing society": "Development & Societies",
    "real estate": "Development & Societies",
    "development and societies": "Development & Societies",
    "banking": "Banking & Finance",
    "bank": "Banking & Finance",
    "banks": "Banking & Finance",
    "finance": "Banking & Finance",
    "financial": "Banking & Finance",
    "banking and finance": "Banking & Finance",
    "banking & finance": "Banking & Finance",
}

_PROVINCE_ALIASES = {
    "kpk": "Khyber Pakhtunkhwa",
    "kp": "Khyber Pakhtunkhwa",
    "khyber pakhtunkhwa": "Khyber Pakhtunkhwa",
    "ajk": "Azad Kashmir",
    "azad jammu and kashmir": "Azad Kashmir",
    "azad kashmir": "Azad Kashmir",
    "gb": "Gilgit-Baltistan",
    "gilgit baltistan": "Gilgit-Baltistan",
    "gilgit-baltistan": "Gilgit-Baltistan",
    "ict": "Islamabad",
    "islamabad": "Islamabad",
    "pakistan": "All Pakistan",
    "all pakistan": "All Pakistan",
    "federal": "All Pakistan",
    "punjab": "Punjab",
    "sindh": "Sindh",
    "balochistan": "Balochistan",
    "baluchistan": "Balochistan",
}


def normalize_sector(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if v in SECTORS:
        return v
    return _SECTOR_ALIASES.get(v.lower())


def normalize_province(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if v in PROVINCES:
        return v
    return _PROVINCE_ALIASES.get(v.lower())


_EDU_RULES = [
    ("MBBS/BDS", r"\b(mbbs|bds|doctor|pharm[\s-]?d|dpt)\b"),
    ("MPhil/PhD", r"\b(ph\.?d|m\.?phil|ms)\b"),
    ("Engineering", r"\b(engineer\w*|b\.?e|b\.?sc\.?\s*eng\w*)\b"),
    ("Master", r"\b(master\w*|m\.?a|m\.?sc|mba)\b"),
    ("Bachelor", r"\b(bachelor\w*|bs|b\.?a|b\.?sc|bba|1[46][\s-]?years?)\b"),
    ("Diploma", r"\b(diploma|dae)\b"),
    ("Intermediate", r"\b(intermediate|f\.?sc|f\.?a|hssc|12[\s-]?years?)\b"),
    ("Matric", r"\b(matric\w*|ssc|middle|primary|10[\s-]?years?|literate)\b"),
]


def normalize_education_level(value: str | None) -> str | None:
    """Map free text such as 'BS in CS / 16 years education' onto the facet vocabulary."""
    if not value:
        return None
    v = value.strip()
    if v in EDUCATION_LEVELS:
        return v
    low = v.lower()
    for level, pattern in _EDU_RULES:
        if re.search(pattern, low):
            return level
    return "Other"

