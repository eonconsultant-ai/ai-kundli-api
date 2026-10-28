"""Static tables used by the Vedic calculation engine."""

from __future__ import annotations

SIGNS: tuple[dict[str, str], ...] = (
    {"name": "Aries", "sanskrit": "Mesha"},
    {"name": "Taurus", "sanskrit": "Vrishabha"},
    {"name": "Gemini", "sanskrit": "Mithuna"},
    {"name": "Cancer", "sanskrit": "Karka"},
    {"name": "Leo", "sanskrit": "Simha"},
    {"name": "Virgo", "sanskrit": "Kanya"},
    {"name": "Libra", "sanskrit": "Tula"},
    {"name": "Scorpio", "sanskrit": "Vrischika"},
    {"name": "Sagittarius", "sanskrit": "Dhanu"},
    {"name": "Capricorn", "sanskrit": "Makara"},
    {"name": "Aquarius", "sanskrit": "Kumbha"},
    {"name": "Pisces", "sanskrit": "Meena"},
)

# Element / modality are needed by several compatibility and strength rules.
SIGN_ELEMENTS: tuple[str, ...] = (
    "fire",
    "earth",
    "air",
    "water",
    "fire",
    "earth",
    "air",
    "water",
    "fire",
    "earth",
    "air",
    "water",
)
SIGN_MODALITIES: tuple[str, ...] = (
    "movable",
    "fixed",
    "dual",
    "movable",
    "fixed",
    "dual",
    "movable",
    "fixed",
    "dual",
    "movable",
    "fixed",
    "dual",
)

NAKSHATRAS: tuple[dict[str, object], ...] = (
    {"name": "Ashwini", "lord": "ketu", "gana": "deva", "yoni": "horse", "nadi": "adi"},
    {"name": "Bharani", "lord": "venus", "gana": "manushya", "yoni": "elephant", "nadi": "madhya"},
    {"name": "Krittika", "lord": "sun", "gana": "rakshasa", "yoni": "sheep", "nadi": "antya"},
    {"name": "Rohini", "lord": "moon", "gana": "manushya", "yoni": "serpent", "nadi": "antya"},
    {"name": "Mrigashira", "lord": "mars", "gana": "deva", "yoni": "serpent", "nadi": "madhya"},
    {"name": "Ardra", "lord": "rahu", "gana": "manushya", "yoni": "dog", "nadi": "adi"},
    {"name": "Punarvasu", "lord": "jupiter", "gana": "deva", "yoni": "cat", "nadi": "adi"},
    {"name": "Pushya", "lord": "saturn", "gana": "deva", "yoni": "sheep", "nadi": "madhya"},
    {"name": "Ashlesha", "lord": "mercury", "gana": "rakshasa", "yoni": "cat", "nadi": "antya"},
    {"name": "Magha", "lord": "ketu", "gana": "rakshasa", "yoni": "rat", "nadi": "antya"},
    {"name": "Purva Phalguni", "lord": "venus", "gana": "manushya", "yoni": "rat", "nadi": "madhya"},
    {"name": "Uttara Phalguni", "lord": "sun", "gana": "manushya", "yoni": "cow", "nadi": "adi"},
    {"name": "Hasta", "lord": "moon", "gana": "deva", "yoni": "buffalo", "nadi": "adi"},
    {"name": "Chitra", "lord": "mars", "gana": "rakshasa", "yoni": "tiger", "nadi": "madhya"},
    {"name": "Swati", "lord": "rahu", "gana": "deva", "yoni": "buffalo", "nadi": "antya"},
    {"name": "Vishakha", "lord": "jupiter", "gana": "rakshasa", "yoni": "tiger", "nadi": "antya"},
    {"name": "Anuradha", "lord": "saturn", "gana": "deva", "yoni": "deer", "nadi": "madhya"},
    {"name": "Jyeshtha", "lord": "mercury", "gana": "rakshasa", "yoni": "deer", "nadi": "adi"},
    {"name": "Mula", "lord": "ketu", "gana": "rakshasa", "yoni": "dog", "nadi": "adi"},
    {"name": "Purva Ashadha", "lord": "venus", "gana": "manushya", "yoni": "monkey", "nadi": "madhya"},
    {"name": "Uttara Ashadha", "lord": "sun", "gana": "manushya", "yoni": "mongoose", "nadi": "antya"},
    {"name": "Shravana", "lord": "moon", "gana": "deva", "yoni": "monkey", "nadi": "antya"},
    {"name": "Dhanishta", "lord": "mars", "gana": "rakshasa", "yoni": "lion", "nadi": "madhya"},
    {"name": "Shatabhisha", "lord": "rahu", "gana": "rakshasa", "yoni": "horse", "nadi": "adi"},
    {"name": "Purva Bhadrapada", "lord": "jupiter", "gana": "manushya", "yoni": "lion", "nadi": "adi"},
    {"name": "Uttara Bhadrapada", "lord": "saturn", "gana": "manushya", "yoni": "cow", "nadi": "madhya"},
    {"name": "Revati", "lord": "mercury", "gana": "deva", "yoni": "elephant", "nadi": "antya"},
)

NAKSHATRA_SPAN = 360 / 27
PADA_SPAN = NAKSHATRA_SPAN / 4

DASHA_SEQUENCE: tuple[str, ...] = (
    "ketu",
    "venus",
    "sun",
    "moon",
    "mars",
    "rahu",
    "jupiter",
    "saturn",
    "mercury",
)
DASHA_YEARS: dict[str, float] = {
    "ketu": 7,
    "venus": 20,
    "sun": 6,
    "moon": 10,
    "mars": 7,
    "rahu": 18,
    "jupiter": 16,
    "saturn": 19,
    "mercury": 17,
}
DASHA_TOTAL_YEARS = 120
# Most modern software uses the tropical year for Vimshottari date arithmetic.
# Some lineages use 360-day savana years; expose the constant so it can be audited.
DASHA_YEAR_DAYS = 365.2425

PLANET_META: dict[str, dict[str, str]] = {
    "sun": {"name": "Sun", "sanskrit": "Surya"},
    "moon": {"name": "Moon", "sanskrit": "Chandra"},
    "mars": {"name": "Mars", "sanskrit": "Mangala"},
    "mercury": {"name": "Mercury", "sanskrit": "Budha"},
    "jupiter": {"name": "Jupiter", "sanskrit": "Guru"},
    "venus": {"name": "Venus", "sanskrit": "Shukra"},
    "saturn": {"name": "Saturn", "sanskrit": "Shani"},
    "rahu": {"name": "Rahu", "sanskrit": "Rahu"},
    "ketu": {"name": "Ketu", "sanskrit": "Ketu"},
}

PLANET_ORDER: tuple[str, ...] = (
    "sun",
    "moon",
    "mars",
    "mercury",
    "jupiter",
    "venus",
    "saturn",
    "rahu",
    "ketu",
)

# Surya Siddhanta-style combustion orbs in degrees. Mercury and Venus use a
# narrower orb when retrograde. Schools differ; keep this table explicit.
COMBUSTION_ORBS: dict[str, tuple[float, float]] = {
    "moon": (12, 12),
    "mars": (17, 17),
    "mercury": (14, 12),
    "jupiter": (11, 11),
    "venus": (10, 8),
    "saturn": (15, 15),
}

WEEKDAYS: tuple[dict[str, str], ...] = (
    {"name": "Sunday", "sanskrit": "Ravivara", "short": "Sun"},
    {"name": "Monday", "sanskrit": "Somavara", "short": "Mon"},
    {"name": "Tuesday", "sanskrit": "Mangalavara", "short": "Tue"},
    {"name": "Wednesday", "sanskrit": "Budhavara", "short": "Wed"},
    {"name": "Thursday", "sanskrit": "Guruvara", "short": "Thu"},
    {"name": "Friday", "sanskrit": "Shukravara", "short": "Fri"},
    {"name": "Saturday", "sanskrit": "Shanivara", "short": "Sat"},
)

TITHI_NAMES: tuple[str, ...] = (
    "Pratipada",
    "Dwitiya",
    "Tritiya",
    "Chaturthi",
    "Panchami",
    "Shashthi",
    "Saptami",
    "Ashtami",
    "Navami",
    "Dashami",
    "Ekadashi",
    "Dwadashi",
    "Trayodashi",
    "Chaturdashi",
    "Purnima",
)

YOGA_NAMES: tuple[str, ...] = (
    "Vishkambha",
    "Priti",
    "Ayushman",
    "Saubhagya",
    "Shobhana",
    "Atiganda",
    "Sukarman",
    "Dhriti",
    "Shula",
    "Ganda",
    "Vriddhi",
    "Dhruva",
    "Vyaghata",
    "Harshana",
    "Vajra",
    "Siddhi",
    "Vyatipata",
    "Variyana",
    "Parigha",
    "Shiva",
    "Siddha",
    "Sadhya",
    "Shubha",
    "Shukla",
    "Brahma",
    "Indra",
    "Vaidhriti",
)

KARANA_MOVABLE: tuple[str, ...] = (
    "Bava",
    "Balava",
    "Kaulava",
    "Taitila",
    "Gara",
    "Vanija",
    "Vishti",
)

# 1-based segment of the daytime that is inauspicious for each weekday.
# Weekday index follows Python's Sunday = 0 convention.
RAHU_SEGMENT: tuple[int, ...] = (8, 2, 7, 5, 6, 4, 3)
YAMAGANDA_SEGMENT: tuple[int, ...] = (5, 4, 3, 2, 1, 7, 6)
GULIKA_SEGMENT: tuple[int, ...] = (7, 6, 5, 4, 3, 2, 1)

VARGA_DIVISIONS: dict[str, int] = {
    "D1": 1,
    "D3": 3,
    "D7": 7,
    "D9": 9,
    "D10": 10,
    "D12": 12,
}

VARGA_NAMES: dict[str, str] = {
    "D1": "Rasi",
    "D3": "Drekkana",
    "D7": "Saptamsa",
    "D9": "Navamsa",
    "D10": "Dasamsa",
    "D12": "Dwadasamsa",
}
