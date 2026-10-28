"""Conversational Vedic astrology guide.

The chart is computed locally. The model receives derived placements and the
messages the user typed; never the name, birth date/time or birthplace.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.schemas.ai import ChatMessage

from .gemini import generate_content
from .groq import chat_completion
from .reading import (
    DANA,
    DANA_HI,
    DEFAULT_DISCLAIMER,
    HOUSE_THEMES,
    HOUSE_THEMES_HI,
    MANTRA,
    MANTRA_HI,
    NAKSHATRA_HI,
    PLANET_LABELS,
    PLANET_LABELS_HI,
    PLANET_THEMES,
    PLANET_THEMES_HI,
    SIGN_HI,
    SIGN_THEMES,
    SIGN_THEMES_HI,
    build_facts,
)

logger = logging.getLogger("jyotish.ai.chat")

CHAT_PRIVACY = (
    "Your birth details stay on the Kundli server. Only chart placements, dashas and "
    "the messages you type are sent to the AI service."
)

CHAT_SYSTEM = """You are "AI Panditji" (AI Jyotish), a warm and careful Vedic astrology guide inside a mobile app.
The app computed the chart and gives you verified facts. Use only those facts.

Hard rules:
- Speak as a dharma guide, not a fortune teller. Present every suggestion as dharma:
  duty, right conduct, patience, service and steady practice. Ask or imply "what is
  the dharmic response here?" rather than "what will happen to you?".
- Frame everything as tendency and reflection, not certainty. Use words like "may", "tends to", "consider".
- Never predict death, serious illness, accidents, divorce, infertility or financial ruin.
- Never diagnose or treat health conditions. Never give medical, legal or financial
  instructions; suggest a qualified professional for those.
- Remedies must be free or low-cost cultural practices (mantra japa, charity, routine,
  journalling, breath work, service). No gemstones, expensive rituals or fear.
- Never mention the user's name, birth date, birth time or birthplace; you do not receive them.
- Reply in the language and script of the user's latest message: English, Hindi in
  Devanagari, or Hinglish (Roman-script Hindi mixed with English). If the latest
  message is too short to tell, use the requested app language.
- The app already greeted the user with "Hari OM" in the opening message. Never say
  "Hari OM" again in a reply.
- When web search is available, use it only for general Vedic context and free
  traditional remedies that enrich the verified facts. Ignore paid rituals, gemstone
  sales, fear-based claims and anything outside free cultural practice. If a search
  result conflicts with the verified facts, follow the facts.
- Reply in plain conversational text. No markdown, no headings, no tables.
- Keep each reply between 70 and 140 words. Be specific to the chart facts.
- End with one small practical step or one gentle follow-up question.
- If the question is not about astrology, life or the chart, briefly bring it back to the chart.
"""

TOPICS = {
    "remedies": (
        "remedy", "remedies", "mantra", "upay", "puja", "dan", "daan", "gemstone",
        "उपाय", "मंत्र", "पूजा", "दान", "रत्न",
    ),
    "career": (
        "career", "job", "work", "business", "promotion", "profession", "salary",
        "करियर", "नौकरी", "काम", "व्यवसाय", "प्रमोशन", "नौकरी",
    ),
    "marriage": (
        "marriage", "married", "partner", "relationship", "love", "spouse", "wife",
        "husband", "shaadi", "vivah", "शादी", "विवाह", "रिश्ते", "पति", "पत्नी", "प्रेम",
    ),
    "money": (
        "money", "finance", "financial", "wealth", "loan", "savings", "income", "debt",
        "धन", "पैसा", "आर्थिक", "कर्ज", "बचत", "आय",
    ),
    "health": (
        "health", "illness", "disease", "sleep", "stress", "anxiety", "energy",
        "स्वास्थ्य", "बीमारी", "नींद", "तनाव", "ऊर्जा",
    ),
    "education": (
        "study", "education", "exam", "college", "learning", "degree",
        "पढ़ाई", "शिक्षा", "परीक्षा", "अध्ययन",
    ),
    "mangal": ("mangal", "manglik", "mars dosha", "मांगलिक", "मंगल दोष"),
    "dasha": (
        "dasha", "mahadasha", "antardasha", "sade sati", "period", "transit",
        "दशा", "महादशा", "अंतर्दशा", "साढ़े साती", "गोचर",
    ),
}


def _topic(text: str) -> str:
    lowered = text.lower()
    for topic, words in TOPICS.items():
        if any(word in lowered for word in words):
            return topic
    return "general"


def _theme(theme: str) -> tuple[str, str]:
    main, _, caveat = theme.partition(";")
    return main.strip(), caveat.strip()


def _fallback_reply(facts: dict[str, Any], language: str, question: str) -> str:
    hindi = language == "hi"
    topic = _topic(question)
    lagna = facts["lagna"]
    moon = facts["moon"]
    dasha = facts["dasha"]
    md = str(dasha.get("mahadasha") or "saturn").lower()
    ad = str(dasha.get("antardasha") or "").lower()
    lord = lagna["lord"].lower()
    lord_house = lagna.get("lord_house") or 1
    seventh = facts.get("seventh_house") or "Libra"
    tenth = facts.get("tenth_house") or "Capricorn"
    fifth = facts.get("fifth_house") or "Leo"
    manglik = facts["mangal_dosha"]["is_manglik"]
    sade_sati = facts["sade_sati"]["active"]

    if hindi:
        lagna_name = SIGN_HI.get(lagna["sign"], lagna["sign"])
        moon_name = SIGN_HI.get(moon["sign"], moon["sign"])
        nak = NAKSHATRA_HI.get(moon["nakshatra"], moon["nakshatra"])
        seventh_name = SIGN_HI.get(seventh, seventh)
        tenth_name = SIGN_HI.get(tenth, tenth)
        fifth_name = SIGN_HI.get(fifth, fifth)
        lord_label = PLANET_LABELS_HI.get(lord, "")
        md_label = PLANET_LABELS_HI.get(md, "")
        ad_label = PLANET_LABELS_HI.get(ad, "")
        md_theme = PLANET_THEMES_HI.get(md, "")
        lord_house_theme = HOUSE_THEMES_HI.get(lord_house, "")
        seventh_theme = SIGN_THEMES_HI.get(seventh, "")
        tenth_theme = SIGN_THEMES_HI.get(tenth, "")
        fifth_theme = SIGN_THEMES_HI.get(fifth, "")
        moon_theme = SIGN_THEMES_HI.get(moon["sign"], "")
        sati = (
            "साढ़े साती सक्रिय है, इसलिए धैर्य और नियमित दिनचर्या इस समय सहायक हैं।"
            if sade_sati
            else "अभी गोचर शनि साढ़े साती सक्रिय नहीं दिखाता।"
        )

        replies = {
            "career": (
                f"आपकी कुंडली में दशम भाव {tenth_name} है, जिसके विषय: {tenth_theme}। "
                f"लग्नेश {lord_label} {lord_house} भाव में है, इसलिए {lord_house_theme} से जुड़ा काम अधिक सहज लग सकता है। "
                f"अभी {md_label} महादशा {md_theme} को प्रमुख बनाती है। "
                "एक व्यावहारिक कदम: इस सप्ताह एक कौशल वाला काम पूरा करें, फिर अगला शुरू करें।"
            ),
            "marriage": (
                f"सप्तम भाव {seventh_name} है और साथी के साथ {seventh_theme} जैसी ऊर्जा दिख सकती है। "
                f"चंद्र {moon_name} और {nak} नक्षत्र में है — {moon_theme}। "
                + (
                    "मंगल दोष सक्रिय है; इसे अंतिम निर्णय न मानें, किसी योग्य ज्योतिषी से मिलान जाँचें। "
                    if manglik
                    else "मंगल दोष सक्रिय नहीं दिखता। "
                )
                + "स्पष्ट अपेक्षाएँ और नियमित बातचीत रिश्ते को मजबूत रखती हैं।"
            ),
            "money": (
                f"धन तेज़ उपायों से कम, स्थिर काम से अधिक जुड़ा दिखता है: दशम भाव {tenth_name} है, "
                f"और लग्नेश {lord_house} भाव में है — {lord_house_theme}। "
                f"अभी {md_label} महादशा का समय है, इसलिए बड़े खर्च लिखित योजना के बाद करें। "
                "एक छोटा कदम: इस महीने की आय-खर्च सूची बनाएँ और एक गैर-ज़रूरी खर्च टालें।"
            ),
            "health": (
                "स्वास्थ्य के लिए नींद, सादा भोजन और रोज़ की गति सबसे भरोसेमंद आधार हैं। "
                f"चंद्र {moon_name} में है — {moon_theme}, इसलिए मन और विश्राम का संतुलन ज़रूरी है। "
                f"{sati} किसी भी लगातार तकलीफ़ के लिए योग्य डॉक्टर से सलाह लें; यह पठन इलाज नहीं है।"
            ),
            "education": (
                f"पाँचवाँ भाव {fifth_name} है, जिसके विषय: {fifth_theme}। "
                f"लग्नेश {lord_label} {lord_house} भाव में है, इसलिए {lord_house_theme} से जुड़ी पढ़ाई रुचिकर लग सकती है। "
                "छोटे सत्रों में पढ़ें, हर सत्र के बाद दोहराव रखें, और परीक्षा से पहले नींद पूरी करें।"
            ),
            "mangal": (
                (
                    "मंगल दोष आपकी कुंडली में सक्रिय दिखता है, लेकिन यह विवाह का अंतिम निर्णय नहीं है। "
                    if manglik
                    else "आपकी कुंडली में मंगल दोष सक्रिय नहीं दिखता। "
                )
                + f"सप्तम भाव {seventh_name} है — {seventh_theme}। "
                "परंपरा में दोष भंग के कई नियम हैं, इसलिए मिलान किसी योग्य ज्योतिषी से जाँचें। "
                "एक अच्छी आदत: कठिन बातचीत में उत्तर देने से पहले दो साँस लें।"
            ),
            "dasha": (
                f"अभी {md_label} महादशा चल रही है, जो {md_theme} पर ज़ोर देती है"
                + (f", और {ad_label} अंतर्दशा रोज़ के फैसलों में इसे लागू करती है। " if ad and ad != md else "। ")
                + f"{sati} "
                "इस अवधि में बड़े बदलाव चरणों में करें और हर चरण के लिए एक ठोस आदत चुनें।"
            ),
            "remedies": (
                f"तीन सरल, कम खर्च वाले अभ्यास: {MANTRA_HI.get(lord, 'ॐ नमः शिवाय')} का सप्ताह में पाँच दिन 11 बार जाप; "
                f"{DANA_HI.get(md, 'सादा भोजन दान')} महीने में एक बार; और रोज़ 10 मिनट टहलना। "
                f"ये लग्नेश {lord_label} और वर्तमान {md_label} महादशा से जोड़े गए हैं। "
                "उपाय वैकल्पिक सांस्कृतिक अभ्यास हैं, किसी परिणाम की गारंटी नहीं।"
            ),
            "general": (
                f"आपका लग्न {lagna_name} है, लग्नेश {lord_label} {lord_house} भाव में है, "
                f"और चंद्र {moon_name} राशि तथा {nak} नक्षत्र में है। "
                f"अभी {md_label} महादशा {md_theme} को प्रमुख बनाती है। "
                "आप करियर, रिश्ते, धन, स्वास्थ्य, दशा या उपाय — किसी भी विषय पर पूछ सकते हैं।"
            ),
        }
        return replies[topic]

    # English
    lord_label = PLANET_LABELS.get(lord, "")
    md_label = PLANET_LABELS.get(md, "")
    ad_label = PLANET_LABELS.get(ad, "")
    md_theme = PLANET_THEMES.get(md, "")
    lord_house_theme = HOUSE_THEMES.get(lord_house, "")
    seventh_theme = SIGN_THEMES.get(seventh, "")
    tenth_theme = SIGN_THEMES.get(tenth, "")
    fifth_theme = SIGN_THEMES.get(fifth, "")
    moon_theme = SIGN_THEMES.get(moon["sign"], "")
    sati = (
        "Sade Sati is active, so patience and steady routines help at this time."
        if sade_sati
        else "Saturn's transit does not show Sade Sati right now."
    )
    moon_main, moon_caveat = _theme(moon_theme)

    replies = {
        "career": (
            f"Your tenth house is {tenth}, with themes of {tenth_theme}. "
            f"With the Lagna lord {lord_label} in house {lord_house}, work linked to "
            f"{lord_house_theme} may feel more natural. "
            f"The current {md_label} Mahadasha puts {md_theme} in focus. "
            "One practical step: finish one skill-building task this week before starting another."
        ),
        "marriage": (
            f"The seventh house is {seventh}, so partnership may carry {seventh_theme}. "
            f"The Moon in {moon['sign']} and {moon['nakshatra']} brings {moon_main}; {moon_caveat}. "
            + (
                "Mangal Dosha is active, but it is not a verdict: have matching checked by a qualified astrologer. "
                if manglik
                else "Mangal Dosha is not active in this chart. "
            )
            + "Clear expectations and regular conversation matter more than any score."
        ),
        "money": (
            f"Money tends to follow steady work rather than quick shortcuts here: the tenth house is {tenth}, "
            f"and the Lagna lord sits in house {lord_house}, linked to {lord_house_theme}. "
            f"The {md_label} Mahadasha rewards planning over impulse. "
            "One small step: write this month's income and expenses, then postpone one non-essential purchase."
        ),
        "health": (
            "Sleep, simple food and daily movement are the most reliable supports for your energy. "
            f"With the Moon in {moon['sign']}, {moon_main} colours your mood; {moon_caveat}. "
            f"{sati} For any persistent symptom, please see a qualified doctor; this reading is not medical advice."
        ),
        "education": (
            f"Your fifth house is {fifth}, with themes of {fifth_theme}. "
            f"With the Lagna lord in house {lord_house}, study linked to {lord_house_theme} may hold your interest. "
            "Short focused sessions with a quick review after each one tend to work better than long marathons. "
            "Protect your sleep before exams."
        ),
        "mangal": (
            (
                "Mangal Dosha appears active in your chart, but it is not a final verdict on marriage. "
                if manglik
                else "Mangal Dosha does not appear active in your chart. "
            )
            + f"The seventh house is {seventh}, carrying {seventh_theme}. "
            "Tradition has several cancellation rules, so have compatibility checked by a qualified astrologer. "
            "A useful habit: take two breaths before replying in a difficult conversation."
        ),
        "dasha": (
            f"You are in the {md_label} Mahadasha, which emphasises {md_theme}"
            + (f", with the {ad_label} Antardasha applying it in daily decisions. " if ad and ad != md else ". ")
            + f"{sati} "
            "Make large changes in stages and attach one steady habit to each stage."
        ),
        "remedies": (
            "Three simple, low-cost practices: chant "
            f"{MANTRA.get(lord, 'Om Namah Shivaya')} 11 times on five days a week; "
            f"offer {DANA.get(md, 'simple food')} once a month; and walk for ten minutes daily. "
            f"They are tied to your Lagna lord {lord_label} and the current {md_label} Mahadasha. "
            "Remedies are optional cultural practices, not a guarantee."
        ),
        "general": (
            f"Your Lagna is {lagna['sign']} with its lord {lord_label} in house {lord_house}, "
            f"and the Moon is in {moon['sign']} and {moon['nakshatra']}. "
            f"The {md_label} Mahadasha currently emphasises {md_theme}. "
            "Ask me about career, relationships, money, health, your dasha or remedies for a closer look."
        ),
    }
    return replies[topic]


def _system_prompt(facts: dict[str, Any], language: str) -> str:
    language_name = "Hindi" if language == "hi" else "English"
    return (
        f"{CHAT_SYSTEM}\nReply language: {language_name}.\n"
        f"Verified chart facts: {json.dumps(facts, ensure_ascii=False)}"
    )


def _recent(messages: list[ChatMessage], turns: int) -> list[ChatMessage]:
    recent = messages[-turns:]
    # A window that opens on an assistant turn looks like a prompt-less answer.
    if recent and recent[0].role != "user":
        recent = recent[1:]
    return recent


def _gemini_reply(
    settings: Settings,
    facts: dict[str, Any],
    messages: list[ChatMessage],
    language: str,
    use_search: bool,
) -> tuple[str, str] | None:
    if not settings.gemini_keys:
        return None

    system = _system_prompt(facts, language)
    contents = [
        {
            "role": "user" if message.role == "user" else "model",
            "parts": [{"text": message.content}],
        }
        for message in _recent(messages, settings.ai_history_turns)
    ]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.9,
            "maxOutputTokens": settings.ai_max_output_tokens,
        },
    }
    if use_search:
        body["tools"] = [{"google_search": {}}]
    result = generate_content(settings, body)
    if result is None:
        return None

    data, model = result
    try:
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content", {}).get("parts") if candidates else None) or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        text = text.strip()
        if not text:
            return None
        return text[:1600], model
    except Exception as exc:  # noqa: BLE001 - any AI failure must fall back
        logger.warning("Gemini chat failed: %s", exc)
        return None


def _groq_reply(
    settings: Settings,
    facts: dict[str, Any],
    messages: list[ChatMessage],
    language: str,
) -> tuple[str, str] | None:
    if not settings.groq_keys:
        return None
    history = [
        {"role": "user" if message.role == "user" else "assistant", "content": message.content}
        for message in _recent(messages, settings.ai_history_turns)
    ]
    result = chat_completion(
        settings,
        system=_system_prompt(facts, language),
        messages=history,
        max_tokens=settings.ai_max_output_tokens,
    )
    if result is None:
        return None
    text, model = result
    return text[:1600], model


def chat_reply(
    settings: Settings,
    kundli: dict[str, Any],
    *,
    messages: list[ChatMessage],
    language: str,
    use_provider: bool = True,
    use_search: bool = False,
) -> dict[str, Any]:
    facts = build_facts(kundli, "life")
    ai_result = None
    source = "chart"
    if use_provider:
        ai_result = _gemini_reply(settings, facts, messages, language, use_search)
        if ai_result is not None:
            source = "gemini"
        elif settings.groq_keys:
            ai_result = _groq_reply(settings, facts, messages, language)
            if ai_result is not None:
                source = "groq"

    if ai_result is not None:
        reply, model = ai_result
    else:
        reply = _fallback_reply(facts, language, messages[-1].content)
        model = None

    return {
        "source": source,
        "model": model,
        "language": language,
        "reply": reply,
        "disclaimer": DEFAULT_DISCLAIMER,
        "privacy": CHAT_PRIVACY,
        "generated_at": datetime.now(UTC).isoformat(),
    }
