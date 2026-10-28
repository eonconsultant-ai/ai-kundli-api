"""AI Kundli reading.

The chart is always computed locally. Only derived placements, dashas and doshas
are sent to the language model: never the name, birth date/time or place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

from .gemini import generate_content

logger = logging.getLogger("jyotish.ai")

SIGN_LORDS = {
    "Aries": "mars",
    "Taurus": "venus",
    "Gemini": "mercury",
    "Cancer": "moon",
    "Leo": "sun",
    "Virgo": "mercury",
    "Libra": "venus",
    "Scorpio": "mars",
    "Sagittarius": "jupiter",
    "Capricorn": "saturn",
    "Aquarius": "saturn",
    "Pisces": "jupiter",
}

PLANET_LABELS = {
    "sun": "Sun",
    "moon": "Moon",
    "mars": "Mars",
    "mercury": "Mercury",
    "jupiter": "Jupiter",
    "venus": "Venus",
    "saturn": "Saturn",
    "rahu": "Rahu",
    "ketu": "Ketu",
}

PLANET_LABELS_HI = {
    "sun": "सूर्य",
    "moon": "चंद्र",
    "mars": "मंगल",
    "mercury": "बुध",
    "jupiter": "गुरु",
    "venus": "शुक्र",
    "saturn": "शनि",
    "rahu": "राहु",
    "ketu": "केतु",
}

PLANET_THEMES = {
    "sun": "identity, confidence, authority and visibility",
    "moon": "emotions, comfort, home and how you connect with people",
    "mars": "action, courage, competition and how you handle conflict",
    "mercury": "learning, communication, trade and adaptability",
    "jupiter": "growth, wisdom, teachers, opportunity and generosity",
    "venus": "relationships, creativity, comfort and money habits",
    "saturn": "discipline, responsibility, patience and long-term structure",
    "rahu": "ambition, unconventional paths, technology and restlessness",
    "ketu": "introspection, detachment, spirituality and letting go",
}

PLANET_THEMES_HI = {
    "sun": "आत्मविश्वास, पहचान और नेतृत्व",
    "moon": "भावनाएँ, घर और लोगों से जुड़ाव",
    "mars": "साहस, कर्म और टकराव से निपटने का तरीका",
    "mercury": "सीखना, संवाद और व्यवसाय",
    "jupiter": "विकास, ज्ञान, अवसर और उदारता",
    "venus": "रिश्ते, रचनात्मकता और खर्च की आदतें",
    "saturn": "अनुशासन, ज़िम्मेदारी, धैर्य और दीर्घकालिक निर्माण",
    "rahu": "महत्वाकांक्षा, नए रास्ते और बेचैनी",
    "ketu": "आत्मनिरीक्षण, वैराग्य और आध्यात्मिकता",
}

SIGN_THEMES = {
    "Aries": "direct, energetic and quick to act; patience is the growing edge",
    "Taurus": "steady, practical and loyal; change needs a gentle push",
    "Gemini": "curious, communicative and adaptable; focus is the growing edge",
    "Cancer": "caring, protective and memory-rich; boundaries matter",
    "Leo": "warm, expressive and proud; sharing the stage helps",
    "Virgo": "analytical, helpful and precise; self-criticism needs watching",
    "Libra": "fair, relational and diplomatic; decisions need a firm centre",
    "Scorpio": "intense, loyal and transformative; trust is the lesson",
    "Sagittarius": "optimistic, philosophical and adventurous; details matter",
    "Capricorn": "disciplined, ambitious and responsible; rest is part of duty",
    "Aquarius": "independent, original and community-minded; warmth matters",
    "Pisces": "empathetic, imaginative and spiritual; clear boundaries matter",
}

SIGN_THEMES_HI = {
    "Aries": "सीधे, ऊर्जावान और तेज़; धैर्य सीखने वाली बात है",
    "Taurus": "स्थिर, व्यावहारिक और निष्ठावान; बदलाव के लिए थोड़ा धक्का चाहिए",
    "Gemini": "जिज्ञासु, संवादप्रिय और लचीले; एकाग्रता पर काम करें",
    "Cancer": "दयालु, रक्षात्मक और भावनात्मक; सीमाएँ ज़रूरी हैं",
    "Leo": "गर्मजोश, अभिव्यक्तिपूर्ण और स्वाभिमानी; साथ मिलकर चलें",
    "Virgo": "विश्लेषणात्मक, सेवाभावी और सटीक; आत्म-आलोचना पर ध्यान दें",
    "Libra": "निष्पक्ष, संबंध-प्रधान और कूटनीतिक; निर्णय में दृढ़ता रखें",
    "Scorpio": "गहरे, निष्ठावान और रूपांतरकारी; भरोसा सीखने वाली बात है",
    "Sagittarius": "आशावादी, दार्शनिक और साहसी; बारीकियाँ महत्वपूर्ण हैं",
    "Capricorn": "अनुशासित, महत्वाकांक्षी और ज़िम्मेदार; विश्राम भी कर्तव्य है",
    "Aquarius": "स्वतंत्र, मौलिक और समुदाय-केंद्रित; गर्मजोशी रखें",
    "Pisces": "संवेदनशील, कल्पनाशील और आध्यात्मिक; स्पष्ट सीमाएँ रखें",
}

HOUSE_THEMES = {
    1: "self, body and first impressions",
    2: "family, speech and personal resources",
    3: "courage, communication and siblings",
    4: "home, mother and emotional security",
    5: "creativity, study and children",
    6: "health routines, service and daily challenges",
    7: "partnership and one-to-one commitments",
    8: "shared resources, change and inner depth",
    9: "beliefs, teachers and long journeys",
    10: "career, public role and responsibility",
    11: "gains, friends and community",
    12: "rest, spirituality and letting go",
}

HOUSE_THEMES_HI = {
    1: "स्वयं, शरीर और पहली छाप",
    2: "परिवार, वाणी और संसाधन",
    3: "साहस, संवाद और भाई-बहन",
    4: "घर, माता और भावनात्मक सुरक्षा",
    5: "रचनात्मकता, अध्ययन और संतान",
    6: "स्वास्थ्य दिनचर्या, सेवा और रोज़ की चुनौतियाँ",
    7: "साझेदारी और प्रतिबद्ध संबंध",
    8: "साझा संसाधन, बदलाव और आंतरिक गहराई",
    9: "मान्यता, गुरु और लंबी यात्राएँ",
    10: "करियर, सामाजिक भूमिका और ज़िम्मेदारी",
    11: "लाभ, मित्र और समुदाय",
    12: "विश्राम, आध्यात्मिकता और त्याग",
}

MANTRA = {
    "sun": "Om Suryaya Namah",
    "moon": "Om Chandraya Namah",
    "mars": "Om Mangalaya Namah",
    "mercury": "Om Budhaya Namah",
    "jupiter": "Om Gurave Namah",
    "venus": "Om Shukraya Namah",
    "saturn": "Om Shanaye Namah",
    "rahu": "Om Rahave Namah",
    "ketu": "Om Ketave Namah",
}

DANA = {
    "sun": "wheat, jaggery or a small donation on Sunday",
    "moon": "rice, milk or water on Monday",
    "mars": "red lentils or support for a sports or rescue cause on Tuesday",
    "mercury": "green gram or books for a student on Wednesday",
    "jupiter": "turmeric, chana dal or support for a teacher on Thursday",
    "venus": "rice, curd or support for an artist on Friday",
    "saturn": "black sesame, mustard oil or help for a worker on Saturday",
    "rahu": "food for a stray animal or support for a newcomer",
    "ketu": "simple food for a sadhu or a quiet service contribution",
}

DANA_HI = {
    "sun": "रविवार को गेहूँ, गुड़ या छोटा दान",
    "moon": "सोमवार को चावल, दूध या जल",
    "mars": "मंगलवार को मसूर या किसी खेल/बचाव कार्य में सहयोग",
    "mercury": "बुधवार को मूँग या किसी विद्यार्थी को पुस्तकें",
    "jupiter": "गुरुवार को हल्दी, चना दाल या शिक्षक को सहयोग",
    "venus": "शुक्रवार को चावल, दही या कलाकार को सहयोग",
    "saturn": "शनिवार को काले तिल, सरसों तेल या किसी श्रमिक की सहायता",
    "rahu": "किसी बेसहारा जीव को भोजन या नए व्यक्ति को सहयोग",
    "ketu": "सादा भोजन दान या शांत सेवा कार्य",
}

SIGN_HI = {
    "Aries": "मेष",
    "Taurus": "वृषभ",
    "Gemini": "मिथुन",
    "Cancer": "कर्क",
    "Leo": "सिंह",
    "Virgo": "कन्या",
    "Libra": "तुला",
    "Scorpio": "वृश्चिक",
    "Sagittarius": "धनु",
    "Capricorn": "मकर",
    "Aquarius": "कुंभ",
    "Pisces": "मीन",
}

NAKSHATRA_HI = {
    "Ashwini": "अश्विनी",
    "Bharani": "भरणी",
    "Krittika": "कृत्तिका",
    "Rohini": "रोहिणी",
    "Mrigashira": "मृगशिरा",
    "Ardra": "आर्द्रा",
    "Punarvasu": "पुनर्वसु",
    "Pushya": "पुष्य",
    "Ashlesha": "आश्लेषा",
    "Magha": "मघा",
    "Purva Phalguni": "पूर्व फाल्गुनी",
    "Uttara Phalguni": "उत्तर फाल्गुनी",
    "Hasta": "हस्त",
    "Chitra": "चित्रा",
    "Swati": "स्वाति",
    "Vishakha": "विशाखा",
    "Anuradha": "अनुराधा",
    "Jyeshtha": "ज्येष्ठा",
    "Mula": "मूल",
    "Purva Ashadha": "पूर्वाषाढ़ा",
    "Uttara Ashadha": "उत्तराषाढ़ा",
    "Shravana": "श्रवण",
    "Dhanishta": "धनिष्ठा",
    "Shatabhisha": "शतभिषा",
    "Purva Bhadrapada": "पूर्व भाद्रपद",
    "Uttara Bhadrapada": "उत्तर भाद्रपद",
    "Revati": "रेवती",
}

MANTRA_HI = {
    "sun": "ॐ सूर्याय नमः",
    "moon": "ॐ चन्द्राय नमः",
    "mars": "ॐ मंगलाय नमः",
    "mercury": "ॐ बुधाय नमः",
    "jupiter": "ॐ गुरवे नमः",
    "venus": "ॐ शुक्राय नमः",
    "saturn": "ॐ शनये नमः",
    "rahu": "ॐ राहवे नमः",
    "ketu": "ॐ केतवे नमः",
}

FOCUS_SECTION = {
    "life": "Life direction",
    "career": "Career and money",
    "relationships": "Relationships and home",
    "wellbeing": "Wellbeing and daily rhythm",
}

FOCUS_SECTION_HI = {
    "life": "जीवन की दिशा",
    "career": "करियर और धन",
    "relationships": "रिश्ते और घर",
    "wellbeing": "स्वास्थ्य और दिनचर्या",
}

DEFAULT_DISCLAIMER = (
    "This reading is traditional Vedic guidance, not a prediction or a substitute for "
    "medical, legal or financial advice. Remedies are optional cultural practices."
)

SYSTEM_PROMPT = """You are a careful Vedic astrology guide inside a mobile app.
Use only the chart facts supplied by the app. Never invent planets, dashas or doshas.

Hard rules:
- Frame everything as tendency and reflection, not certainty. Use words like "may", "tends to", "consider".
- Never predict death, serious illness, accidents, divorce, infertility or financial ruin.
- Never diagnose or treat health conditions, and never give medical, legal or financial instructions.
- Remedies must be free or low-cost cultural practices (mantra japa, charity, routine, journalling,
  breath awareness, service). Do not recommend gemstones, expensive rituals or fear-based urgency.
- Do not mention the user's name, birth date, birth time or birthplace; you do not receive them.
- Respect the requested language exactly.
- Return only valid JSON matching the requested shape. No markdown fences.

The JSON shape:
{
  "headline": "one warm sentence, max 14 words",
  "overview": "2-3 sentences tying the Lagna, Moon and current dasha together",
  "sections": [
    {"title": "Core nature", "body": "70-100 words"},
    {"title": "Focus area", "body": "70-100 words"},
    {"title": "Current period", "body": "60-90 words"},
    {"title": "Relationships and home", "body": "60-90 words"}
  ],
  "remedies": [
    {"title": "short name", "practice": "what to do, when and how often", "why": "which chart factor it supports"}
  ],
  "affirmation": "one practical sentence the person can act on today"
}
Write 3 remedies. Keep the whole reading under 500 words. Do not include a disclaimer; the app adds it."""


_reading_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def build_facts(kundli: dict[str, Any], focus: str) -> dict[str, Any]:
    planets = {planet["key"]: planet for planet in kundli["planets"]}
    houses = {house["house"]: house for house in kundli["houses"]}
    lagna = kundli["lagna"]
    lagna_lord = SIGN_LORDS.get(lagna["sign"], "jupiter")
    lord = planets.get(lagna_lord, {})
    path = kundli["dashas"]["current"]["path"]
    mahadasha = path[0] if path else {}
    antardasha = path[1] if len(path) > 1 else {}
    moon = kundli["moon_sign"]
    moon_planet = planets["moon"]
    seventh = houses.get(7, {})
    tenth = houses.get(10, {})

    return {
        "lagna": {
            "sign": lagna["sign"],
            "nakshatra": lagna["nakshatra"],
            "pada": lagna["pada"],
            "lord": PLANET_LABELS[lagna_lord],
            "lord_house": lord.get("house"),
            "lord_sign": lord.get("sign"),
        },
        "moon": {
            "sign": moon["sign"],
            "nakshatra": moon["nakshatra"],
            "pada": moon["pada"],
            "nakshatra_lord": PLANET_LABELS.get(moon_planet.get("nakshatra_lord"), ""),
            "house": moon_planet.get("house"),
        },
        "sun": {
            "sign": kundli["sun_sign"]["sign"],
            "house": planets["sun"].get("house"),
        },
        "seventh_house": seventh.get("sign"),
        "tenth_house": tenth.get("sign"),
        "fifth_house": houses.get(5, {}).get("sign"),
        "planets": [
            {
                "planet": planet["name"],
                "sign": planet["sign"],
                "house": planet["house"],
                "retrograde": planet["retrograde"],
                "combust": planet["combust"],
                "nakshatra": planet["nakshatra"],
            }
            for planet in kundli["planets"]
        ],
        "dasha": {
            "mahadasha": PLANET_LABELS.get(mahadasha.get("lord", ""), ""),
            "mahadasha_ends": mahadasha.get("end", "")[:10],
            "antardasha": PLANET_LABELS.get(antardasha.get("lord", ""), ""),
        },
        "mangal_dosha": {
            "is_manglik": kundli["mangal_dosha"]["is_manglik"],
            "from": kundli["mangal_dosha"]["active_from"],
        },
        "sade_sati": {
            "active": kundli["transits"]["sade_sati"]["active"],
            "phase": kundli["transits"]["sade_sati"].get("phase"),
        },
        "vargottama": kundli.get("vargottama", []),
        "panchang": {
            "tithi": kundli["panchang_at_birth"]["tithi"]["name"],
            "vara": kundli["panchang_at_birth"]["vara"]["name"],
            "nakshatra": kundli["panchang_at_birth"]["nakshatra"]["name"],
        },
        "focus": focus,
    }


def _cache_key(facts: dict[str, Any], language: str) -> str:
    payload = json.dumps({"facts": facts, "language": language}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_cached(key: str, ttl: int) -> dict[str, Any] | None:
    now = time.monotonic()
    with _cache_lock:
        entry = _reading_cache.get(key)
        if entry is None:
            return None
        expires, reading = entry
        if expires <= now:
            _reading_cache.pop(key, None)
            return None
        return reading


def _put_cached(key: str, reading: dict[str, Any], ttl: int, max_entries: int) -> None:
    with _cache_lock:
        if len(_reading_cache) >= max_entries:
            oldest = min(_reading_cache, key=lambda k: _reading_cache[k][0])
            _reading_cache.pop(oldest, None)
        _reading_cache[key] = (time.monotonic() + ttl, reading)


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_reading(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    section_rows = payload.get("sections")
    remedy_rows = payload.get("remedies")
    if not isinstance(section_rows, list) or not isinstance(remedy_rows, list):
        return None

    sections = []
    for row in section_rows[:5]:
        if not isinstance(row, dict):
            continue
        title = _clip(row.get("title"), 80)
        body = _clip(row.get("body"), 1600)
        if title and body:
            sections.append({"title": title, "body": body})

    remedies = []
    for row in remedy_rows[:4]:
        if not isinstance(row, dict):
            continue
        title = _clip(row.get("title"), 80)
        practice = _clip(row.get("practice"), 300)
        why = _clip(row.get("why"), 300)
        if title and practice:
            remedies.append({"title": title, "practice": practice, "why": why})

    headline = _clip(payload.get("headline"), 140)
    overview = _clip(payload.get("overview"), 1200)
    affirmation = _clip(payload.get("affirmation"), 300)
    if len(sections) < 3 or not remedies or not overview:
        return None

    return {
        "headline": headline,
        "overview": overview,
        "sections": sections,
        "remedies": remedies,
        "affirmation": affirmation,
    }


def _gemini_reading(
    settings: Settings,
    facts: dict[str, Any],
    language: str,
    daily: bool,
) -> tuple[dict[str, Any], str] | None:
    if not settings.gemini_keys:
        return None

    focus = facts.get("focus", "life")
    language_name = "Hindi" if language == "hi" else "English"
    prompt = {
        "language": language_name,
        "focus": focus,
        "daily_step": daily,
        "chart_facts": facts,
        "section_titles": (
            [
                "मूल स्वभाव",
                FOCUS_SECTION_HI[focus],
                "वर्तमान काल",
                "करियर और दिशा" if focus == "relationships" else "रिश्ते और घर",
            ]
            if language == "hi"
            else [
                "Core nature",
                FOCUS_SECTION[focus],
                "Current period",
                "Work and direction" if focus == "relationships" else "Relationships and home",
            ]
        ),
    }

    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.65,
            "topP": 0.9,
            "maxOutputTokens": 1800,
            "responseMimeType": "application/json",
        },
    }
    result = generate_content(settings, body)
    if result is None:
        return None

    data, model = result
    try:
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content", {}).get("parts") if candidates else None) or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        reading = _clean_reading(json.loads(text))
        if reading is None:
            logger.warning("Gemini returned an unusable reading")
            return None
        return reading, model
    except Exception as exc:  # noqa: BLE001 - any AI failure must fall back
        logger.warning("Gemini reading failed: %s", exc)
        return None


def _planet_in(planet: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    for row in facts["planets"]:
        if row["planet"].lower() == PLANET_LABELS[planet].lower():
            return row
    return None


def _theme_parts(theme: str) -> tuple[str, str]:
    main, _, caveat = theme.partition(";")
    return main.strip(), caveat.strip()


def _fallback_reading(
    facts: dict[str, Any],
    language: str,
    daily: bool,
) -> dict[str, Any]:
    hindi = language == "hi"
    focus = facts["focus"]
    lagna = facts["lagna"]
    lord = lagna["lord"].lower()
    lord_house = lagna.get("lord_house") or 1
    moon = facts["moon"]
    dasha = facts["dasha"]
    md = str(dasha.get("mahadasha") or "").lower() or "saturn"
    ad = str(dasha.get("antardasha") or "").lower() or md
    seventh = facts.get("seventh_house") or "Libra"
    tenth = facts.get("tenth_house") or "Capricorn"

    sign_theme = SIGN_THEMES_HI.get(lagna["sign"], "") if hindi else SIGN_THEMES.get(lagna["sign"], "")
    moon_theme = SIGN_THEMES_HI.get(moon["sign"], "") if hindi else SIGN_THEMES.get(moon["sign"], "")
    md_theme = PLANET_THEMES_HI.get(md, "") if hindi else PLANET_THEMES.get(md, "")
    lord_house_theme = HOUSE_THEMES_HI.get(lord_house, "") if hindi else HOUSE_THEMES.get(lord_house, "")
    seventh_theme = SIGN_THEMES_HI.get(seventh, "") if hindi else SIGN_THEMES.get(seventh, "")
    tenth_theme = SIGN_THEMES_HI.get(tenth, "") if hindi else SIGN_THEMES.get(tenth, "")

    if hindi:
        lagna_name = SIGN_HI.get(lagna["sign"], lagna["sign"])
        moon_name = SIGN_HI.get(moon["sign"], moon["sign"])
        seventh_name = SIGN_HI.get(seventh, seventh)
        tenth_name = SIGN_HI.get(tenth, tenth)
        lord_label = PLANET_LABELS_HI.get(lord, "")
        md_label = PLANET_LABELS_HI.get(md, "")
        ad_label = PLANET_LABELS_HI.get(ad, "")

        headline = f"{lagna_name} लग्न, {moon_name} चंद्र राशि और {md_label} महादशा"
        overview = (
            f"आपका लग्न {lagna_name} है और लग्नेश {lord_label} {lord_house} भाव में है, "
            f"इसलिए {lord_house_theme} जीवन का केंद्र बनते हैं। "
            f"चंद्र {moon_name} राशि और {NAKSHATRA_HI.get(moon['nakshatra'], moon['nakshatra'])} नक्षत्र में है। "
            f"अभी {md_label} महादशा चल रही है।"
        )
        core = (
            f"आपके {lagna_name} लग्न का स्वभाव: {sign_theme}। "
            f"लग्नेश {lord_label} {lord_house} भाव में है, इसलिए {lord_house_theme} पर स्वाभाविक ध्यान रहता है। "
            f"चंद्र {moon_name} में है — {moon_theme}। "
            "अपनी गति और विश्राम के बीच संतुलन रखें।"
        )
        focus_body = {
            "life": (
                f"आपकी दिशा {tenth_name} दशम भाव से बनती है। इसके विषय: {tenth_theme}। "
                "जो काम इन गुणों का उपयोग करे, वह अधिक सहज लगता है। "
                "बड़े बदलाव चरणों में करें और हर चरण में एक ठोस आदत जोड़ें।"
            ),
            "career": (
                f"दशम भाव {tenth_name} है, जिसके विषय: {tenth_theme}। "
                f"लग्नेश {lord_house} भाव में है, इसलिए {lord_house_theme} से जुड़े अवसर मदद कर सकते हैं। "
                "धन के फैसले लिखित योजना और योग्य सलाह के बाद लें।"
            ),
            "relationships": (
                f"सप्तम भाव {seventh_name} है। साथी के साथ इन विषयों की झलक दिख सकती है: {seventh_theme}। "
                "स्पष्ट संवाद और सीमाएँ रिश्ता मजबूत रखती हैं।"
            ),
            "wellbeing": (
                "स्वास्थ्य के लिए नींद, भोजन और गति का नियम सबसे भरोसेमंद है। "
                f"चंद्र {moon_name} में है — {moon_theme}। "
                "थकान को संकेत मानें और विश्राम को योजना में रखें।"
            ),
        }[focus]
        current = (
            (
                f"अभी {md_label} महादशा और उसी ग्रह की अंतर्दशा चल रही है, "
                f"इसलिए {md_theme} पर विशेष ध्यान दें। "
                if ad == md
                else f"अभी {md_label} महादशा में {md_theme} प्रमुख है, "
                f"और {ad_label} अंतर्दशा में इसे रोज़मर्रा के फैसलों में उतारने का समय है। "
            )
            + (
                "साढ़े साती सक्रिय है; धैर्य, नियम और सेवा इस अवधि में सहायक माने जाते हैं।"
                if facts["sade_sati"]["active"]
                else "गोचर शनि इस समय साढ़े साती सक्रिय नहीं दिखाता।"
            )
            + " महत्वपूर्ण निर्णय जल्दबाज़ी में न लें।"
        )
        if focus == "relationships":
            fourth_title = "करियर और दिशा"
            fourth = (
                f"दशम भाव {tenth_name} है, इसके विषय: {tenth_theme}। "
                f"लग्नेश {lord_house} भाव में है, इसलिए {lord_house_theme} से जुड़े काम प्राथमिकता ले सकते हैं। "
                "काम और घर के बीच स्पष्ट समय-सीमा रखें।"
            )
        else:
            fourth_title = "रिश्ते और घर"
            fourth = (
                f"सप्तम भाव {seventh_name} है, इसके विषय: {seventh_theme}। "
                f"लग्नेश {lord_house} भाव में है, इसलिए घर और परिवार से जुड़े फैसले महत्वपूर्ण रहते हैं। "
                + (
                    "मंगल दोष सक्रिय है; संवाद में धैर्य रखें और दोष भंग नियम किसी योग्य ज्योतिषी से जाँचें।"
                    if facts["mangal_dosha"]["is_manglik"]
                    else "जन्म कुंडली में मंगल दोष सक्रिय नहीं दिखता।"
                )
            )
        affirmation = (
            "आज एक छोटा काम पूरा करें और दिन के अंत में आभार लिखें।"
            if not daily
            else "आज 10 मिनट शांत बैठकर साँस पर ध्यान दें और एक ज़रूरी काम पूरा करें।"
        )
        remedies = [
            {
                "title": f"{lord_label} मंत्र",
                "practice": f"{MANTRA_HI.get(lord, 'ॐ नमः शिवाय')} का 11 बार जाप सप्ताह में पाँच दिन करें।",
                "why": f"लग्नेश {lord_label} {lord_house} भाव में है।",
            },
            {
                "title": f"{md_label} दान",
                "practice": f"{DANA_HI.get(md, 'सादा भोजन दान')} — महीने में एक बार।",
                "why": "वर्तमान महादशा के ग्रह को संतुलित करने का पारंपरिक उपाय।",
            },
            {
                "title": "दिनचर्या और सेवा",
                "practice": "रोज़ 10 मिनट टहलें और सप्ताह में एक घंटा किसी की निःस्वार्थ सहायता करें।",
                "why": "मन और शरीर को स्थिर रखने का व्यावहारिक अभ्यास।",
            },
        ]
    else:
        headline = f"{lagna['sign']} Lagna, {moon['sign']} Moon and a {PLANET_LABELS.get(md, '')} Mahadasha"
        overview = (
            f"Your Lagna is {lagna['sign']} and its lord {PLANET_LABELS.get(lord, '')} sits in "
            f"house {lord_house}, making {lord_house_theme} a central theme. "
            f"The Moon is in {moon['sign']} and {moon['nakshatra']}. "
            f"You are in a {PLANET_LABELS.get(md, '')} Mahadasha."
        )
        sign_main, sign_caveat = _theme_parts(sign_theme)
        moon_main, moon_caveat = _theme_parts(moon_theme)
        core = (
            f"{lagna['sign']} rising tends to be {sign_main}; {sign_caveat}. "
            f"With the Lagna lord in house {lord_house}, {lord_house_theme} naturally draw your attention. "
            f"The Moon in {moon['sign']} brings {moon_main} energy; {moon_caveat}. "
            "Balance momentum with rest rather than pushing through fatigue."
        )
        focus_body = {
            "life": (
                f"Your direction is shaped by the {tenth} tenth house. Its themes are {tenth_theme}. "
                "Work that uses these strengths tends to feel more natural. "
                "Make large changes in stages and attach one steady habit to each stage."
            ),
            "career": (
                f"The tenth house is {tenth}, with themes of {tenth_theme}. "
                f"With the Lagna lord in house {lord_house}, opportunities linked to {lord_house_theme} can help. "
                "Take money decisions with a written plan and qualified advice."
            ),
            "relationships": (
                f"The seventh house is {seventh}. Partnerships may carry these themes: {seventh_theme}. "
                "Venus colours how you value closeness, so clear expectations and regular conversation matter."
            ),
            "wellbeing": (
                "Sleep, food and movement are the most reliable supports for your energy. "
                "Treat tiredness as information and schedule recovery rather than pushing through. "
                "A fixed bedtime and a short daily walk usually help more than occasional intense effort."
            ),
        }[focus]
        current = (
            f"The {PLANET_LABELS.get(md, '')} Mahadasha highlights {md_theme}. "
            + (
                "The Antardasha runs under the same planet, so this theme is doubled: keep routines simple. "
                if ad == md
                else f"The {PLANET_LABELS.get(ad, '')} Antardasha turns that theme into daily practice. "
            )
            + (
                "Sade Sati is active; patience, routine and service are traditionally encouraged."
                if facts["sade_sati"]["active"]
                else "Saturn's transit does not show Sade Sati at this time."
            )
            + " Avoid rushing decisions that need time to mature."
        )
        if focus == "relationships":
            fourth_title = "Work and direction"
            fourth = (
                f"The tenth house is {tenth}, with themes of {tenth_theme}. "
                f"With the Lagna lord in house {lord_house}, work linked to {lord_house_theme} may take priority. "
                "Keep clear time boundaries between work and home."
            )
        else:
            fourth_title = "Relationships and home"
            fourth = (
                f"The seventh house is {seventh}. Partnership may carry these themes: {seventh_theme}. "
                f"With the Lagna lord in house {lord_house}, home and family choices matter. "
                + (
                    "Mangal Dosha is active; keep conversations patient and have cancellation "
                    "rules checked by a qualified astrologer."
                    if facts["mangal_dosha"]["is_manglik"]
                    else "Mangal Dosha is not active in this chart."
                )
            )
        affirmation = (
            "Finish one small task today and write down one thing you are grateful for."
            if not daily
            else "Take ten quiet minutes for your breath, then complete one important task."
        )
        remedies = [
            {
                "title": f"{PLANET_LABELS.get(lord, '')} mantra",
                "practice": f"Chant {MANTRA.get(lord, 'Om Namah Shivaya')} 11 times on five days a week.",
                "why": f"Your Lagna lord {PLANET_LABELS.get(lord, '')} is in house {lord_house}.",
            },
            {
                "title": f"{PLANET_LABELS.get(md, '')} charity",
                "practice": f"Offer {DANA.get(md, 'simple food')} once a month.",
                "why": "A traditional way to work with the current Mahadasha lord.",
            },
            {
                "title": "Routine and service",
                "practice": "Walk for ten minutes daily and give one hour of selfless help each week.",
                "why": "A practical grounding practice for the mind and body.",
            },
        ]

    return {
        "headline": headline,
        "overview": overview,
        "sections": [
            {"title": "मूल स्वभाव" if hindi else "Core nature", "body": core},
            {"title": FOCUS_SECTION_HI[focus] if hindi else FOCUS_SECTION[focus], "body": focus_body},
            {"title": "वर्तमान काल" if hindi else "Current period", "body": current},
            {"title": fourth_title, "body": fourth},
        ],
        "remedies": remedies,
        "affirmation": affirmation,
    }


def generate_reading(
    settings: Settings,
    kundli: dict[str, Any],
    *,
    focus: str,
    language: str,
    daily: bool = False,
    use_provider: bool = True,
) -> dict[str, Any]:
    facts = build_facts(kundli, focus)
    key = _cache_key(facts, language)

    cached = _get_cached(key, settings.ai_cache_ttl_seconds)
    if cached is not None:
        return {**cached, "cached": True}

    ai_result = _gemini_reading(settings, facts, language, daily) if use_provider else None
    if ai_result is not None:
        reading, model = ai_result
        source = "gemini"
    else:
        reading = _fallback_reading(facts, language, daily)
        model = None
        source = "chart"

    result = {
        "source": source,
        "model": model,
        "language": language,
        "focus": focus,
        "headline": reading["headline"],
        "overview": reading["overview"],
        "sections": reading["sections"],
        "remedies": reading["remedies"],
        "affirmation": reading["affirmation"],
        "disclaimer": DEFAULT_DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy": (
            "Only placements, dashas and doshas from your chart were used. "
            "Your name, birth date, birth time and place were not sent to the AI service."
        ),
    }
    if source == "gemini":
        _put_cached(key, result, settings.ai_cache_ttl_seconds, settings.ai_cache_max_entries)
    return {**result, "cached": False}


def ai_status(settings: Settings) -> dict[str, Any]:
    gemini = bool(settings.gemini_keys)
    groq = bool(settings.groq_keys)
    if gemini:
        provider = "gemini"
    elif groq:
        provider = "groq"
    else:
        provider = "none"
    return {
        "ai_configured": bool(settings.text_provider_configured),
        "model": settings.gemini_model if gemini else None,
        "fallback_models": settings.gemini_models[1:] if gemini else [],
        "keys": len(settings.gemini_keys),
        "provider": provider,
        # Chat falls back to Groq after Gemini; readings and voice are Gemini-only.
        "chat_fallback_provider": "groq" if groq else None,
        "free_daily_messages": settings.ai_free_daily_messages,
        "plus_daily_messages": settings.ai_plus_daily_messages,
        "free_daily_grounded_messages": settings.ai_free_grounded_messages,
    }
