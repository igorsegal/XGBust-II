import json
import os
from typing import Dict, Optional

# 🔑 Configuration — loaded from environment variables
DEFAULT_DASHSCOPE_MODEL = "qwen-plus"
FALLBACK_OPENAI_MODEL = "gpt-4o-mini"

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


def _call_dashscope(user_content: str, model: str = DEFAULT_DASHSCOPE_MODEL) -> Dict:
    try:
        import dashscope
        from dashscope import Generation
        
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("❌ DASHSCOPE_API_KEY is not set")
        
        response = Generation.call(
            model=model,
            api_key=api_key,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=1500,
            result_format="message",
            response_format="json_object"  # Critical: enables strict JSON output
        )
        
        if response.status_code != 200:
            raise ValueError(f"DashScope API error: {response.status_code} {response.message}")
        
        raw_json = response.output.choices[0].message.content
        return json.loads(raw_json)
        
    except Exception as e:
        print(f"[DASHSCOPE_ERROR] {e}")
        return None


def _call_openai(user_content: str, model: str = FALLBACK_OPENAI_MODEL) -> Dict:
    try:
        from openai import OpenAI
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ OPENAI_API_KEY is not set")
        
        client = OpenAI(api_key=api_key)
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
        
        raw_json = response.choices[0].message.content
        return json.loads(raw_json)
        
    except Exception as e:
        print(f"[OPENAI_ERROR] {e}")
        return None


def evaluate_article(article: Dict) -> Optional[Dict]:
    try:
        user_content = (
            f"TITLE: {article['title']}\n"
            f"YEAR: {article['published_year']}\n"
            f"URL: {article['url']}\n\n"
            f"TEXT:\n{article['text'][:24000]}"
        )

        # Try DashScope first
        result = _call_dashscope(user_content)
        if result is not None:
            result["url"] = article["url"]
            result["title"] = article["title"]
            result["published_year"] = article["published_year"]
            return result

        # Fallback to OpenAI
        result = _call_openai(user_content)
        if result is not None:
            result["url"] = article["url"]
            result["title"] = article["title"]
            result["published_year"] = article["published_year"]
            return result

        print(f"[AI_WARN] Failed to evaluate {article['url']}: both DashScope and OpenAI failed")
        return None

    except ValueError as ve:
        print(f"[CONFIG_ERROR] {ve}")
        return None
    except Exception as e:
        print(f"[AI_UNEXPECTED] Unexpected error in evaluate_article: {e}")
        return None
