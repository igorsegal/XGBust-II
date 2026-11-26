# Правила для проверки в C++ тестере (на 2026-11-24)

## 1. Правила, проверенные в тестере: Hedge, результат НЕ ПРОШЛО (подробности в REPORT.md и registry\rules_registry.json)

**Hedge (Multiplicative Weights): Blending a Handful of Simple Trading Rules Online**

Статья: https://www.mql5.com/en/articles/25064

Файл правила: D:\AHexaTrader\XGBoost-edge-git\data_test\specs\25064.json

Пара и таймфрейм автора: EURUSD, GBPUSD, XAUUSD; H1 и M15. Главный тест: EURUSD M15 и H1.

Вход в лонг: EnsembleSignal >= 0.20; в шорт: EnsembleSignal <= -0.20

Выход и стоп в статье не описаны: тестер ставит выход через 24 бара и стоп 2*ATR(14).

Параметры: {"InpMaFast": 10, "InpMaSlow": 50, "InpRsiPeriod": 14, "InpRsiLower": 30.0, "InpRsiUpper": 70.0, "InpBbPeriod": 20, "InpBbDeviation": 2.0, "InpMacdFast": 12, "InpMacdSlow": 26, "InpMacdSignal": 9, "InpDonchianPeriod": 20, "InpRegretHorizon": 2000, "InpConfidence": 0.2, "η": 0.08}

Полное описание:

На каждом баре (с использованием только данных предыдущего полностью закрытого бара, shift=1) вычисляются пять сигналов: 1) MA Cross: +1 если быстрая скользящая средняя (период InpMaFast=10) > медленная (InpMaSlow=50), -1 если <, иначе 0; 2) RSI Reversion: +1 если RSI (период InpRsiPeriod=14) < InpRsiLower=30.0, -1 если > InpRsiUpper=70.0, иначе 0; 3) Bollinger Breakout: +1 если цена закрытия > верхней полосы Bollinger (период InpBbPeriod=20, отклонение InpBbDeviation=2.0), -1 если < нижней полосы, иначе 0; 4) MACD Histogram: +1 если гистограмма MACD (быстрый EMA=12, медленный=26, сигнал=9) > 0, -1 если < 0, иначе 0; 5) Donchian Breakout: +1 если цена закрытия >= максимума High за последние InpDonchianPeriod=20 баров (включая текущий бар в окне расчёта, но данные берутся строго с shift=1 — т.е. из прошлых баров), -1 если <= минимума Low за те же 20 баров, иначе 0. Затем вычисляется взвешенная сумма сигналов: EnsembleSignal = Σ(w_i * v_i), где w_i — адаптивные веса, обновляемые по мультипликативному правилу Hedge: w_i(t+1) = w_i(t) * exp(-η * l_i(t)), после чего веса нормализуются так, чтобы их сумма равнялась 1. Потери l_i(t) вычисляются как 0.5 - 0.5 * v_i(t) * sign(t), где sign(t) = +1 если цена закрытия бара t выше цены закрытия бара t-1, -1 если ниже, 0 если равно. Начальные веса равны 1/5. Параметр η вычисляется автоматически как √(8·ln(5)/T), где T = InpRegretHorizon = 2000 (по умолчанию), что даёт η ≈ 0.080. Допущение: вход осуществляется при |EnsembleSignal| ≥ InpConfidence = 0.20, причём направление лонг соответствует EnsembleSignal ≥ 0.20, шорт — EnsembleSignal ≤ -0.20.

## 2. Все разобранные судом статьи (27)

| Статус | Номер | Название | Причина отказа |
|---|---|---|---|
| ПРИНЯТА | 25064 | Hedge (Multiplicative Weights): Blending a Handful of Simple Trading Rules Online |  |
| отклонена | 20377 | Neural Networks in Trading: A Spiking Architecture for Spatio-Temporal Market Analysis (En | Статья не содержит конкретного торгового сигнала: нет описания условий входа в сделку (например, 'покупать при X-условии', 'продавать при Y-сигнале'), только архитектура  |
| отклонена | 20404 | Neural Networks in Trading: A Spiking Architecture for Spatio-Temporal Market Analysis (Co | Статья не содержит конкретного торгового сигнала: нет описания, как из выхода модели (например, предсказания, логитов, скрытого состояния) формируется решение 'покупать', |
| отклонена | 20421 | Neural Networks in Trading: A Spatio-Temporal State-Space Model for Financial Data Analysi | Статья описывает архитектуру нейросетевой модели (E-STMFlow) для обработки событийных финансовых данных, но не содержит чёткого, детерминированного правила входа: отсутст |
| отклонена | 20447 | Neural Networks in Trading: A Spatio-Temporal State Space Model for Financial Data Analysi | Статья не содержит конкретного торгового сигнала: нет описания условия входа (например, порога предсказания, кросса, уровня), нет указания, как из выхода STSSM/модели пол |
| отклонена | 22674 | How to Build a 29-Pair Portfolio with an L1 Filter and VaR-based Allocation of Lots | Фатальный порок: условие входа не описано — статья не определяет, как именно предсказание бинарного сигнала («цена вырастет через 3 L1-бара») преобразуется в конкретное т |
| отклонена | 22686 | Beluga Whale Optimization (BWO) Algorithm | Статья не описывает торговое правило вообще — это описание оптимизационного алгоритма для численной минимизации функций. В ней отсутствуют любые элементы торгового правил |
| отклонена | 22816 | TradeMux as a Quant Backbone: Connecting Institutional Python Pipelines to Different Termi | Статья не описывает конкретное торговое правило: нет формализованного условия входа (например, 'BUY при X > Y и Z < W'), а только приводит примеры сигнальных функций (MAC |
| отклонена | 22890 | Self-Learning SuperTrend: An Adaptive Machine Learning-Based Trend Indicator | Фатальный порок: данные будущего в сигнале. Сигнал зависит от виртуальных проб, оцениваемых через 5 баров вперёд («After 5 bars, the probe is closed: the closing price is |
| отклонена | 23053 | Coyote Optimization Algorithm (COA) | Статья не описывает торговое правило, а представляет собой описание алгоритма оптимизации параметров (метаэвристики) для поиска наилучших значений параметров торговой сис |
| отклонена | 23132 | The Chimp Optimization Algorithm: From ChOA to BChimp | Статья описывает алгоритм глобальной оптимизации (Chimp Optimization Algorithm) для непрерывных численных задач, а не торговое правило. В тексте отсутствуют: условие вход |
| отклонена | 23134 | A Grid Expert Advisor Based on a Cellular Automaton with Online Learning in MQL5 (Part II) | Статья описывает архитектурные улучшения (граф-фильтрацию признаков, семантические связи клеток, когерентность голосования), но не содержит чёткого, детерминированного пр |
| отклонена | 23135 | A Grid Expert Advisor Based on a Cellular Automaton with Online Learning in MQL5 (Part III | Фатальный порок: статья не содержит чёткого, детерминированного правила входа. Условие открытия позиции в HandleNewBar() зависит от недефинированных переменных g_cur.min_ |
| отклонена | 23324 | Association Rules and Probability Theory in Forex: A Signal Filter Without Neural Networks | Статья не описывает конкретное правило входа с чётким направлением и параметрами — она описывает *общую архитектуру фильтра на основе ассоциативных правил*, но не указыва |
| отклонена | 24470 | MetaTrader 5 Machine Learning Blueprint (Part 25): Live Monitoring | Статья не описывает торговое правило (вход/выход), а посвящена системе мониторинга работоспособности уже развернутой стратегии — это инфраструктурное решение для post-dep |
| отклонена | 24501 | MetaTrader 5 Machine Learning Blueprint (Part 26): Process Permutation | Статья не описывает конкретное торговое правило для входа/выхода, а фокусируется на методологии оценки процесса разработки (перестановочном тесте целого пайплайна), включ |
| отклонена | 24649 | Integrating MQL5 with Data Processing Packages (Part 11): Multi-Timeframe Causality Detect | Фатальный порок: правило не может быть записано как чёткое детерминированное условие входа, поскольку статья не описывает конкретное, однозначное условие срабатывания сиг |
| отклонена | 24824 | Weak Supervision for Traders: Combining Several Noisy Labeling Heuristics into One Probabi | Статья не содержит конкретного торгового правила входа — она описывает метод фьюзинга сигналов (слабого обучения), но не определяет, при каком значении P(Buy) или каком у |
| отклонена | 24835 | Active Learning: An EA That Only Asks for Human Confirmation on Its Most Uncertain Trades | Статья описывает систему маршрутизации сигналов на основе неопределённости классификатора, но не содержит чёткого, детерминированного правила входа для закрытых баров спо |
| отклонена | 24857 | Estimate the Probability of Large-range Sessions (Part 1): Build and Check EURUSD Forecast | Статья описывает вероятностную модель прогнозирования превышения диапазона сессии (P(Y=1)), но не содержит чёткого, детерминированного правила входа: нет порога вероятнос |
| отклонена | 24864 | Local Outlier Factor: Density-Based Anomaly Detection in Native MQL5 | Статья не описывает чёткое детерминированное правило входа для торговли: LOF — это аномалийный фильтр (gate), а не правило генерации сигналов. Входы определяются внешней  |
| отклонена | 24943 | Why My MQL5 EA Passed Validation and Still Failed Under Execution Delay | Статья описывает инфраструктуру и надёжность исполнения торгового робота (MQL5 EA) в MetaTrader 5, а не самостоятельное торговое правило. В ней отсутствует чёткое, детерм |
| отклонена | 24946 | Do My EA's Losses Come in Clusters? A Wald-Wolfowitz Runs Test for Trade Outcomes in MQL5 | Статья описывает статистический тест (Wald-Wolfowitz runs test и связанные проверки) для анализа зависимости исходов закрытых сделок (кластеризация убытков), но не содерж |
| отклонена | 25097 | MQL5 Developer Gotchas (Part 1): A Parameter Mapper for Calling Indicators with Input Grou | Статья не описывает торговое правило, а посвящена инфраструктурной проблеме передачи параметров в кастомные индикаторы через iCustom()/IndicatorCreate() — в частности, вл |
| отклонена | 25141 | Does the Terminal Run the Model You Trained? ONNX Contract and Golden-File Checks in MQL5 | Статья не описывает торговое правило, стратегию или сигнал входа. Она посвящена инфраструктуре верификации корректности выполнения ONNX-моделей в MQL5: проверке контракта |
| отклонена | 25170 | Implementing a DST-aware Trading Day Resolver in MQL5 | Статья не содержит конкретного торгового сигнала или правила входа/выхода — она описывает инфраструктурный модуль для корректного определения торговых дней с учётом часов |
| отклонена | 25757 | How to Develop a Multi-Currency Expert Advisor with the AI Assistant in MetaTrader 5 | Статья не содержит полного детерминированного правила для проверки на закрытых барах спот-форекса. Хотя отдельные стратегии S1 и S2 описаны частично, они явно отвергнуты  |

Статьи, отсеянные фильтром 1 до суда: D:\AHexaTrader\XGBoost-edge-git\data_test\rejected.tsv
