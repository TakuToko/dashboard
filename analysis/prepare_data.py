"""
prepare_data.py — 竞品分析数据预处理
-------------------------------------
流程：
  reviews.csv  →  pandas 清洗聚合  →  jieba 分词  →  analysis.json

输出 JSON 结构（前端 dashboard.html 直接读取）：
  {
    "version_id":        版本 ID（= CSV 采集时间戳）,
    "schema_version":    数据结构版本（字段变更时 +1，前端据此提示新旧不可比）,
    "data_collected_at": 数据采集时间（来自 CSV 时间戳）,
    "generated_at":      分析生成时间,
    "overview":          游戏级基础统计,
    "rating_dist":       评分分布（分游戏）,
    "playtime_score":    游戏时长 vs 评分,
    "time_trend":        评论时间趋势,
    "word_freq":         各游戏高频词（词云用，保留游戏名等展示感词）,
    "llm_phrases":       LLM 归纳 + 规则锚定的原因短语（结论用，无 key 时为空 {}）,
    "top_reviews":       点赞 Top 评论,
    "insights":          规则化研究结论（每条带 group：main=万象棋主线 / benchmark=竞品镜鉴）,
    "recommendations":   行动建议（全部针对主线游戏 王者万象棋）,
    "key_findings":      首屏「核心发现」摘要（取 main 组按严重度排序，回链建议）,
    "player_persona":    玩家画像（生命周期 + 阶段分桶 + 标签 + 阶段×原因短语矩阵）,
    "mechanic_compare":  竞品机制对比表（人工维护的行业知识：设计差异）,
    "data_compare":      数据对比表（自动生成：官方数据 + 抽样统计 + 原因短语）
  }

⚠️ 所有业务配置已统一到 config.py，本文件只保留逻辑。
"""

import json
import sys
import os
import re
from collections import Counter
from datetime import datetime

import pandas as pd
import jieba
import jieba.analyse

# =========================================================
# 0. 导入配置 + 工具函数（从项目根目录）
# =========================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 本模块所在目录也加进来，保证 llm_phrases.py 无论以脚本还是模块方式运行都能 import
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from config import (
    GAMES_CONFIG,        # 游戏主配置
    CUSTOM_STOPWORDS,    # 停用词表
    NEGATION_WORDS,      # 🆕 否定词（否定词后面的词极性反转，跳过不计词频）
    INSIGHT_NOISE_WORDS, # 🆕 规则引擎专用二次过滤词（词云不过滤）
    DOMAIN_WORDS,        # jieba 领域词典
    USER_TAG_RULES,      # 用户标签规则
    MECHANIC_COMPARE,    # 竞品机制对比表
    STAGE_PHRASE_MIN_HITS,  # 🆕 阶段×原因短语矩阵：最小命中数
    STAGE_PHRASE_TOP_N,     # 🆕 阶段×原因短语矩阵：每阶段展示条数
)
import utils  # 🆕 爬虫工具（含 App 详情接口）
from llm_phrases import (  # 🆕 LLM 原因短语抽取（阶段A归纳 + 阶段B锚定）
    build_llm_phrases,
    _prepare_matcher,      # 复用短语的匹配器构造，保证与锚定口径一致
    _hit,
)

# =========================================================
# 1. 路径（预处理模块自己的路径，不进 config）
# =========================================================
DATA_DIR = os.path.join(BASE_DIR, "data")                          # main.py 爬取的时间戳 CSV 目录
DASHBOARD_DIR = os.path.join(BASE_DIR, "dashboard")
ANALYSES_DIR = os.path.join(DASHBOARD_DIR, "analyses")            # 多版本 JSON 存放目录
VERSIONS_PATH = os.path.join(DASHBOARD_DIR, "versions.json")       # 前端版本清单
CURRENT_JSON_PATH = os.path.join(DASHBOARD_DIR, "analysis.json")   # 当前激活版本（兼容旧前端）

# 数据结构版本：顶层字段新增/变更时 +1。
# 前端据此判断"该版本的模块是否齐全"，缺失模块（如 llm_phrases / data_compare）会显示降级提示。
SCHEMA_VERSION = 1


def find_latest_csv():
    """自动找 data/ 下最新的 reviews_*.csv"""
    import glob
    if not os.path.isdir(DATA_DIR):
        return None
    csvs = glob.glob(os.path.join(DATA_DIR, "reviews_*.csv"))
    if not csvs:
        return None
    return max(csvs, key=os.path.getmtime)


def csv_to_version_id(csv_path):
    """从 CSV 文件名提取版本 ID（时间戳）"""
    basename = os.path.basename(csv_path)
    # reviews_20260923_143000.csv → 20260923_143000
    return basename.replace("reviews_", "").replace(".csv", "")


def version_id_to_time(version_id):
    """版本 ID（采集时间戳）→ 可读时间：20260923_143000 → 2026-09-23 14:30"""
    vid = str(version_id)
    if len(vid) >= 13 and vid[8] == "_":
        return f"{vid[:4]}-{vid[4:6]}-{vid[6:8]} {vid[9:11]}:{vid[11:13]}"
    return vid


# =========================================================
# 2. 数据加载与清洗
# =========================================================
def load_and_clean(csv_path):
    """读 CSV，做必要的类型转换和清洗"""
    print(f"[1/6] 正在加载 {csv_path} ...")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    df["评分"] = pd.to_numeric(df["评分"], errors="coerce")
    df["评论时间"] = pd.to_datetime(df["评论时间"], errors="coerce", format="mixed")
    df["玩过时长_小时"] = pd.to_numeric(df["玩过时长_小时"], errors="coerce")
    df = df.dropna(subset=["评分", "评论内容"])

    print(f"      清洗完成: {len(df)} 条有效评论")
    print(f"      游戏列表: {df['游戏名称'].unique().tolist()}")
    return df


# =========================================================
# 3. 分词 & 词频统计
# =========================================================
def tokenize(texts, top_n=150):
    """对文本列表做 jieba 分词，返回 top_n 高频词列表"""
    counter = Counter()

    # 注册领域专有名词（从 config 读，防止 jieba 错误切分）
    for w in DOMAIN_WORDS:
        jieba.add_word(w)

    for text in texts:
        clean = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", " ", str(text))
        words = [w.strip() for w in jieba.lcut(clean)]

        # 标记极性被反转的词：否定词在**前**（"不好玩" → 不 + 好玩、"不喜欢" → 不 + 喜欢）
        # → 跳过否定词后面的那个词，否则差评词云里会出现"好玩""喜欢"这类与语境矛盾的正面词。
        # 只做前缀否定：中缀否定（"画面不好"）里的前词是有效抱怨对象，不能误杀。
        negated_next = set()
        for i, w in enumerate(words):
            if w in NEGATION_WORDS and i + 1 < len(words):
                negated_next.add(i + 1)

        for i, w in enumerate(words):
            if i in negated_next or not w:
                continue
            if len(w) < 2:
                continue
            if w in CUSTOM_STOPWORDS:
                continue
            counter[w] += 1

    return [{"name": w, "value": c} for w, c in counter.most_common(top_n)]


# =========================================================
# 4. 各模块统计函数
# =========================================================
def compute_overview(df):
    """模块 1: 游戏级基础统计"""
    print("[2/6] 正在计算 overview ...")
    result = {}
    for game, gdf in df.groupby("游戏名称"):
        result[game] = {
            "avg_score": round(gdf["评分"].mean(), 2),
            "review_count": len(gdf),
            "total_ups": int(pd.to_numeric(gdf["点赞数"], errors="coerce").sum()),
            "total_downs": int(pd.to_numeric(gdf["点踩数"], errors="coerce").sum()),
            "avg_play_hours": round(gdf["玩过时长_小时"].mean(), 1),
            "5star_ratio": round((gdf["评分"] == 5).sum() / len(gdf) * 100, 1),
            "1star_ratio": round((gdf["评分"] == 1).sum() / len(gdf) * 100, 1),
        }
    return result


def compute_rating_dist(df):
    """模块 2: 评分分布"""
    print("[3/6] 正在计算 rating_dist ...")
    result = {}
    for game, gdf in df.groupby("游戏名称"):
        dist = gdf["评分"].value_counts().sort_index()
        result[game] = {str(int(k)): int(v) for k, v in dist.items()}
    return result


def compute_playtime_score(df):
    """模块 3: 玩过时长 vs 评分"""
    print("[4/6] 正在计算 playtime_score ...")

    bins = [0, 10, 30, 50, 100, 9999]
    labels = ["<10h", "10-30h", "30-50h", "50-100h", ">100h"]

    df_copy = df.copy()
    df_copy["时长分组"] = pd.cut(
        df_copy["玩过时长_小时"], bins=bins, labels=labels, right=False
    )

    result = {}
    for game, gdf in df_copy.groupby("游戏名称"):
        bucket_avg = gdf.groupby("时长分组", observed=True)["评分"].mean()
        expect_df = gdf[gdf["玩过阶段"] == "期待"]
        expect_avg = round(expect_df["评分"].mean(), 2) if len(expect_df) > 0 else None

        result[game] = {
            "buckets": labels,
            "avg_scores": [round(bucket_avg.get(l, 0), 2) if not pd.isna(bucket_avg.get(l)) else None for l in labels],
            "expect_score": expect_avg,
            "expect_count": int((gdf["玩过阶段"] == "期待").sum()),
        }
    return result


def compute_time_trend(df):
    """模块 4: 评论时间趋势"""
    print("[5/6] 正在计算 time_trend ...")
    result = {}
    for game, gdf in df.groupby("游戏名称"):
        gdf_clean = gdf.dropna(subset=["评论时间"])
        if len(gdf_clean) == 0:
            result[game] = {"dates": [], "counts": []}
            continue
        daily = gdf_clean.groupby(gdf_clean["评论时间"].dt.date).size().sort_index()
        result[game] = {
            "dates": [str(d) for d in daily.index],
            "counts": [int(c) for c in daily.values],
        }
    return result


def compute_word_freqs(df):
    """模块 5 & 6: 各游戏高频词 + 负面高频词"""
    print("[6/6] 正在 jieba 分词（词云数据）...")
    result = {}
    for game, gdf in df.groupby("游戏名称"):
        all_texts = gdf["评论内容"].tolist()
        pos_texts = gdf[gdf["评分"] >= 4]["评论内容"].tolist()
        neg_texts = gdf[gdf["评分"] <= 2]["评论内容"].tolist()

        result[game] = {
            "all": tokenize(all_texts, top_n=150),
            "positive": tokenize(pos_texts, top_n=100),
            "negative": tokenize(neg_texts, top_n=100),
        }
    return result


def compute_top_reviews(df):
    """模块 7: 点赞 Top10 评论"""
    print("     正在提取点赞 Top 评论 ...")
    result = {}
    for game, gdf in df.groupby("游戏名称"):
        sorted_df = gdf.sort_values("点赞数", ascending=False).head(10)
        result[game] = sorted_df.apply(
            lambda r: {
                "nickname": str(r["评论者"]),
                "score": int(r["评分"]),
                "ups": int(pd.to_numeric(r["点赞数"], errors="coerce") or 0),
                "time": str(r["评论时间"])[:16],
                "play_hours": f"{r['玩过时长_小时']}h" if pd.notna(r["玩过时长_小时"]) else "未填",
                "content": str(r["评论内容"])[:300],
            },
            axis=1
        ).tolist()
    return result


def tag_user_by_text(text):
    """对一条评论打标签（从 config 读规则）"""
    tags = []
    for tag_name, patterns in USER_TAG_RULES:
        for p in patterns:
            if re.search(p, str(text)):
                tags.append(tag_name)
                break
    return tags


def _stage_of(stage_raw, hours):
    """
    玩家阶段分桶（唯一口径，画像统计与阶段×原因矩阵共用）
      期待者    ：玩过阶段含"期待"（预约未玩）
      新手      ：玩过时长 < 10h
      中级      ：10-50h
      深度      ：>= 50h
    注：非期待阶段但时长为空的评论归入「期待者」，与原有口径保持一致。
    """
    if "期待" in str(stage_raw):
        return "期待者"
    if pd.isna(hours):
        return "期待者"
    if hours < 10:
        return "新手 (<10h)"
    if hours < 50:
        return "中级 (10-50h)"
    return "深度 (>50h)"


def compute_player_persona(df):
    """
    模块 8: 玩家画像（首发新游专属方法）
    ┌─ 从 config.GAMES_CONFIG 读取生命周期元数据
    ├─ 按玩过阶段分桶 → 期待者 / 新手 / 中级 / 深度
    └─ 文本反推标签分布（规则法）
    """
    print("[额外] 正在生成玩家画像 ...")
    result = {}
    today = datetime.now().date()

    for game, gdf in df.groupby("游戏名称"):
        # 生命周期元数据：从 config.GAMES_CONFIG 读，计算距今天数
        game_cfg = GAMES_CONFIG.get(game, {})
        lifecycle = {
            "launch_date": game_cfg.get("launch_date", ""),
            "days_since_launch": (today - pd.to_datetime(game_cfg.get("launch_date", today)).date()).days if game_cfg.get("launch_date") else 0,
            "stage": game_cfg.get("stage", ""),
            "color": game_cfg.get("color", "#888"),
            "summary": game_cfg.get("summary", ""),
        }

        # 分桶（统一走 _stage_of，避免这里和阶段×原因矩阵口径漂移）
        df_copy = gdf.copy()
        df_copy["阶段分组"] = [
            _stage_of(sr, h)
            for sr, h in zip(df_copy["玩过阶段"], df_copy["玩过时长_小时"])
        ]

        stage_stats = []
        total = len(gdf)
        for stage in ["期待者", "新手 (<10h)", "中级 (10-50h)", "深度 (>50h)"]:
            sdf = df_copy[df_copy["阶段分组"] == stage]
            if len(sdf) == 0:
                continue
            stage_stats.append({
                "stage": stage,
                "count": int(len(sdf)),
                "ratio": round(len(sdf) / total * 100, 1),
                "avg_score": round(float(sdf["评分"].mean()), 2),
                "avg_play_hours": round(float(sdf["玩过时长_小时"].mean()), 1) if pd.notna(sdf["玩过时长_小时"]).any() else 0,
            })

        # 文本反推标签分布
        # 「正面评价 / 负面评价」是评价倾向，不是玩家身份/关注点，
        # 与评分分布图重复表达，且会挤占标签榜名额 —— 不进入标签分布。
        TENDENCY_TAGS = {"正面评价", "负面评价"}
        tag_counter = Counter()
        for text in gdf["评论内容"].tolist():
            for t in tag_user_by_text(text):
                tag_counter[t] += 1
        tag_distribution = [
            # category：前端据此分成「玩家身份」与「关注点」两组展示
            {"name": t, "value": int(c), "ratio": round(c / total * 100, 1),
             "category": "关注点" if t.startswith("关注") else "身份"}
            for t, c in tag_counter.most_common(20)
            if t not in TENDENCY_TAGS
        ]

        result[game] = {
            "lifecycle": lifecycle,
            "total_reviews": int(total),
            "stage_stats": stage_stats,
            "tag_distribution": tag_distribution,
        }
    return result


def compute_data_compare(data):
    """
    模块 7.5: 数据对比表（全部由本次采集数据自动生成，不写死）
    —— 与 config.MECHANIC_COMPARE 互补：那张表回答"设计上有什么不同"（人工维护的行业知识），
       这张表回答"玩家实际怎么评价"（官方数据 + 抽样统计 + 原因短语），
       并且把原先写死在机制表里的"玩家痛点"改为数据驱动，避免两处结论打架。
    """
    print("     正在生成数据对比表 ...")
    overview = data.get("overview", {}) or {}
    app_stats = data.get("app_stats", {}) or {}
    llm = data.get("llm_phrases", {}) or {}

    games = [g for g in GAMES_CONFIG.keys() if g in overview]
    if not games:
        return {"headers": ["对比维度"], "rows": []}

    def _w(n):
        """下载量：过万折算成万，便于阅读"""
        n = int(n or 0)
        return f"{n / 10000:.1f} 万" if n >= 10000 else (str(n) if n else "—")

    def _top_phrase(game, kind):
        items = (llm.get(game) or {}).get(kind) or []
        return f"{items[0]['phrase']}（{items[0]['ratio']}）" if items else "—"

    rows = [
        # 两条评分统一折算到 10 分制：否则 6.5/10 与 4.09/5 并排会被误读为「抽样低了 2~3 分」
        ["TapTap 官方评分（全量加权）", *[f"{app_stats.get(g, {}).get('rating', 0)}/10" for g in games]],
        ["本次抽样平均分（折算 10 分制）", *[f"{round(overview.get(g, {}).get('avg_score', 0) * 2, 1)}/10" for g in games]],
        ["抽样口径",        *[f"热度 Top{overview.get(g, {}).get('review_count', 0)} 简单平均"
                              for g in games]],
        ["官方下载量",      *[_w(app_stats.get(g, {}).get("download_count", 0)) for g in games]],
        ["官方关注数",      *[_w(app_stats.get(g, {}).get("follow_count", 0)) for g in games]],
        ["本次抽样评论量",  *[f"{overview.get(g, {}).get('review_count', 0)} 条" for g in games]],
        ["5星 / 1星 占比",  *[f"{overview.get(g, {}).get('5star_ratio', 0)}% / {overview.get(g, {}).get('1star_ratio', 0)}%"
                              for g in games]],
        ["差评 Top1 原因",  *[_top_phrase(g, "negative") for g in games]],
        ["好评 Top1 原因",  *[_top_phrase(g, "positive") for g in games]],
    ]
    return {"headers": ["对比维度", *games], "rows": rows}


def attach_stage_phrases(df, data):
    """
    模块 8.5: 阶段 × 原因短语矩阵
    —— 复用 LLM 短语的别名/关键词（与锚定同一套匹配口径），统计每个玩家阶段
       命中各原因短语的占比，并算「相对全局的提升度」= 该阶段占比 / 全局占比。
    —— 提升度 > 1 说明该原因在这个阶段被提得更多，即该阶段的特征诉求。
    —— 结果直接写回 data["player_persona"][game]["stage_stats"][i]["top_phrases"]。
    """
    llm = data.get("llm_phrases") or {}
    persona = data.get("player_persona") or {}
    if not llm:
        print("      ⚠️  无原因短语数据，阶段×原因矩阵跳过（前端将提示未生成）")
        return

    print("     正在计算阶段 × 原因矩阵 ...")
    for game, kinds in llm.items():
        stages = (persona.get(game) or {}).get("stage_stats") or []
        if not stages:
            continue

        gdf = df[df["游戏名称"] == game]
        if gdf.empty:
            continue
        gdf = gdf.assign(阶段分组=[
            _stage_of(sr, h) for sr, h in zip(gdf["玩过阶段"], gdf["玩过时长_小时"])
        ])
        contents = gdf["评论内容"].astype(str).str.lower()
        total = len(gdf)

        # 差评/好评短语合并成一张候选表（阶段内不区分好评差评，只看"被提及"）
        # 保留 polarity：前端据此把该阶段话题分成「不满」与「认可」两组展示
        phrases = ([(p, "negative") for p in kinds.get("negative", [])] +
                   [(p, "positive") for p in kinds.get("positive", [])])
        phrase_masks = []
        for p, polarity in phrases:
            aliases = [a for a in dict.fromkeys([p["phrase"]] + p.get("aliases", [])) if len(a) >= 2]
            matcher = _prepare_matcher(aliases, [k for k in p.get("keywords", []) if len(k) >= 2])
            mask = contents.apply(lambda t: _hit(t, matcher))
            if mask.sum() == 0:
                continue
            phrase_masks.append((p["phrase"], polarity, mask, float(mask.sum()) / total))

        for s in stages:
            in_stage = gdf["阶段分组"] == s["stage"]
            n_stage = int(in_stage.sum())
            rows = []
            for phrase, polarity, mask, overall_ratio in phrase_masks:
                n_hit = int((mask & in_stage).sum())
                if n_hit < STAGE_PHRASE_MIN_HITS or overall_ratio <= 0:
                    continue
                stage_ratio = n_hit / n_stage if n_stage else 0
                rows.append({
                    "phrase": phrase,
                    "polarity": polarity,
                    "count": n_hit,
                    "ratio": f"{round(stage_ratio * 100, 1)}%",
                    "lift": round(stage_ratio / overall_ratio, 1),
                })
            # 提升度优先，同提升度看命中数
            rows.sort(key=lambda r: (r["lift"], r["count"]), reverse=True)
            s["top_phrases"] = rows[:STAGE_PHRASE_TOP_N]

        print(f"         └ {game}：{len(stages)} 个阶段已生成特征原因")


def compute_bm25_index(df):
    """
    🆕 BM25 轻量语义检索索引（前端可直接计算打分）

    输出结构：
    {
      "reviews": [                        // 扁平化评论列表，用于搜索
        {
          "id": ..., "game": ..., "score": ..., 
          "ups": ..., "time": ..., "play_hours": ...,
          "content": "...原始文本...",
          "tokens": ["ELO", "控牌", "匹配", ...],  // 已过滤停用词
          "token_count": 12
        }, ...
      ],
      "idf": {"ELO": 3.2, "控牌": 2.8, ...},  // 全局 IDF 值
      "avgdl": 14.3                                 // 平均文档长度
    }
    
    BM25 公式（前端 JS 计算）：
      score(q, d) = Σ IDF(t) * TF(t,d) * (k1+1) / (TF(t,d) + k1*(1-b + b*dl/avgdl))
      默认 k1=1.5, b=0.75
    """
    print("[额外] 正在构建 BM25 检索索引 ...")

    # 注册领域词典
    for w in DOMAIN_WORDS:
        jieba.add_word(w)

    # —— 第一步：分词所有评论，统计 DF（文档频率）——
    doc_tokens = []       # List[List[str]]，每条评论的 token 列表
    df_counter = Counter()  # 每个词出现在多少条评论里（DF）
    total_docs = len(df)

    for _, row in df.iterrows():
        text = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", " ", str(row["评论内容"]))
        tokens = []
        for w in jieba.lcut(text):
            w = w.strip()
            if not w or len(w) < 2:
                continue
            if w in CUSTOM_STOPWORDS:
                continue
            tokens.append(w)
        doc_tokens.append(tokens)
        # DF：一个词在一条评论里出现多次只算一次
        for unique_tok in set(tokens):
            df_counter[unique_tok] += 1

    # —— 第二步：计算 IDF ——
    # IDF(t) = log((N - DF(t) + 0.5) / (DF(t) + 0.5) + 1)
    import math
    N = total_docs
    idf = {}
    for word, df_val in df_counter.items():
        idf[word] = round(math.log((N - df_val + 0.5) / (df_val + 0.5) + 1), 4)

    # —— 第三步：计算平均文档长度 ——
    avgdl = round(sum(len(t) for t in doc_tokens) / max(len(doc_tokens), 1), 2)

    # —— 第四步：组装评论列表 ——
    reviews_out = []
    for (_, row), tokens in zip(df.iterrows(), doc_tokens):
        # TF：Counter 统计词频
        tf_counter = Counter(tokens)
        # 只保留 Top 50 高频词的 TF（节省 JSON 体积）
        tf_top50 = dict(tf_counter.most_common(50))

        reviews_out.append({
            "id": str(row.get("评论ID", "")),
            "game": str(row["游戏名称"]),
            "score": int(row["评分"]),
            "ups": int(pd.to_numeric(row["点赞数"], errors="coerce") or 0),
            "time": str(row["评论时间"])[:16],
            "play_hours": round(float(row["玩过时长_小时"]), 1) if pd.notna(row["玩过时长_小时"]) else 0,
            "nickname": str(row.get("评论者", "")),
            "content": str(row["评论内容"])[:1000],  # 前端"原处展开原评论"要读完整原文
            "tokens": tokens[:80],       # 前 80 个 token（节省体积）
            "tf": tf_top50,              # Top 50 词的词频
            "dl": len(tokens),           # 文档长度
        })

    # IDF 只保留出现 >= 2 次的词（稀有词 IDF 太大容易噪声）
    idf_filtered = {w: v for w, v in idf.items() if df_counter[w] >= 2}

    print(f"      索引构建完成: {len(reviews_out)} 条评论, {len(idf_filtered)} 个唯一词, 平均长度 {avgdl}")

    return {
        "reviews": reviews_out,
        "idf": idf_filtered,
        "avgdl": avgdl,
        "total_docs": N,
    }


# =========================================================
# 9. 规则化分析引擎（可追溯的结构化结论 + LLM prompt 上下文）
# =========================================================
def analyze_insights(df, data):
    """
    规则化计算，不依赖 LLM，每条结论带证据锚点 + 触发该指标的评论样本
    
    输出两个东西：
    1. insights[] —— 前端直接渲染的结构化结论（卡片式 UI）
       每条带 sample_reviews（前 5 条触发评论），前端可一键联动 BM25 搜索
    2. llm_context —— 压缩后的摘要（喂给 LLM 用，控制在 ~3000 token 内）
    """
    wzq = "王者万象棋"
    jcc = "金铲铲之战"
    
    overview = data.get("overview", {})
    persona = data.get("player_persona", {})
    word_freq = data.get("word_freq", {})
    llm_phrases = data.get("llm_phrases", {})  # 🆕 LLM 原因短语（优先于裸词频）
    app_stats = data.get("app_stats", {})
    mechanic = data.get("mechanic_compare", [])

    insights = []

    # —— 辅助：收集触发某 insight 的评论样本 ——
    def _samples(game_name, tags=None, keywords=None, stages=None, score_max=None, score_min=None, limit=5):
        """
        按条件过滤 df，返回前 N 条匹配评论。
        tags:     用户标签名列表（匹配 USER_TAG_RULES 的 patterns）
        keywords: 关键词列表（评论内容里包含）
        stages:   阶段名列表（匹配"玩过阶段"或我们自己的分桶）
        score_min/max: 评分范围
        """
        gdf = df[df["游戏名称"] == game_name].copy()
        masks = []

        if tags:
            tag_patterns = []
            for tag_name in tags:
                # 从 config 里找对应的正则 pattern
                for tname, patterns in USER_TAG_RULES:
                    if tname == tag_name:
                        tag_patterns.extend(patterns)
                        break
            if tag_patterns:
                # 任一 pattern 命中即算
                mask = gdf["评论内容"].astype(str).apply(
                    lambda txt: any(re.search(p, txt, re.IGNORECASE) for p in tag_patterns)
                )
                masks.append(mask)

        if keywords:
            mask = gdf["评论内容"].astype(str).apply(
                lambda txt: any(kw.lower() in txt.lower() for kw in keywords)
            )
            masks.append(mask)

        if stages:
            for s in stages:
                if "期待" in s:
                    masks.append(gdf["玩过阶段"].astype(str).str.contains("期待", na=False))
                elif "深度" in s:
                    masks.append(gdf["玩过时长_小时"] >= 50)
                elif "新手" in s:
                    masks.append((gdf["玩过时长_小时"] < 10) & 
                                 ~gdf["玩过阶段"].astype(str).str.contains("期待", na=False))

        if score_max is not None:
            masks.append(gdf["评分"] <= score_max)
        if score_min is not None:
            masks.append(gdf["评分"] >= score_min)

        final = gdf
        for m in masks:
            final = final[m]

        # 去重 + 取前 N 条
        samples = []
        for _, row in final.head(limit).iterrows():
            samples.append({
                "review_id": str(row.get("评论ID", "")),
                "content": str(row["评论内容"])[:200],
                "score": int(row["评分"]),
                "ups": int(pd.to_numeric(row.get("点赞数", 0), errors="coerce") or 0),
                "game": game_name,
            })
        return samples

    # —— 研究目标 1：万象棋核心受众 ——
    for game_name in [wzq, jcc]:
        p = persona.get(game_name, {})
        tags = {t["name"]: t["ratio"] for t in p.get("tag_distribution", [])}
        stages = {s["stage"]: s for s in p.get("stage_stats", [])}

        if game_name == wzq:
            # 结论：核心受众是谁
            ip_ratio = tags.get("王者IP老粉", 0)
            aosj_ratio = tags.get("自走棋老手", 0)
            # 必须按标签名显式取：金铲铲标签榜首位是「关注平衡/数值」，取 [0] 会把它误当成 LOL 老玩家占比
            jcc_tags = {t["name"]: t["ratio"] for t in (persona.get(jcc, {}).get("tag_distribution") or [])}
            lol_ratio = jcc_tags.get("LOL老玩家", 0)
            if ip_ratio > 0:
                insights.append({
                    "dimension": "受众画像", "target": "王者万象棋",
                    "title": f"核心受众是王者 IP 老粉（{ip_ratio}%）",
                    "search_query": "王者 荣耀 情怀",
                    "severity": "info",
                    "detail": f"万象棋评论者中 {ip_ratio}% 提到王者/荣耀/情怀，{aosj_ratio}% 是自走棋老手；"
                              f"金铲铲侧 LOL 老玩家占 {lol_ratio}%。万象棋受众更偏王者 IP 圈层。",
                    "evidence": {
                        "field": "player_persona.tag_distribution",
                        "metrics": [{"k": "王者IP老粉", "v": f"{ip_ratio}%"}, 
                                    {"k": "自走棋老手", "v": f"{aosj_ratio}%"},
                                    {"k": f"{jcc} LOL老玩家", "v": f"{lol_ratio}%"}],
                        "sample_reviews": _samples(wzq, tags=["王者IP老粉"], limit=5),
                    }
                })

            # 结论：首发阶段玩家画像
            expect_ratio = stages.get("期待者", {}).get("ratio", 0)
            deep_ratio = stages.get("深度 (>50h)", {}).get("ratio", 0)
            newbie_ratio = stages.get("新手 (<10h)", {}).get("ratio", 0)
            mid_ratio = stages.get("中级 (10-50h)", {}).get("ratio", 0)
            if expect_ratio > 0 or deep_ratio > 0:
                insights.append({
                    "dimension": "首发特征", "target": "王者万象棋",
                    "title": f"深度玩家占比偏低（{deep_ratio}%）",
                    "search_query": "老玩家 深度 新手",
                    "severity": "warning",
                    "detail": f"万象棋上线 {p.get('lifecycle', {}).get('days_since_launch', '?')} 天。"
                              f"评论者构成：期待者 {expect_ratio}%、新手 {newbie_ratio}%、"
                              f"中级 {mid_ratio}%、深度 {deep_ratio}%。口碑尚未经过深度玩家检验。",
                    "evidence": {
                        "field": "player_persona.stage_stats",
                        "metrics": [{"k": "期待者", "v": f"{expect_ratio}%"},
                                    {"k": "新手", "v": f"{newbie_ratio}%"},
                                    {"k": "深度", "v": f"{deep_ratio}%"}],
                        "sample_reviews": _samples(wzq, stages=["深度"], limit=5),
                    }
                })

    # —— 研究目标 2：万象棋核心诉求（痛点 + 正面）——
    for game_name, severity_label in [(wzq, "high"), (jcc, "medium")]:
        p = persona.get(game_name, {})
        tags = {t["name"]: t["ratio"] for t in p.get("tag_distribution", [])}
        words_neg = word_freq.get(game_name, {}).get("negative", [])
        words_pos = word_freq.get(game_name, {}).get("positive", [])

        # 🆕 LLM 原因短语（优先）：LLM 归纳「具体短语」+ 规则引擎锚定真实占比
        #    拿不到时（无 key / 失败）回退到裸词频逻辑
        neg_phrases = llm_phrases.get(game_name, {}).get("negative", [])
        pos_phrases = llm_phrases.get(game_name, {}).get("positive", [])

        # 核心痛点
        pain_tag = None
        pain_ratio = 0
        for tag_name in ["关注ELO/控牌", "关注外挂/脚本", "关注服务器/技术", "关注平衡/数值"]:
            r = tags.get(tag_name, 0)
            if r > pain_ratio:
                pain_ratio = r
                pain_tag = tag_name

        if pain_tag and pain_ratio >= 10:
            sq = pain_tag.replace("关注", "").replace("/", " ")
            if neg_phrases:
                # —— 走 LLM 短语：具体归因（如「阵容与棋手绑定过深」）+ 真实占比 ——
                top_neg = neg_phrases[:3]
                top_neg_plain = [x["phrase"] for x in top_neg]
                top_neg_names = [f"{x['phrase']}（占差评 {x['ratio']}）" for x in top_neg]
                insights.append({
                    "dimension": "核心痛点", "target": game_name,
                    "title": f"「{pain_tag.replace('关注', '')}」提及率 {pain_ratio}%",
                    "search_query": f"{sq} " + " ".join(x["phrase"] for x in top_neg[:2]),
                    "severity": severity_label,
                    "detail": f"{game_name} {pain_ratio}% 的评论提到「{pain_tag}」，"
                              f"热门差评的 Top 3 原因：{'；'.join(top_neg_plain)}。",
                    "evidence": {
                        "field": "llm_phrases.negative（LLM 归纳短语 + 规则引擎锚定占比）",
                        "metrics": [{"k": pain_tag, "v": f"{pain_ratio}%"},
                                    {"k": "差评Top3原因", "v": top_neg_names}],
                        # 样本必须是「触发本条结论」的评论：即含 pain_tag 的差评，
                        # 而不是 Top1 短语的样本（否则标题讲 ELO、样本讲阵容，读者会觉得无关）
                        "sample_reviews": _samples(game_name, tags=[pain_tag], score_max=2, limit=5),
                    }
                })
            else:
                # —— 兜底：裸词频（无 LLM 短语时）——
                # 二次过滤：排除游戏名等无信息主题词（词云保留，结论不显示）
                words_neg_clean = [w for w in words_neg if w["name"] not in INSIGHT_NOISE_WORDS]
                top_neg = words_neg_clean[0]["name"] if words_neg_clean else (words_neg[0]["name"] if words_neg else "—")
                top_neg2 = words_neg_clean[1]["name"] if len(words_neg_clean) > 1 else (words_neg_clean[0]["name"] if len(words_neg_clean) == 1 else "—")
                insights.append({
                    "dimension": "核心痛点", "target": game_name,
                    "title": f"「{pain_tag.replace('关注', '')}」提及率 {pain_ratio}%",
                    "search_query": f"{sq} {top_neg} {top_neg2}",
                    "severity": severity_label,
                    "detail": f"{game_name} {pain_ratio}% 的评论提到「{pain_tag}」，"
                              f"差评高频词 Top 2：{top_neg}、{top_neg2}。",
                    "evidence": {
                        "field": "player_persona + word_freq",
                        "metrics": [{"k": pain_tag, "v": f"{pain_ratio}%"},
                                    {"k": "差评Top2", "v": f"{top_neg}、{top_neg2}"}],
                        "sample_reviews": _samples(game_name, tags=[pain_tag], score_max=2, limit=5),
                    }
                })

        # 正面亮点
        if pos_phrases:
            # —— 走 LLM 短语：玩家认可的具体原因 ——
            top_pos = pos_phrases[:3]
            top_pos_plain = [x["phrase"] for x in top_pos]
            top_pos_names = [f"{x['phrase']}（占好评 {x['ratio']}）" for x in top_pos]
            insights.append({
                "dimension": "正面反馈", "target": game_name,
                "title": f"最受认可：{top_pos[0]['phrase']}",
                "search_query": top_pos[0]["phrase"],
                "severity": "info",
                "detail": f"{game_name}好评最集中的 Top 3 原因：{'；'.join(top_pos_plain)}。",
                "evidence": {
                    "field": "llm_phrases.positive（LLM 归纳短语 + 规则引擎锚定占比）",
                    "metrics": [{"k": "好评Top3原因", "v": top_pos_names}],
                    "sample_reviews": top_pos[0].get("sample_reviews") or
                                      _samples(game_name, keywords=[top_pos[0]["phrase"]], score_min=4, limit=5),
                }
            })
        elif words_pos:
            # —— 兜底：裸词频（无 LLM 短语时）——
            # 二次过滤：排除游戏名等无信息主题词
            words_pos_clean = [w for w in words_pos if w["name"] not in INSIGHT_NOISE_WORDS]
            top_pos = words_pos_clean[0]["name"] if words_pos_clean else (words_pos[0]["name"] if words_pos else "—")
            top_pos2 = words_pos_clean[1]["name"] if len(words_pos_clean) > 1 else (words_pos_clean[0]["name"] if len(words_pos_clean) == 1 else "—")
            top_pos3 = words_pos_clean[2]["name"] if len(words_pos_clean) > 2 else (
                words_pos_clean[1]["name"] if len(words_pos_clean) == 2 else (words_pos_clean[0]["name"] if len(words_pos_clean) == 1 else "—")
            )
            insights.append({
                "dimension": "正面反馈", "target": game_name,
                "title": f"最受认可：{top_pos}",
                "search_query": f"{top_pos} {top_pos2}",
                "severity": "info",
                "detail": f"{game_name}正面评论高频词 Top 3：{top_pos}、{top_pos2}、{top_pos3}。",
                "evidence": {
                    "field": "word_freq.positive",
                    "metrics": [{"k": "正面Top3", "v": [top_pos, top_pos2, top_pos3]}],
                    "sample_reviews": _samples(game_name, keywords=[top_pos, top_pos2], score_min=4, limit=5),
                }
            })

    # —— 研究目标 3：竞品对比 & 可借鉴经验 ——
    wzq_p = persona.get(wzq, {})
    jcc_p = persona.get(jcc, {})
    wzq_over = overview.get(wzq, {})
    jcc_over = overview.get(jcc, {})

    # 深度玩家留存对比
    wzq_deep = next((s["ratio"] for s in wzq_p.get("stage_stats", []) if "深度" in s["stage"]), 0)
    jcc_deep = next((s["ratio"] for s in jcc_p.get("stage_stats", []) if "深度" in s["stage"]), 0)
    jcc_avg = jcc_over.get("avg_score", 0)
    wzq_avg = wzq_over.get("avg_score", 0)

    insights.append({
        "dimension": "竞品经验", "target": "王者万象棋",
        "title": f"金铲铲深度玩家 {jcc_deep}% vs 万象棋 {wzq_deep}%",
        "search_query": "老玩家 匹配 ELO 公平",
        "severity": "medium",
        # 评分统一折算到 10 分制，避免与对比表里的 /10 口径并排时被误读
        "detail": f"金铲铲运营 5 年，深度玩家（>50h）占 {jcc_deep}%，抽样平均 {round(jcc_avg * 2, 1)}/10；"
                  f"万象棋深度玩家 {wzq_deep}%，抽样平均 {round(wzq_avg * 2, 1)}/10。"
                  f"金铲铲的匹配公平性维护与反作弊投入，是其老玩家留存的关键。",
        "evidence": {
            "field": "player_persona + overview",
            "metrics": [{"k": f"{wzq} 深度", "v": f"{wzq_deep}%"},
                        {"k": f"{jcc} 深度", "v": f"{jcc_deep}%"},
                        {"k": f"{jcc} 抽样平均", "v": f"{round(jcc_avg * 2, 1)}/10"}],
            "sample_reviews": _samples(jcc, stages=["深度"], limit=3) + _samples(wzq, stages=["深度"], limit=2),
        }
    })

    # 官方评分 vs 抽样评分交叉验证
    if wzq in app_stats and jcc in app_stats:
        wzq_official = app_stats[wzq].get("rating", 0)
        jcc_official = app_stats[jcc].get("rating", 0)
        insights.append({
            "dimension": "数据交叉验证", "target": "王者万象棋",
            "title": f"官方评分与抽样评分的口径对比",
            "severity": "info",
            "detail": f"万象棋官方评分 {wzq_official}/10（全量加权），抽样平均分 {round(wzq_avg * 2, 1)}/10"
                      f"（热度 Top500 简单平均）；金铲铲官方 {jcc_official}/10，抽样 {round(jcc_avg * 2, 1)}/10。"
                      f"两者口径不同（全量加权 vs 热度抽样），不可直接比较高低。",
            "evidence": {
                "field": "app_stats + overview",
                "metrics": [{"k": f"{wzq} 官方", "v": f"{wzq_official}/10"},
                            {"k": f"{wzq} 抽样×2", "v": f"{round(wzq_avg*2, 1)}/10"},
                            {"k": f"{jcc} 官方", "v": f"{jcc_official}/10"}],
                "sample_reviews": [],  # 交叉验证不绑定特定评论
            }
        })

    # —— 研究目标 4：行动建议（规则化）——
    recommendations = []
    pain_item = next((i for i in insights if i["dimension"] == "核心痛点" and i["target"] == wzq), None)
    # 建议标题/动作必须与真实痛点口径一致，
    # 否则会出现「标题讲平衡、正文讲阵容、动作讲 ELO」的错位。
    PAIN_ACTION_MAP = {
        "ELO/控牌":   ("优先缓解匹配公平性争议", "公开匹配规则与分档胜率分布，降低「被控牌」的感知"),
        "外挂/脚本":  ("优先加强反作弊处置", "提升外挂识别与举报处置时效，公示处罚结果"),
        "服务器/技术": ("优先修复稳定性问题", "针对闪退、卡屏、掉线做专项修复并周更跟进"),
        "平衡/数值":  ("优先处理平衡与数值问题", "针对被集中吐槽的阵容与棋手强度做数值回调，并公示调整依据"),
    }
    if pain_item and pain_item.get("severity") == "high":
        # 从证据锚点里取真实痛点标签（如「关注平衡/数值」→「平衡/数值」）
        pain_label = next((m["k"].replace("关注", "")
                           for m in pain_item.get("evidence", {}).get("metrics", [])
                           if m.get("k", "").startswith("关注")), "核心痛点")
        rec_title, rec_action = PAIN_ACTION_MAP.get(
            pain_label, (f"优先处理{pain_label}问题", "按差评归因确定迭代优先级"))
        recommendations.append({
            "priority": "P0 紧急", "icon": "🔴", "target": wzq,
            "from_dimension": "核心痛点",   # 供首屏「核心发现」摘要回链对应结论
            "title": rec_title,
            "action": rec_action,
            "rationale": pain_item["detail"],
            "success_metric": f"目标：差评中「{pain_label}」相关占比降至 < 10%",
        })

    audience_item = next((i for i in insights if i["dimension"] == "受众画像" and i["target"] == wzq), None)
    if audience_item:
        recommendations.append({
            "priority": "P1 重要", "icon": "🟡", "target": wzq,
            "from_dimension": "受众画像",
            "title": "首发期强化王者 IP 联动",
            "action": "上线王者经典皮肤作为限定奖励、与王者荣耀联动做排位奖励互通",
            "rationale": audience_item["detail"],
            "success_metric": "目标：IP 老粉玩家占比从当前值提升 10%",
        })

    competitor_item = next((i for i in insights if i["dimension"] == "竞品经验"), None)
    if competitor_item:
        recommendations.append({
            "priority": "P1 重要", "icon": "🟡", "target": wzq,
            "title": "建立玩家反馈快速响应机制",
            "action": "每周 Top 10 差评关键词分析 → 产品迭代优先级",
            "rationale": competitor_item["detail"],
            "success_metric": "目标：月更频次 → 周更",
        })

    recommendations.append({
        "priority": "P2 优化", "icon": "🟢", "target": wzq,
        "title": "深度合作自走棋社区",
        "action": "邀请 B 站自走棋 UP 主做万象棋 vs 金铲铲对比评测",
        "rationale": "万象棋受众偏离纯自走棋圈，需要在自走棋社区渗透",
        "success_metric": "目标：自走棋老手标签占比提升 5%",
    })

    # —— 分区归属：本报告以「王者万象棋」为主线，金铲铲之战是作为基准的竞品 ——
    # main      = 万象棋自身的问题/受众/亮点 → 承载结论与行动建议
    # benchmark = 金铲铲侧数据 & 跨游戏对照 → 只做"镜鉴"，不单独出建议
    BENCHMARK_DIMENSIONS = {"竞品经验", "数据交叉验证"}
    for item in insights:
        item["group"] = ("benchmark"
                         if item["dimension"] in BENCHMARK_DIMENSIONS or item["target"] == jcc
                         else "main")

    # 镜鉴条目补一句"对万象棋意味着什么"，否则读者看完金铲铲的数据不知道所以然
    _wzq_pain = next((i for i in insights if i["dimension"] == "核心痛点" and i["target"] == wzq), None)
    _wzq_pos = next((i for i in insights if i["dimension"] == "正面反馈" and i["target"] == wzq), None)
    for item in insights:
        if item["group"] != "benchmark":
            continue
        if item["dimension"] == "竞品经验":
            item["mirror"] = ("万象棋应在首发期就把「匹配公平 + 反作弊」当作留存基建投入，"
                              "而不是等深度玩家流失后再补救。")
        elif item["dimension"] == "数据交叉验证":
            item["mirror"] = ("抽样是热度 Top500 的简单平均，官方是全量加权，两者口径不同，"
                              "仅作交叉参考，不作为评分高低的依据。")
        elif item["dimension"] == "核心痛点" and _wzq_pain:
            item["title"] = f"竞品镜鉴：{item['title']}"
            item["mirror"] = ("同类问题万象棋当前提及率低于金铲铲，但金铲铲运营 5 年仍未消化 —— "
                              "说明这类问题不会随版本迭代自动消失，需在首发期就纳入迭代主线。")
        elif item["dimension"] == "正面反馈" and _wzq_pos:
            item["title"] = f"竞品镜鉴：{item['title']}"
            item["mirror"] = "金铲铲靠这一点支撑了 5 年长线留存，是万象棋在成熟期需要补齐的能力。"

    return {
        "insights": insights,
        "recommendations": recommendations,
        # 🆕 首屏「核心发现」摘要（只看万象棋主线，供不下钻的决策者一屏读完）
        "key_findings": _build_key_findings(insights, recommendations),
        # 压缩后的上下文（喂给 LLM 用，控制 token）
        "llm_context": _build_llm_context(data, insights, recommendations),
    }


def _build_key_findings(insights, recommendations, top_n=3):
    """
    生成首屏「核心发现」摘要。

    只取 main 组（万象棋主线），按严重度降序排，每条尽量回链到对应的行动建议。
    —— 报告改成漏斗式（结论在最末）后，摘要让决策者不必滚到底就能看到结论。
    —— 控制在 3 条：一屏读完，更多细节留给模块 ⑤ 的完整结论。
    """
    SEV_RANK = {"high": 0, "warning": 1, "medium": 2, "info": 3}
    main_items = sorted([i for i in insights if i.get("group") == "main"],
                        key=lambda i: SEV_RANK.get(i.get("severity"), 9))

    findings = []
    for item in main_items[:top_n]:
        rec = next((r for r in recommendations if r.get("from_dimension") == item["dimension"]), None)
        findings.append({
            "severity": item.get("severity", "info"),
            "dimension": item.get("dimension", ""),
            "title": item.get("title", ""),
            "detail": item.get("detail", ""),
            "action": f"{rec['priority']}｜{rec['title']}" if rec else "",
        })
    return findings


def _build_llm_context(data, insights, recommendations):
    """
    把 analysis.json 的关键数据压缩成适合 LLM 消费的结构化摘要
    目标：控制在 ~3000 token 内（压缩率 > 90%）
    """
    wzq, jcc = "王者万象棋", "金铲铲之战"
    overview = data.get("overview", {})
    persona = data.get("player_persona", {})
    word_freq = data.get("word_freq", {})
    app_stats = data.get("app_stats", {})
    mechanic = data.get("mechanic_compare", [])

    # 压缩成人类可读的简表
    summary_lines = [f"【角色设定】本报告以「{wzq}」为分析主体，"
                     f"「{jcc}」是作为基准的竞品；结论与建议只针对{wzq}。",
                     "\n【基础对比】"]
    for gn in [wzq, jcc]:
        o = overview.get(gn, {})
        p = persona.get(gn, {})
        ps = app_stats.get(gn, {})
        lc = p.get("lifecycle", {})
        summary_lines.append(
            f"  {gn}（上线{lc.get('days_since_launch', '?')}天，{lc.get('stage', '')}）: "
            f"官方评分 {ps.get('rating', 0)}/10（全量加权）, "
            f"抽样平均分 {round(o.get('avg_score', 0) * 2, 1)}/10（热度 Top{o.get('review_count', 0)} 简单平均）, "
            f"评论 {o.get('review_count', 0)} 条"
        )

    summary_lines.append("\n【核心痛点】")
    for item in insights:
        if item["dimension"] == "核心痛点":
            summary_lines.append(f"  [{item['target']}] {item['title']} — {item['detail']}")

    summary_lines.append("\n【受众画像】")
    for item in insights:
        if item["dimension"] == "受众画像":
            summary_lines.append(f"  {item['title']} — {item['detail']}")

    summary_lines.append("\n【竞品镜鉴】（金铲铲之战在本报告中是基准竞品，不是被分析对象）")
    for item in insights:
        if item["dimension"] in ("竞品经验", "数据交叉验证") or (
                item["dimension"] == "正面反馈" and item["target"] != "王者万象棋"):
            line = f"  {item['title']} — {item['detail']}"
            if item.get("mirror"):
                line += f" 【对万象棋意味着】{item['mirror']}"
            summary_lines.append(line)

    summary_lines.append("\n【机制对比】")
    for row in mechanic:
        if isinstance(row, list) and len(row) >= 3:
            summary_lines.append(f"  {row[0]}: {row[1]} vs {row[2]}")

    summary_lines.append("\n【规则引擎建议】")
    for r in recommendations:
        summary_lines.append(f"  [{r['priority']}] {r['title']} → {r['action']}")

    # 附带 Top 5 正面/负面原因（优先 LLM 短语，无则回退高频词）
    llm_phrases = data.get("llm_phrases", {})
    summary_lines.append("\n【差评原因 Top5】")
    for gn in [wzq, jcc]:
        phr = [p["phrase"] for p in llm_phrases.get(gn, {}).get("negative", [])[:5]]
        if not phr:
            phr = [w["name"] for w in word_freq.get(gn, {}).get("negative", [])[:5]]
        summary_lines.append(f"  {gn}: {phr}")
    summary_lines.append("\n【好评原因 Top5】")
    for gn in [wzq, jcc]:
        phr = [p["phrase"] for p in llm_phrases.get(gn, {}).get("positive", [])[:5]]
        if not phr:
            phr = [w["name"] for w in word_freq.get(gn, {}).get("positive", [])[:5]]
        summary_lines.append(f"  {gn}: {phr}")

    return "\n".join(summary_lines)


# =========================================================
# 5. 主流程
# =========================================================
def main():
    import argparse
    import shutil
    import glob as _glob

    parser = argparse.ArgumentParser(description="TapTap 竞品分析 - 数据预处理")
    parser.add_argument("--input", help="指定 CSV 路径，默认自动取 data/ 下最新的")
    parser.add_argument("--version", help="自定义版本 ID，默认从 CSV 文件名提取")
    args = parser.parse_args()

    # 确定输入 CSV
    if args.input:
        csv_path = args.input
    else:
        csv_path = find_latest_csv()

    # 兜底：如果 data/ 还没建好，找根目录的 reviews.csv（兼容老用户）
    if not csv_path or not os.path.exists(csv_path):
        legacy = os.path.join(BASE_DIR, "reviews.csv")
        if os.path.exists(legacy):
            csv_path = legacy
        else:
            print(f"❌ 找不到任何 CSV 数据！")
            print(f"   请先运行: python main.py  （会把 CSV 存到 data/ 下）")
            sys.exit(1)

    version_id = args.version or csv_to_version_id(csv_path)

    print("=" * 60)
    print("  TapTap 竞品分析 - 数据预处理")
    print("=" * 60)
    print(f"  📂 CSV 输入: {csv_path}")
    print(f"  📌 版本 ID : {version_id}")

    # Step 0: 爬 TapTap App 详情（官方统计数据）
    app_stats = utils.fetch_all_app_stats()

    # Step 1: 加载评论 CSV
    df = load_and_clean(csv_path)

    # Step 2-9: 各模块统计
    data = {
        "version_id": version_id,
        "schema_version": SCHEMA_VERSION,
        "data_collected_at": version_id_to_time(version_id),  # 🆕 数据采集时间（CSV 时间戳）
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),  # 分析生成时间
        "app_stats": app_stats,
        "overview": compute_overview(df),
        "rating_dist": compute_rating_dist(df),
        "playtime_score": compute_playtime_score(df),
        "time_trend": compute_time_trend(df),
        "word_freq": compute_word_freqs(df),
        "top_reviews": compute_top_reviews(df),
        "player_persona": compute_player_persona(df),
        "mechanic_compare": MECHANIC_COMPARE,
        "bm25": compute_bm25_index(df),
    }

    # Step 10: LLM 原因短语抽取（LLM 归纳短语 + 规则引擎锚定真实占比）
    #   无 API Key / 开关关闭 / 调用失败 → 返回 {}，结论自动回退裸词频逻辑
    try:
        data["llm_phrases"] = build_llm_phrases(df, version_id)
    except Exception as e:  # noqa: BLE001
        print(f"[LLM短语] ⚠️  抽取失败，已降级为词频逻辑：{e}")
        data["llm_phrases"] = {}

    # Step 10.5: 阶段 × 原因短语矩阵（依赖 llm_phrases，写回 player_persona.stage_stats）
    attach_stage_phrases(df, data)
    # 数据对比表（依赖 llm_phrases，官方数据 + 抽样统计自动生成）
    data["data_compare"] = compute_data_compare(data)

    # Step 11: 规则化分析引擎（可追溯结论 + LLM 上下文）
    insights_result = analyze_insights(df, data)
    data["insights"] = insights_result["insights"]
    data["recommendations"] = insights_result["recommendations"]
    data["key_findings"] = insights_result["key_findings"]   # 🆕 首屏「核心发现」摘要
    data["llm_context"] = insights_result["llm_context"]
    print(f"[规则引擎] 生成 {len(insights_result['insights'])} 条结论 + "
          f"{len(insights_result['recommendations'])} 条建议 + "
          f"LLM 上下文 {len(insights_result['llm_context'])} 字符")

    # —— 输出 0：把体积最大的检索语料 bm25.reviews 拆到独立文件 ——
    # 原因：整份 JSON 约 3.2MB，其中 bm25.reviews 占 ~72%，而它只在「检索区搜索」
    #      和「点样本展开原文」时用到，首屏渲染完全不需要。放在主文件里会让首屏
    #      必须等 3MB 下载完才渲染（网络差时直接卡死/超时）。
    # 拆分后主 JSON 只剩 idf/avgdl/total_docs（约 100KB），语料改为前端按需懒加载。
    bm25 = data.get("bm25") or {}
    bm25_reviews = bm25.pop("reviews", [])
    retrieval_path = os.path.join(ANALYSES_DIR, f"bm25_{version_id}.json")
    root_retrieval_path = os.path.join(DASHBOARD_DIR, "bm25.json")

    # —— 输出 1：多版本 JSON（dashboard/analyses/analysis_{version_id}.json）——
    os.makedirs(ANALYSES_DIR, exist_ok=True)
    version_json_path = os.path.join(ANALYSES_DIR, f"analysis_{version_id}.json")
    with open(version_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # —— 输出 1.5：检索索引（紧凑格式，仅供前端懒加载，不需要人读）——
    with open(retrieval_path, "w", encoding="utf-8") as f:
        json.dump({"version_id": version_id, "reviews": bm25_reviews},
                  f, ensure_ascii=False, separators=(",", ":"))

    # —— 输出 2：兼容当前版本（dashboard/analysis.json + dashboard/bm25.json）——
    shutil.copy(version_json_path, CURRENT_JSON_PATH)
    shutil.copy(retrieval_path, root_retrieval_path)

    # —— 输出 3：versions.json（前端下拉框读这个）——
    os.makedirs(DASHBOARD_DIR, exist_ok=True)

    # 先读已有的 versions.json，没有就新建
    versions = {"current": version_id, "available": []}
    if os.path.exists(VERSIONS_PATH):
        try:
            with open(VERSIONS_PATH, "r", encoding="utf-8") as f:
                versions = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass  # 损坏就重建

    # 刷新 available：扫描 analyses/ 目录下所有版本
    available = []
    # 前端据此判断该版本模块是否齐全（缺 llm_phrases / data_compare 等 → 显示降级提示）
    TRACKED_MODULES = ("llm_phrases", "data_compare", "insights", "recommendations", "key_findings", "bm25")
    for p in sorted(_glob.glob(os.path.join(ANALYSES_DIR, "analysis_*.json"))):
        vid = os.path.basename(p).replace("analysis_", "").replace(".json", "")
        stat = os.stat(p)
        vdate = version_id_to_time(vid)  # 友好标签：20260923_143000 → 2026-09-23 14:30
        # 统计该版本有多少条评论 + 记录模块齐全度
        d = {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            review_count = sum(g.get("total_reviews", 0) for g in d.get("player_persona", {}).values())
        except Exception:
            review_count = 0
        available.append({
            "id": vid,
            "label": f"{vdate} · {review_count}条 · {stat.st_size // 1024}KB",
            "size": stat.st_size,
            "schema_version": d.get("schema_version", 0),
            "data_collected_at": d.get("data_collected_at", vdate),
            "generated_at": d.get("generated_at", vdate),
            "modules": [k for k in TRACKED_MODULES if d.get(k)],
        })

    versions["available"] = available
    versions["current"] = version_id
    versions["schema_version"] = SCHEMA_VERSION      # 🆕 前端据此判断新旧版本是否可比
    versions["current_schema_modules"] = [k for k in TRACKED_MODULES if data.get(k)]

    with open(VERSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(versions, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"✅ 版本 {version_id} 已生成")
    print(f"   📊 分析 JSON: {version_json_path}")
    print(f"   🔎 检索索引 : {retrieval_path}（{len(bm25_reviews)} 条，前端按需懒加载）")
    print(f"   🔗 当前副本 : {CURRENT_JSON_PATH} + {root_retrieval_path}")
    print(f"   📋 版本清单 : {VERSIONS_PATH}")
    print(f"   📦 版本列表 : {len(available)} 个版本可用")
    print("=" * 60)


if __name__ == "__main__":
    main()
