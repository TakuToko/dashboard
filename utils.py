import time
import json
from datetime import datetime
import requests
import pandas as pd
import config as config
from urllib.parse import urlparse, parse_qs


def get_taptap_reviews():
    """
    爬取 TapTap 评论，返回字段：
      游戏名称 | 评分 | 评论内容 | 评论时间 | 点赞数 | 点踩数 | 
      评论者昵称 | 玩过阶段 | 玩过时长(小时) | 评论ID | 来源接口
    """

    all_reviews = []

    for game_name, game_info in config.GAMES_CONFIG.items():
        if not game_info["is_active"]:
            print(f"{game_name}配置为不采集，暂时跳过")
            continue

        app_id = game_info["app_id"]
        max_review = game_info["max_reviews"]
        print(f"当前开始采集{game_name}的评论数据……")

        url = config.TAPTAP_REVIEW_URL
        page_size = config.PAGE_SIZE
        headers = config.HEADERS.copy()
        headers["Referer"] = f"https://www.taptap.cn/app/{app_id}/review?os=android"
        x_ua = config.X_UA

        offset = 0
        current_game_count = 0
        session_id = None
        consecutive_empty = 0

        while current_game_count < max_review:
            params = {
                "app_id": app_id,
                "sort": "hot",
                "X-UA": x_ua
                # from / limit 用 session_id 控制，不再手动传 offset
                # （但 limit 还是显式指定更安全）
            }
            if session_id:
                params["session_id"] = session_id
                # 有 session_id 就不带 from，让接口自己翻页
            else:
                params["from"] = offset

            response = requests.get(url, headers=headers, params=params)

            if response.status_code != 200:
                print(f"  ⚠️ {game_name} 状态码 {response.status_code}，重试一次...")
                time.sleep(2)
                continue  # 不 break，重试

            resp_json = response.json()
            data_list = resp_json.get("data", {}).get("list", [])

            if not data_list:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(f"  ⚠️ 连续 3 页空数据，停止翻页")
                    break
                time.sleep(1)
                continue  # 空页不一定是结束，session_id 可能翻到空位置了

            consecutive_empty = 0

            # 从 next_page 提取 session_id 用于翻页
            next_page = resp_json.get("data", {}).get("next_page", "")
            if next_page:
                parsed = urlparse(next_page)
                qs = parse_qs(parsed.query)
                new_session = qs.get("session_id", [None])[0]
                if new_session:
                    session_id = new_session

            skipped = 0
            for item in data_list:
                try:
                    moment = item["moment"]
                    review_node = moment["review"]

                    ts = moment.get("created_time")
                    comment_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                    text = review_node.get("contents", {}).get("raw_text", "")
                    score = review_node.get("score")
                    stat = moment.get("stat", {})
                    ups = stat.get("ups", 0)
                    downs = stat.get("downs", 0)
                    author = moment.get("author", {})
                    nickname = author.get("user", {}).get("name", "") if author else ""
                    stage_label = review_node.get("stage_label", "")
                    total_spent_sec = review_node.get("total_played_spent")
                    play_hours = round(total_spent_sec / 3600, 1) if total_spent_sec else ""
                    review_id = review_node.get("id")

                    all_reviews.append({
                        "游戏名称": game_name,
                        "评分": score,
                        "评论内容": text,
                        "评论时间": comment_time,
                        "点赞数": ups,
                        "点踩数": downs,
                        "评论者": nickname,
                        "玩过阶段": stage_label,
                        "玩过时长_小时": play_hours,
                        "评论ID": review_id,
                    })
                    current_game_count += 1

                    if current_game_count >= max_review:
                        break
                except (KeyError, TypeError) as e:
                    skipped += 1
                    continue

            if skipped > 0:
                print(f"  本页跳过 {skipped} 条残缺评论")

            if not session_id:
                offset += page_size  # 只有前几页没 session_id 时才用 offset 翻页
            time.sleep(1)

        print(f"✅ {game_name}采集完成，已采集 {current_game_count} 条评论")

    return all_reviews


def save_reviews_to_csv(reviews, filename="reviews.csv"):
    if not reviews:
        print("没有评论数据可保存")
        return

    df = pd.DataFrame(reviews)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"评论数据已保存到 {filename}，共 {len(df)} 条数据")
    print(f"字段列表: {list(df.columns)}")


# =========================================================
# TapTap App 官方统计数据爬取
# —— 从 App 页面 HTML 里提取 JSON-LD（Schema.org 结构化数据）
# —— 这是搜索引擎和爬虫通用的标准格式，稳定不 404
# —— TapTap 用 10 分制（bestRating=10），前端展示除以 2 转 5 星
# =========================================================
import re as _re


def fetch_app_stats(app_id):
    """
    爬取 TapTap App 官方统计数据（评分、下载、关注、发行商等）
    
    双轨方案（全部从 HTML 页面拿，不依赖隐藏 API）：
      ① JSON-LD：<script type="application/ld+json"> 拿评分、发行商、下载量
                 下载量从 schema.org 的 InteractionCounter 拿
                 （interactionType=DownloadAction → userInteractionCount）
      ② DOM 正则兜底：关注数等 SPA 动态渲染的互动数据
    
    返回：
      { title, publisher, rating, rating_count, follow_count, 
        download_count, wish_count, tags, launch_date, raw_max_rating }
      
    返回 None 表示页面请求失败
    """
    headers = config.HEADERS.copy()
    headers["Referer"] = "https://www.taptap.cn/"

    app_url = f"https://www.taptap.cn/app/{app_id}"
    try:
        resp = requests.get(app_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️ App 页面返回 {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ⚠️ App 页面请求失败: {e}")
        return None

    html = resp.text

    # ① JSON-LD 层（评分、发行商、下载量等 SSR 静态字段）
    result = _parse_jsonld_from_html(html) or {}

    # ② DOM 正则兜底（关注数等 SPA 动态渲染的字段）
    dom_stats = _parse_taptap_dom_stats(html)

    # 合并：JSON-LD 有值优先，否则用 DOM 抓的
    for key in ("follow_count", "download_count", "wish_count"):
        dom_val = dom_stats.get(key, 0)
        if dom_val > 0 and result.get(key, 0) == 0:
            result[key] = dom_val

    return result if result else None


def _parse_taptap_dom_stats(html):
    """
    从 TapTap App 详情页的 HTML 中正则提取互动数据（DOM 层兜底）。
    
    这个函数的主要目的：
    - 拿关注数 follow_count（JSON-LD 里通常只有 DownloadAction，关注数是 SPA 动态渲染的）
    - 拿 download_count 作为最终兜底
    
    数字格式：支持 "82 万" / "1.2 亿" / "4660"（TapTap 用中文计数单位）
    """
    result = {"download_count": 0, "follow_count": 0, "rating_count_dom": 0}

    def _parse_number(text):
        """把 '82 万' / '1.2 亿' / '4660' 转成整数"""
        text = text.replace(",", "").replace(" ", "").strip()
        m = _re.match(r'([\d.]+)\s*([亿万])?', text)
        if not m:
            return 0
        num = float(m.group(1))
        unit = m.group(2) or ""
        if unit == "亿":
            return int(num * 100_000_000)
        elif unit == "万":
            return int(num * 10_000)
        else:
            return int(num)

    # —— 关注数（最重要，JSON-LD 里拿不到）——
    # 页面上可能的形式：
    #   "关注" </div> "323 万"     （跨行、跨 DOM 节点）
    #   "关注 323 万"               （单行纯文本）
    # 所以用 [\s\S]{0,60}? 跨行匹配
    patterns_follow = [
        r'关注[\s\S]{0,80}?([\d.]+)\s*([亿万])',
        r'关注\s*([\d.]+)\s*([亿万])',
        r'关注[\s\S]{0,80}?([\d,]+)',   # "关注 ... 4660"（无单位）
    ]
    for p in patterns_follow:
        m = _re.search(p, html)
        if m:
            num_str = m.group(1)
            unit = m.group(2) if m.lastindex >= 2 else ""
            result["follow_count"] = _parse_number(num_str + (unit if unit else ""))
            if result["follow_count"] > 0:
                break

    # —— 下载量兜底（优先 JSON-LD，但以防万一）——
    patterns_download = [
        r'下载[\s\S]{0,80}?([\d.]+)\s*([亿万])',
        r'下载\s*([\d.]+)\s*([亿万])',
    ]
    for p in patterns_download:
        m = _re.search(p, html)
        if m:
            num_str = m.group(1)
            unit = m.group(2) if m.lastindex >= 2 else ""
            result["download_count"] = _parse_number(num_str + (unit if unit else ""))
            if result["download_count"] > 0:
                break

    print(f"      📊 DOM 正则兜底: download={result['download_count']:,} follow={result['follow_count']:,}")
    return result


def _parse_jsonld_from_html(html):
    """
    从 HTML 里找所有 JSON-LD script，找到 @type=SoftwareApplication 那个
    """
    # 找所有 <script type="application/ld+json">...</script>
    # 注意里面可能有换行，要用 DOTALL
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    all_jsonlds = _re.findall(pattern, html, _re.DOTALL)

    app_json = None
    for raw in all_jsonlds:
        try:
            obj = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        # TapTap 的主数据 script 是 @type=SoftwareApplication
        if obj.get("@type") == "SoftwareApplication" or "aggregateRating" in obj:
            app_json = obj
            break

    if not app_json:
        print(f"  ⚠️ HTML 里没找到 JSON-LD SoftwareApplication")
        return None

    result = {
        "title": str(app_json.get("name", "") or ""),
        "publisher": "",
        "launch_date": str(app_json.get("datePublished", "") or ""),
        "tags": [],
        # 评分相关
        "rating": 0.0,          # 官方评分（TapTap 10 分制，前端会除以 2 显示 5 星）
        "rating_count": 0,      # 评分人数
        "raw_max_rating": 0,    # 原始分制上限（TapTap 是 10）
        # 互动/关注/下载
        "follow_count": 0,
        "download_count": 0,
        "wish_count": 0,
        # 用于交叉验证
        "interaction_count": 0, # 总互动数（点赞+评论+分享等总和，可能≈关注量）
    }

    # —— 评分 ——
    agg = app_json.get("aggregateRating", {}) or {}
    if agg:
        val = agg.get("ratingValue")
        if val is not None:
            try: result["rating"] = float(val)
            except (ValueError, TypeError): pass
        cnt = agg.get("ratingCount")
        if cnt is not None:
            try: result["rating_count"] = int(cnt)
            except (ValueError, TypeError): pass
        best = agg.get("bestRating")
        if best is not None:
            try: result["raw_max_rating"] = int(best)
            except (ValueError, TypeError): pass

    # —— 互动统计（InteractionCounter）——
    # TapTap 用 schema.org 的 InteractionCounter 标准：
    #   interactionType = DownloadAction → 下载量
    #   interactionType = FollowAction   → 关注数
    #   interactionType = WishListAction → 愿望单数
    # 注意：可能是单个对象，也可能是数组（多个 Counter）
    interact = app_json.get("interactionStatistic")
    if interact:
        if isinstance(interact, dict):
            interact = [interact]
        if isinstance(interact, list):
            for counter in interact:
                if not isinstance(counter, dict):
                    continue
                cnt = counter.get("userInteractionCount")
                if cnt is None:
                    continue
                try:
                    cnt = int(cnt)
                except (ValueError, TypeError):
                    continue
                itype = (counter.get("interactionType") or {}).get("@type", "")
                if "DownloadAction" in itype:
                    result["download_count"] = cnt
                    print(f"      🎯 JSON-LD InteractionCounter → download_count={cnt:,}")
                elif "FollowAction" in itype:
                    result["follow_count"] = cnt
                    print(f"      🎯 JSON-LD InteractionCounter → follow_count={cnt:,}")
                elif "WishListAction" in itype:
                    result["wish_count"] = cnt
                else:
                    # 未知类型，先记到 interaction_count 兜底
                    result["interaction_count"] = max(result.get("interaction_count", 0), cnt)

    # —— 兜底：用 offers 里的字段或 publisher 的 follow 数 ——
    if result.get("follow_count", 0) == 0 and result.get("interaction_count", 0) > 0:
        result["follow_count"] = result["interaction_count"]

    # —— publisher ——
    pub = app_json.get("publisher")
    if isinstance(pub, dict):
        result["publisher"] = str(pub.get("name", "") or "")
    elif isinstance(pub, str):
        result["publisher"] = pub

    # —— genre（作为 tags）——
    genre = app_json.get("genre")
    if genre:
        if isinstance(genre, str):
            result["tags"] = [genre]
        elif isinstance(genre, list):
            result["tags"] = [str(g) for g in genre[:5]]

    # —— 兜底：follow_count 用 interaction_count ——
    if result["interaction_count"] > 0 and result["follow_count"] == 0:
        result["follow_count"] = result["interaction_count"]

    return result


def fetch_all_app_stats():
    """批量爬取所有竞品的 App 详情"""
    stats = {}
    print("[App详情] 正在爬取 TapTap 官方数据 ...")
    for game_name, game_info in config.GAMES_CONFIG.items():
        if not game_info["is_active"]:
            continue
        app_id = game_info["app_id"]
        print(f"  正在获取 {game_name} ({app_id}) ...")
        result = fetch_app_stats(app_id)
        if result:
            stats[game_name] = result
            print(f"    ✅ 总分: {result['rating']} | 评分人数: {result['rating_count']} | 关注: {result['follow_count']} | 下载: {result['download_count']}")
        else:
            # 接口失败时用配置里的生命周期元数据兜底
            cfg = game_info
            stats[game_name] = {
                "title": game_name,
                "publisher": cfg.get("publisher", ""),
                "launch_date": cfg.get("launch_date", ""),
                "rating": 0, "rating_count": 0, "follow_count": 0,
                "wish_count": 0, "download_count": 0, "tags": [],
            }
            print(f"    ⚠️ 接口失败，使用配置兜底")
        time.sleep(0.5)
    return stats
