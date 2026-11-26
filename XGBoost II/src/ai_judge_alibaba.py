import json
import os
from typing import Dict, Optional
DEFAULT_DASHSCOPE_MODEL = "qwen-plus"
FALLBACK_OPENAI_MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = """
Ты — судейская коллегия «Протокола Гриль» (Адвокат, Прокурор, Судья) для отбора торговых идей и признаков (features) в движок AHexaTraderEngine (XGBoost для валютных пар Forex Majors и Crosses).
Вынеси СТРОГИЙ БИНАРНЫЙ ВЕРДИКТ: "PASS" или "REJECT".
Мгновенный REJECT:
1. Статья про графику (GUI, Canvas, Cairo), сетевые утилиты (SFTP, Telegram, Watchdog), управление ордерами без торговой логики.
2. Стратегия требует биржевой стакан (Level 2), реальные фьючерсные объемы или акции/крипту и неприменима к спот-форексу (Forex Majors/Crosses).
3. Есть заглядывание в будущее (look-ahead bias, использование Close[0] текущего незакрытого бара или старшего таймфрейма до его закрытия) или субъективность ("на глаз").
4. Используются сетка (Grid), мартингейл или усреднение убытков.
Допуск PASS:
- Есть строгая, замкнутая математика индикатора, фильтра рыночного режима (волатильность, смена режима, корреляция, мета-разметка) или правила входа/выхода, пригодная для вычисления на закрытых барах [t-1] в C++/Python.
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
def _validate_schema(data: Optional[Dict]) -> Optional[Dict]:
    if not isinstance(data, dict):
        return None
    verdict = str(data.get("verdict", "")).upper().strip()
    if verdict not in ("PASS", "REJECT"):
        return None
    data["verdict"] = verdict
    if verdict == "PASS":
        formula = str(data.get("formula_and_logic", "")).strip()
        if len(formula) < 20:
            data["verdict"] = "REJECT"
            data["reject_reason"] = "Invalid or empty formula_and_logic"
        if not isinstance(data.get("forex_pairs"), list) or not data["forex_pairs"]:
            data["forex_pairs"] = ["EURUSD", "GBPUSD", "USDJPY"]
        if not isinstance(data.get("timeframes"), list) or not data["timeframes"]:
            data["timeframes"] = ["H1", "H4"]
    return data
def _build_article_excerpt(text: str) -> str:
    if len(text) <= 26000:
        return text
    return text[:14000] + "\n\n... [TRUNCATED MIDDLE] ...\n\n" + text[-12000:]
def _call_dashscope(user_content: str, model: str = DEFAULT_DASHSCOPE_MODEL) -> Optional[Dict]:
    try:
        from dashscope import Generation
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY is not set")
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
            response_format="json_object",
        )
        if response.status_code != 200:
            raise ValueError(f"DashScope API error: {response.status_code} {response.message}")
        raw_json = response.output.choices[0].message.content
        return _validate_schema(json.loads(raw_json))
    except Exception as e:
        print(f"[DASHSCOPE_ERROR] {e}")
        return None
def _call_openai(user_content: str, model: str = FALLBACK_OPENAI_MODEL) -> Optional[Dict]:
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")
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
        return _validate_schema(json.loads(raw_json))
    except Exception as e:
        print(f"[OPENAI_ERROR] {e}")
        return None
def evaluate_article(article: Dict) -> Optional[Dict]:
    user_content = (
        f"TITLE: {article['title']}\n"
        f"YEAR: {article['published_year']}\n"
        f"URL: {article['url']}\n\n"
        f"TEXT:\n{_build_article_excerpt(article['text'])}"
    )
    result = _call_dashscope(user_content)
    if result is None:
        result = _call_openai(user_content)
    if result is None:
        print(f"[AI_WARN] Failed to evaluate {article['url']}")
        return None
    result["url"] = article["url"]
    result["title"] = article["title"]
    result["published_year"] = article["published_year"]
    return result