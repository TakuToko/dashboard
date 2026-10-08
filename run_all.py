"""
run_all.py — 一键更新看板数据
================================
依次执行两步（等价于手动跑两条命令）：

    1) python main.py                 爬 TapTap 评论 → data/reviews_<时间戳>.csv
    2) python analysis/prepare_data.py  预处理 + LLM 短语抽取
                                       → dashboard/analyses/analysis_<版本>.json
                                       → dashboard/versions.json（前端下拉框读它）

用法：
    python run_all.py                 # 爬取 + 分析（完整流程）
    python run_all.py --skip-crawl    # 跳过爬取，只对 data/ 下最新 CSV 重新分析

跑完后前端 Ctrl+F5 强刷即可看到新版本。
"""

import argparse
import glob
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def _run(script_rel):
    """在项目根目录下运行指定脚本，失败即中止"""
    path = os.path.join(BASE_DIR, script_rel)
    print("\n" + "=" * 60)
    print(f"▶ 运行 {script_rel}")
    print("=" * 60)
    proc = subprocess.run([sys.executable, path], cwd=BASE_DIR)
    if proc.returncode != 0:
        print(f"\n❌ {script_rel} 执行失败（退出码 {proc.returncode}），已中止")
        sys.exit(proc.returncode)


def main():
    ap = argparse.ArgumentParser(description="爬取 + 预处理，一键更新看板数据")
    ap.add_argument("--skip-crawl", action="store_true",
                    help="跳过爬取，只对 data/ 下最新 CSV 重新分析")
    args = ap.parse_args()

    if args.skip_crawl:
        csvs = glob.glob(os.path.join(DATA_DIR, "reviews_*.csv"))
        if not csvs:
            print(f"❌ data/ 下没有 reviews_*.csv，无法跳过爬取。请先执行 python run_all.py")
            sys.exit(1)
        latest = max(csvs, key=os.path.getmtime)
        print(f"⏭  跳过爬取，使用最新 CSV：{os.path.basename(latest)}")
    else:
        _run("main.py")

    _run(os.path.join("analysis", "prepare_data.py"))

    print("\n" + "=" * 60)
    print("✅ 全部完成。请到前端 Ctrl+F5 强刷，新版本会出现在「知识库版本」下拉框。")
    print("=" * 60)


if __name__ == "__main__":
    main()