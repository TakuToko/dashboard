"""
llm_phrases.py — LLM 评论原因短语抽取 + 规则锚定
--------------------------------------------------
解决问题：词云只显示中性名词（阵容、棋手），缺少具体归因
         （阵容与棋手绑定过深、打法死板、对局冗长）。

两阶段设计（核心：LLM 只归纳短语，规则引擎数占比，LLM 不碰数字）：
  阶段 A（LLM）  ：把最热门评论归纳成「具体短语 + 真实别名 + 关键词」
  阶段 B（规则）  ：用别名/关键词回扫全量评论，统计真实命中数与占比

阶段 A 产物落盘缓存到 data/phrase_cache_v4_{version_id}.json，
重跑预处理时若缓存存在直接复用，不重复调用 LLM（省时省钱 + 结论稳定）。
"""

import json
import os
import re
import sys
import time

import jieba
import pandas as pd

# —— 路径引导：让本模块可独立 import config ——
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_ENDPOINT,
    DEEPSEEK_MODEL,
    LLM_PHRASE_ENABLED,
    LLM_PHRASE_MAX_REVIEWS,
    LLM_PHRASE_BATCH_SIZE,
    LLM_PHRASE_TOP_N,
    CUSTOM_STOPWORDS,
    DOMAIN_WORDS,
)

DATA_DIR = os.path.join(BASE_DIR, "data")


# =========================================================
# 1. 调用 DeepSeek（与前端保持一致的参数约定）
# =========================================================
def _call_llm(messages, retries=2, max_tokens=2000):
    """调用 DeepSeek，返回 content 文本。失败抛异常。"""
    import requests

    body = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.2,          # 低温度，保证归纳结果稳定
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},  # 关闭思考模式，避免 content 为空
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }

    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                DEEPSEEK_ENDPOINT, headers=headers,
                data=json.dumps(body), timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
            # content 为空时兜底 reasoning_content
            content = msg.get("content") or msg.get("reasoning_content") or ""
            if not content.strip():
                raise ValueError("LLM 返回空内容")
            # 输出被 max_tokens 掐断时明确告警：JSON 会不完整，
            # 交给 _parse_phrase_json 去抢救已生成的完整条目
            if choice.get("finish_reason") == "length":
                print(f"      ⚠️  输出触及 max_tokens={max_tokens} 被截断，将抢救已完成的条目")
            return content
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                time.sleep(2)
    raise RuntimeError(f"DeepSeek 调用失败：{last_err}")


# =========================================================
# 2. 解析 LLM 返回的 JSON（容忍 ```json 围栏 / 前后废话）
# =========================================================
def _parse_phrase_json(text):
    """从 LLM 返回文本里抽出 [{"phrase":..., "aliases":[...]}, ...]"""
    # 去掉 markdown 代码围栏
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    # 截取第一个 [ 到最后一个 ]（被 max_tokens 截断时可能没有收尾的 ]）
    start, end = text.find("["), text.rfind("]")
    if start == -1:
        raise ValueError(f"无法从返回中定位 JSON 数组：{text[:200]}")
    candidate = text[start:end + 1] if end > start else text[start:]

    try:
        arr = json.loads(candidate)
    except json.JSONDecodeError as e:
        # 输出被截断 → 逐个抢救已经完整生成的 {...} 对象（aliases 用 [] 不涉及花括号，可安全正则）
        salvaged = []
        for chunk in re.findall(r"\{[^{}]*\}", candidate):
            try:
                salvaged.append(json.loads(chunk))
            except json.JSONDecodeError:
                continue
        if not salvaged:
            raise ValueError(f"JSON 解析失败且无完整条目可抢救：{e}") from e
        print(f"      ⚠️  JSON 不完整，已抢救出 {len(salvaged)} 个完整条目（丢弃被截断的部分）")
        arr = salvaged

    if not isinstance(arr, list):
        raise ValueError("返回的不是数组")

    cleaned = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue
        aliases = item.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        aliases = [str(a).strip() for a in aliases if str(a).strip()]

        keywords = item.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        keywords = [str(k).strip() for k in keywords if str(k).strip()]

        cleaned.append({"phrase": phrase, "aliases": aliases, "keywords": keywords})
    return cleaned


# =========================================================
# 2.5 文本匹配（锚定阶段的核心）
# —— LLM 给的别名常是"书面化改写"或"多概念拼接串"，做整串字面匹配会几乎全部落空
#    （实测："打发时间"在评论里出现 15 次，而别名"打发时间休闲解压"0 次命中）。
#    所以匹配放宽为三级，任一成立即算命中，兼顾召回与"不能空口命中"（需 ≥2 个信号）。
# =========================================================
_JIEBA_READY = False


def _ensure_jieba():
    """注册领域词典（幂等），保证别名切词与词频统计口径一致"""
    global _JIEBA_READY
    if not _JIEBA_READY:
        for w in DOMAIN_WORDS:
            jieba.add_word(w)
        _JIEBA_READY = True


def _terms(text):
    """把别名/关键词切成实词集合（去停用词、去单字）"""
    _ensure_jieba()
    out = set()
    for w in jieba.lcut(str(text)):
        w = w.strip()
        if len(w) < 2 or w in CUSTOM_STOPWORDS:
            continue
        out.add(w)
    return out


def _prepare_matcher(aliases, keywords):
    """
    把别名/关键词预切成词（每条短语只切一次，避免在逐条评论的循环里重复 jieba 分词）。
    返回 (别名小写列表, [(实词集合, 需命中数)], 关键词小写列表)
    """
    aliases_lower = [a.lower() for a in aliases]
    token_rules = []
    for a in aliases:
        toks = _terms(a)
        if len(toks) >= 2:
            token_rules.append((toks, max(2, (len(toks) + 1) // 2)))
    keywords_lower = [k.lower() for k in keywords if len(k) >= 2]
    return aliases_lower, token_rules, keywords_lower


def _hit(text_lower, matcher):
    """
    判定一条评论是否命中某短语：
      1) 任一别名整串字面命中（别名本身若是评论里的真实片段，这条最快）
      2) 任一别名分词后命中「法定人数」个实词（2 词需 2 个、5 词需 3 个…）
         —— 覆盖"多概念拼接串"，同时避免长别名靠两个常见词就误命中
      3) ≥2 个关键词同时命中（覆盖"口语改写"）
    """
    aliases_lower, token_rules, keywords_lower = matcher

    for a in aliases_lower:
        if a in text_lower:
            return True

    for toks, need in token_rules:
        if sum(1 for t in toks if t in text_lower) >= need:
            return True

    if len(keywords_lower) >= 2 and sum(1 for k in keywords_lower if k in text_lower) >= 2:
        return True

    return False


# =========================================================
# 3. 阶段 A：选取最热门评论 → LLM 归纳短语
# =========================================================
def _pick_reviews(df, game, kind, limit):
    """按评分筛差评/好评，取点赞数最高的 limit 条"""
    gdf = df[df["游戏名称"] == game].copy()
    if kind == "negative":
        gdf = gdf[gdf["评分"] <= 2]
    else:
        gdf = gdf[gdf["评分"] >= 4]
    gdf["_ups"] = pd.to_numeric(gdf["点赞数"], errors="coerce").fillna(0)
    return gdf.sort_values("_ups", ascending=False).head(limit)


def _build_prompt(game, kind, rows):
    """构造归纳提示词"""
    label = "差评" if kind == "negative" else "好评"
    tendency = "不满" if kind == "negative" else "认可"
    lines = []
    for i, (_, r) in enumerate(rows.iterrows(), 1):
        txt = str(r["评论内容"]).replace("\n", " ").strip()[:120]
        lines.append(f"{i}. {txt}")
    reviews_text = "\n".join(lines)

    system = "你是自走棋游戏的产品分析师，擅长从玩家评论中归纳出具体的原因短语。只输出 JSON，不要任何解释。"

    user = f"""以下是《{game}》的一批【{label}】评论，请归纳玩家{tendency}的**具体原因**。

【1. phrase 短语】用于展示的规范表述
- 必须带评价或倾向，禁止输出单个中性名词（如"阵容""棋手""游戏"）
- 归纳 8-15 条，按重要性排序

【2. aliases 别名】3-5 个，**必须是评论里真实出现过的口语片段**
⚠️ 这是最容易出错的地方，请严格遵守：
- 只能从上面的评论中**原样摘抄连续片段**（2-6 字），如"绑死""太肝了""一把二十分钟"
- ❌ 禁止书面化改写：评论写"打发时间"，就不要写成"打发时间休闲解压"
- ❌ 禁止把多个概念拼成一串：评论写"画质精美""音效震撼"，就不要写成"画质精美音效震撼"
- ✅ 一个别名只表达一个意思，越短越口语越好

【3. keywords 关键词】2-4 个，用于统计真实提及率
- 必须是**评论里真实高频出现的短词**（2-4 字），如 ["画质", "帧率", "流畅"]
- 宁可少而准，绝对不要写评论里没出现过的词

【4. 其它】
- 只输出 JSON 数组，不要输出任何统计数字
- 不要编造评论中不存在的原因

评论：
{reviews_text}

输出格式（严格 JSON，不要加任何其他文字）：
[{{"phrase": "阵容与棋手绑定过深", "aliases": ["绑死", "只能玩一个阵容", "阵容锁死"], "keywords": ["阵容", "绑定", "锁死"]}}]"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _merge_prompt(game, kind, items):
    """构造"合并同义短语"的提示词"""
    label = "差评" if kind == "negative" else "好评"
    lines = []
    for i, it in enumerate(items, 1):
        kw = "/".join(it.get("keywords", []))
        lines.append(f"{i}. {it['phrase']}  别名: {'/'.join(it.get('aliases', []))}"
                     + (f"  关键词: {kw}" if kw else ""))
    listing = "\n".join(lines)

    system = "你是自走棋游戏的产品分析师，擅长把语义重复的玩家反馈合并成一条规范表述。只输出 JSON，不要任何解释。"

    user = f"""下面是分批归纳《{game}》【{label}】原因后得到的 {len(items)} 条短语，其中存在**大量语义重复**的项
（例如「运气成分远大于运营技巧」与「运气远大于运营」、「对局进度极慢」与「对局冗长拖沓」是同一个原因）。

请合并语义相同/高度相近的项，**重点是压缩，不是重述**：
1. 输出条目数必须**明显少于输入**（上限 {LLM_PHRASE_TOP_N} 条，建议 8-{LLM_PHRASE_TOP_N} 条），凡意思相同或高度相近的一律合并成一条
2. 保留最具体、最完整、最书面的一条作为主短语，其余表述并入它的 aliases（每条 aliases 最多 4 个）
3. 不要丢失原有意思，但也不要把同义表述拆成两条；不要凭空新增原因
4. **aliases 与 keywords 原样保留**（合并时把被并入项的全部别名、关键词汇总进来，不要改写、不要精炼）
5. 只输出 JSON 数组，不要输出任何统计数字、不要解释、不要复述输入

待合并列表（{len(items)} 条）：
{listing}

输出格式（严格 JSON，不要加任何其他文字）：
[{{"phrase": "运气成分远大于运营技巧", "aliases": ["运气远大于运营", "全靠运气", "运气游戏"], "keywords": ["运气", "概率", "随机"]}}]"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _dedup_substring(items):
    """确定性兜底：短短语被长短语完全包含时（如"对局冗长" ⊂ "对局冗长拖沓"），并入长短语的别名"""
    ordered = sorted(items, key=lambda x: len(x["phrase"]), reverse=True)
    kept = []
    for it in ordered:
        merged_into = None
        for k in kept:
            if it["phrase"] in k["phrase"]:
                merged_into = k
                break
        if merged_into:
            merged_into["aliases"] = list(
                dict.fromkeys(merged_into["aliases"] + [it["phrase"]] + it["aliases"])
            )
            merged_into["keywords"] = list(
                dict.fromkeys(merged_into.get("keywords", []) + it.get("keywords", []))
            )
        else:
            kept.append(it)
    return kept


def _merge_phrases(game, kind, items):
    """
    把分批归纳出的短语做一次语义归并（LLM 判断同义，规则保证不丢项）。
    失败时降级为「仅做包含关系去重」，不影响主流程。
    """
    if len(items) <= 1:
        return items

    merged = items
    try:
        # 归并的输入可能有 40-80 条候选，输出容易超过默认 2000 tokens 被截断，
        # 这里给足输出空间（配合 _parse_phrase_json 的截断抢救）
        text = _call_llm(_merge_prompt(game, kind, items), max_tokens=4096)
        merged = _parse_phrase_json(text) or items
        label_cn = "差评" if kind == "negative" else "好评"
        print(f"      ✅ {game}·{label_cn} {len(items)} 条 → 归并为 {len(merged)} 条")
    except Exception as e:  # noqa: BLE001
        print(f"      ⚠️  {game}·{'差评' if kind == 'negative' else '好评'} 短语归并失败，"
              f"降级为仅去重：{e}")

    return _dedup_substring(merged)


def extract_phrases(df, version_id, force=False):
    """
    阶段 A：对两款游戏的差评/好评分别调 LLM 归纳短语。
    带缓存：data/phrase_cache_v4_{version_id}.json 存在则直接读。
    返回 {game: {"negative": [...], "positive": [...]}}
    """
    # v4：新增 keywords 字段 + 三级宽松匹配，旧缓存（别名是拼接串、无 keywords）必须作废
    cache_path = os.path.join(DATA_DIR, f"phrase_cache_v4_{version_id}.json")
    if os.path.exists(cache_path) and not force:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            print(f"      ♻️  命中短语缓存：{os.path.basename(cache_path)}")
            return cached
        except (json.JSONDecodeError, IOError):
            pass  # 缓存损坏则重抽

    games = list(df["游戏名称"].unique())
    result = {}

    for game in games:
        result[game] = {}
        for kind in ["negative", "positive"]:
            rows = _pick_reviews(df, game, kind, LLM_PHRASE_MAX_REVIEWS)
            if rows.empty:
                result[game][kind] = []
                continue

            # 分批调用，避免超上下文
            merged = {}
            total_batches = (len(rows) + LLM_PHRASE_BATCH_SIZE - 1) // LLM_PHRASE_BATCH_SIZE
            for bi in range(total_batches):
                batch = rows.iloc[bi * LLM_PHRASE_BATCH_SIZE:(bi + 1) * LLM_PHRASE_BATCH_SIZE]
                label = "差评" if kind == "negative" else "好评"
                print(f"      🤖 {game} · {label} 第 {bi + 1}/{total_batches} 批 "
                      f"({len(batch)} 条) ...")
                messages = _build_prompt(game, kind, batch)
                text = _call_llm(messages)
                for item in _parse_phrase_json(text):
                    key = item["phrase"]
                    if key in merged:
                        # 合并别名/关键词去重
                        merged[key]["aliases"] = list(
                            dict.fromkeys(merged[key]["aliases"] + item["aliases"])
                        )
                        merged[key]["keywords"] = list(
                            dict.fromkeys(merged[key].get("keywords", []) + item.get("keywords", []))
                        )
                    else:
                        merged[key] = item

            candidates = list(merged.values())
            label_cn = "差评" if kind == "negative" else "好评"
            print(f"      🧩 {game} · {label_cn}：{len(candidates)} 条候选短语 → 归并同义项 ...")
            result[game][kind] = _merge_phrases(game, kind, candidates)

    # 落盘缓存
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"      💾 短语缓存已保存：{os.path.basename(cache_path)}")
    except IOError as e:
        print(f"      ⚠️  缓存写入失败（不影响本次运行）：{e}")

    return result


# =========================================================
# 4. 阶段 B：规则锚定（纯 Python 数占比，保证数字可复现）
# =========================================================
def anchor_phrases(df, phrases_by_game):
    """
    用每条短语的别名回扫评论，统计真实命中数与占比。

    ⚠️ 关键：差评原因只在【差评(评分≤2)】里锚定，好评原因只在【好评(评分≥4)】里锚定。
       否则差评短语会命中无意提到该词的高星评论，样本与结论不符。
       占比分母 = 该游戏该类评论总数（差评原因 = 占差评的比例）。

    返回 {game: {"negative": [{phrase, aliases, keywords, count, ratio, sample_reviews}], "positive": [...]}}
    """
    out = {}
    for game, kinds in phrases_by_game.items():
        gdf_all = df[df["游戏名称"] == game]
        out[game] = {}

        for kind, plist in kinds.items():
            # 按倾向圈定锚定范围，避免高星评论混进痛点证据
            gdf = gdf_all[gdf_all["评分"] <= 2] if kind == "negative" else gdf_all[gdf_all["评分"] >= 4]
            total = len(gdf) if len(gdf) > 0 else 1
            contents = gdf["评论内容"].astype(str)
            ups = pd.to_numeric(gdf["点赞数"], errors="coerce").fillna(0)
            anchored = []

            for p in plist:
                # 别名 = 短语本身 + 显式别名；单字别名区分度太低（如"卡""难"），必须剔除
                aliases = [a for a in dict.fromkeys([p["phrase"]] + p.get("aliases", [])) if len(a) >= 2]
                keywords = [k for k in p.get("keywords", []) if len(k) >= 2]
                if not aliases and not keywords:
                    continue

                # 三级宽松匹配（整串字面 / 别名分词法定人数 / 关键词≥2个），详见 _hit()
                matcher = _prepare_matcher(aliases, keywords)
                mask = contents.apply(lambda t: _hit(t.lower(), matcher))
                matched = gdf[mask]
                cnt = len(matched)
                if cnt == 0:
                    continue  # 过滤未被证实的短语，避免"0% 提及"噪声

                # 取点赞最高的 5 条作为可追溯样本
                top = matched.assign(_ups=ups[mask]).sort_values("_ups", ascending=False).head(5)
                samples = [{
                    "review_id": str(r.get("评论ID", "")),
                    "content": str(r["评论内容"])[:1000],   # 与 _samples() 对齐，保证"原处展开"是全文
                    "score": int(r["评分"]),
                    "ups": int(pd.to_numeric(r.get("点赞数", 0), errors="coerce") or 0),
                    "game": game,
                } for _, r in top.iterrows()]

                anchored.append({
                    "phrase": p["phrase"],
                    "aliases": aliases,
                    "keywords": keywords,
                    "count": cnt,
                    "ratio": f"{round(cnt / total * 100, 1)}%",
                    "sample_reviews": samples,
                })

            anchored.sort(key=lambda x: x["count"], reverse=True)
            out[game][kind] = anchored[:LLM_PHRASE_TOP_N]

    return out


# =========================================================
# 5. 编排入口
# =========================================================
def build_llm_phrases(df, version_id, force=False):
    """
    阶段 A + 阶段 B 编排。无 key / 开关关闭 / 调用失败均返回 {}（调用方降级）。
    返回 {game: {"negative": [...], "positive": [...]}}
    """
    if not LLM_PHRASE_ENABLED:
        print("[LLM短语] 开关已关闭，跳过")
        return {}
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("sk-在此填入"):
        print("[LLM短语] 未配置 DEEPSEEK_API_KEY（.env），跳过 → 结论将回退词频逻辑")
        return {}

    print(f"[LLM短语] 开始抽取（模型 {DEEPSEEK_MODEL}，每类取 {LLM_PHRASE_MAX_REVIEWS} 条最热门）...")
    phrases = extract_phrases(df, version_id, force=force)
    anchored = anchor_phrases(df, phrases)

    for game, kinds in anchored.items():
        n_neg = len(kinds.get("negative", []))
        n_pos = len(kinds.get("positive", []))
        print(f"      ✅ {game}：{n_neg} 条差评原因 + {n_pos} 条好评原因（已锚定真实占比）")
        # 打印 Top1 占比，便于直观判断匹配召回是否正常（旧版常出现全部 0.4%）
        for kind, label in [("negative", "差评"), ("positive", "好评")]:
            top = (kinds.get(kind) or [])
            if top:
                print(f"         └ {label}榜 Top1：「{top[0]['phrase']}」"
                      f" 命中 {top[0]['count']} 条 / 占比 {top[0]['ratio']}")

    return anchored