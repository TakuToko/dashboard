"""
爬虫入口：爬取 TapTap 评论，带时间戳存到 data/ 目录

每次运行生成独立文件（如 data/reviews_20260923_143000.csv），
不会覆盖历史数据。之后运行: python analysis/prepare_data.py
会自动取 data/ 下最新的 CSV 做预处理。
"""
import os
from datetime import datetime
import sys

# 把父目录加入 path（utils.py 在父目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import get_taptap_reviews, save_reviews_to_csv
import config as config


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    # 确保 data 目录存在
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 60)
    print("  TapTap 竞品分析 - 数据采集")
    print("=" * 60)

    # 爬评论
    reviews = get_taptap_reviews()
    if not reviews:
        print("❌ 没爬到任何评论")
        return

    # 生成带时间戳的文件名
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(DATA_DIR, f"reviews_{ts}.csv")
    save_reviews_to_csv(reviews, filename=csv_path)

    # 额外打印版本信息，方便 prepare_data.py 读取
    version_id = ts
    print(f"\n📌 数据版本 ID: {version_id}")
    print(f"📂 CSV 路径: {csv_path}")
    print(f"\n👉 下一步: python analysis/prepare_data.py")
    print("   （会自动取 data/ 下最新 CSV 做预处理）")


if __name__ == "__main__":
    main()
