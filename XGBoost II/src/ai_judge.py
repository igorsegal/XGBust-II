import json
import os
from typing import Dict, Optional
from openai import OpenAI

DEFAULT_BASE_URL = "https://azure.com"
PRIMARY_MODEL = "MAI-Code-2-Flash"
FALLBACK_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """
Ты — судейская коллегия «Протокола Гриль» (Адвокат, Прокурор, Судья) для отбора торговых идей и признаков (features) в движок AHexaTraderEngine (XGBoost для валютных пар Forex Majors и Crosses).

Вынеси СТРОГИЙ БИНАРНЫЙ ВЕРДИКТ: "PASS" или "REJECT".

Мгновенный REJECT:
1. Статья про графику (GUI, Canvas, Cairo), сетевые утилиты (SFTP, Telegram, Watchdog), управление ордерами без торговой логики.
2. Стратегия требует биржевой стакан (Level 2), реальные фьючерсные объемы или акции/крипту и неприменима к спот-форексу (Forex Majors/Crosses).
3. Есть заглядывание в будущее (look-ahead bias, использование Close или старшего таймфрейма до его закрытия) или субъективность ("на глаз").

Допуск PASS:
- Есть строгая, замкнутая математика индикатора, фильтра рыночного режима (волатильность, смена режима, корреляция) или правила входа/выхода, пригодная для вычисления на закрытых барах [t-1] в C++/Python.

Верни ТОЛЬКО валидный JSON:
{
  "verdict": "PASS",
  "reject_reason": "",
  "edge_type": "Feature_Engineering",
  "forex_pairs": ["EURUSD", "GBPUSD", "USDJPY"],
  "timeframes": ["H1", "H4", "D1"],
  "formula_and_logic": "точное математическое описание признака или правила без утечки будущего",
  "author_oos_metrics": "метрики тестирования автора из статьи",
  "judge_verdict_summary": "резюме судьи в 2 предложениях"
}
"""


def get_client() -> OpenAI:
    api_key = os.getenv("MAI_API_KEY") or os.getenv("GITHUB_TOKEN")
    base_url = os.getenv("MAI_BASE_URL") or DEFAULT_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url)


def _call_model(client: OpenAI, model: str, user_content: str) -> Dict:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    if isinstance(response, str):
        response = json.loads(response)
    if isinstance(response, dict):
        raw_json = response["choices"][0]["message"]["content"]
    else:
        raw_json = response.choices[0].message.content
    return json.loads(raw_json)


def evaluate_article(article: Dict) -> Optional[Dict]:
    client = get_client()
    primary = os.getenv("MAI_MODEL") or PRIMARY_MODEL

    user_content = (
        f"TITLE: {article['title']}\n"
        f"YEAR: {article['published_year']}\n"
        f"URL: {article['url']}\n\n"
        f"TEXT:\n{article['text'][:24000]}"
    )

    try:
        result = _call_model(client, primary, user_content)
    except Exception as e1:
        print(f"[AI_FALLBACK] {primary} unavailable ({e1}), switching to {FALLBACK_MODEL}")
        try:
            result = _call_model(client, FALLBACK_MODEL, user_content)
        except Exception as e2:
            print(f"[AI_WARN] Failed to evaluate {article['url']}: {e2}")
            return None

    result["url"] = article["url"]
    result["title"] = article["title"]
    result["published_year"] = article["published_year"]
    return result
