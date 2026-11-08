#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
半决赛实时看板 — 数据抓取与快照更新脚本
支持：
1. 本地手动/定时运行，更新 data/snapshot.json 与 data/snapshot.js（供 file:// 直接打开）
2. GitHub Actions 定时运行（每 10 分钟），自动记录历史分数变化事件（diff feed）
"""

import datetime
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

API_URL = "https://jluat-smart-app-api.yuntu.cn/third/jsphb"
SOURCE_URL = "https://reg.aicomp.cn/special/phb/detail?id=4843470003011457070&rwId=4863942083800600605&stbh=4863942083800600619"
RW_ID = "4863942083800600605"
STBH = "4863942083800600619"

TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

BOARD_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BOARD_DIR / "data"
QUALIFIERS_FILE = DATA_DIR / "qualifiers_77.json"
HISTORY_FILE = DATA_DIR / "history.json"
SNAPSHOT_JSON = DATA_DIR / "snapshot.json"
SNAPSHOT_JS = DATA_DIR / "snapshot.js"


def fetch_stage(stage_name: str, timeout: int = 20, retries: int = 3) -> dict:
    payload = {
        "pageNo": 0,
        "pageSize": 20,
        "type": "JSDF",
        "rwId": RW_ID,
        "stbh": STBH,
        "jd": stage_name,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                API_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VideoORA-LiveBoard/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode("utf-8"))
                return {
                    "http_status": resp.status,
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "response": data,
                }
        except Exception as e:
            last_err = e
    raise last_err


def parse_seconds_diff(t_start: str, t_end: str):
    if not t_start or not t_end:
        return None
    try:
        dt1 = datetime.datetime.strptime(t_start.strip(), "%Y-%m-%d %H:%M:%S")
        dt2 = datetime.datetime.strptime(t_end.strip(), "%Y-%m-%d %H:%M:%S")
        diff = (dt2 - dt1).total_seconds()
        return int(round(diff)) if diff >= 0 else None
    except Exception:
        return None


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load 77 qualifiers (copy from parent if not yet in DATA_DIR)
    parent_qual_file = BOARD_DIR.parent / "round2_official_awards_and_semifinal_qualifiers.json"
    if not QUALIFIERS_FILE.exists() and parent_qual_file.exists():
        raw_q = json.loads(parent_qual_file.read_text(encoding="utf-8"))
        QUALIFIERS_FILE.write_text(
            json.dumps(raw_q, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    qual_data = json.loads(QUALIFIERS_FILE.read_text(encoding="utf-8"))
    all_award_records = qual_data.get("records", [])
    qualifiers_77 = [r for r in all_award_records if r.get("qualified")]
    qual_by_csbh = {r["csbh"]: r for r in qualifiers_77}

    now_dt = datetime.datetime.now(TZ_CN)
    now_iso = now_dt.isoformat(timespec="seconds")
    snap_id = now_dt.strftime("%Y%m%d_%H%M%S")

    # 2. Fetch 半决赛 & 复赛
    sf_res = fetch_stage("半决赛")
    r2_res = fetch_stage("复赛")

    sf_rows = sf_res["response"].get("data") or []
    r2_rows = r2_res["response"].get("data") or []

    sf_by_csbh = {row["CSBH_"]: row for row in sf_rows if "CSBH_" in row}
    r2_by_csbh = {row["CSBH_"]: row for row in r2_rows if "CSBH_" in row}

    # 3. Load history for score change event tracking
    history = {"snapshots": [], "events": []}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    prev_scores = {}
    if history.get("snapshots"):
        last_snap = history["snapshots"][-1]
        prev_scores = last_snap.get("scores", {})

    current_scores = {}
    new_events = []

    for row in sf_rows:
        csbh = row.get("CSBH_", "")
        score_str = row.get("FS_")
        score_val = float(score_str) if score_str not in (None, "") else None
        rank_val = int(row.get("XH_", 0))
        tjsj = row.get("ZPZHTJSJ_", "")
        dfsj = row.get("DFSJ_", "")
        tdmc = row.get("TDMC_", "")
        judge_sec = parse_seconds_diff(tjsj, dfsj)

        current_scores[csbh] = {
            "rank": rank_val,
            "score": score_str,
            "tjsj": tjsj,
            "dfsj": dfsj,
            "tdmc": tdmc,
        }

        prev = prev_scores.get(csbh)
        if prev is None:
            # First time seen in history
            if history.get("snapshots"):
                new_events.append({
                    "type": "new_submission",
                    "detected_at": now_iso,
                    "csbh": csbh,
                    "tdmc": tdmc,
                    "new_score": score_str,
                    "prev_score": None,
                    "delta": None,
                    "new_rank": rank_val,
                    "prev_rank": None,
                    "tjsj": tjsj,
                    "dfsj": dfsj,
                    "judge_sec": judge_sec,
                })
        else:
            prev_s = float(prev["score"]) if prev.get("score") not in (None, "") else None
            if (score_str != prev.get("score")) or (tjsj != prev.get("tjsj")):
                delta = round(score_val - prev_s, 4) if (score_val is not None and prev_s is not None) else None
                new_events.append({
                    "type": "score_update" if score_str != prev.get("score") else "resubmit_same_score",
                    "detected_at": now_iso,
                    "csbh": csbh,
                    "tdmc": tdmc,
                    "new_score": score_str,
                    "prev_score": prev.get("score"),
                    "delta": delta,
                    "new_rank": rank_val,
                    "prev_rank": prev.get("rank"),
                    "tjsj": tjsj,
                    "dfsj": dfsj,
                    "judge_sec": judge_sec,
                })

    # Append snapshot to history only if scores/timestamps changed or history is empty
    state_fingerprint = hashlib.sha256(
        json.dumps(current_scores, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    last_fp = history["snapshots"][-1].get("fingerprint") if history.get("snapshots") else None

    if state_fingerprint != last_fp:
        history.setdefault("snapshots", []).append({
            "snapshot_id": snap_id,
            "captured_at": now_iso,
            "platform_create_time": sf_rows[0].get("createTime", "") if sf_rows else "",
            "scored_count": len(sf_rows),
            "fingerprint": state_fingerprint,
            "scores": current_scores,
        })
        # Keep last 200 snapshots in history.json to stay lightweight
        history["snapshots"] = history["snapshots"][-200:]

    if new_events:
        history.setdefault("events", []).extend(new_events)
        history["events"] = history["events"][-500:]

    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 4. Build unified 77-team dataset (plus any extra teams if API ever returns outside 77)
    previous_snap_scores = (
        history["snapshots"][-2]["scores"]
        if len(history.get("snapshots", [])) >= 2
        else {}
    )

    unified_teams = []
    seen_csbh = set()

    # First: all teams currently on Semifinal leaderboard in rank order
    for sf in sf_rows:
        csbh = sf["CSBH_"]
        seen_csbh.add(csbh)
        q_info = qual_by_csbh.get(csbh, {})
        r2_info = r2_by_csbh.get(csbh, {})
        prev_info = previous_snap_scores.get(csbh, {})

        sf_score = float(sf["FS_"]) if sf.get("FS_") not in (None, "") else None
        r2_score = float(r2_info["FS_"]) if r2_info.get("FS_") not in (None, "") else None
        prev_score = float(prev_info["score"]) if prev_info.get("score") not in (None, "") else None

        delta_vs_r2 = round(sf_score - r2_score, 4) if (sf_score is not None and r2_score is not None) else None
        delta_vs_prev = round(sf_score - prev_score, 4) if (sf_score is not None and prev_score is not None) else None
        rank_delta_vs_prev = (prev_info["rank"] - int(sf["XH_"])) if prev_info.get("rank") else None

        tjsj = sf.get("ZPZHTJSJ_", "")
        dfsj = sf.get("DFSJ_", "")
        judge_sec = parse_seconds_diff(tjsj, dfsj)

        unified_teams.append({
            "csbh": csbh,
            "tdmc": sf.get("TDMC_") or r2_info.get("TDMC_") or "未知队名",
            "members": q_info.get("members", []),
            "r2_award": q_info.get("award", "晋级国赛"),
            "r2_award_seq": q_info.get("seq"),
            "has_sf_score": True,
            "sf_rank": int(sf["XH_"]),
            "sf_score": sf_score,
            "sf_score_str": sf.get("FS_", ""),
            "sf_tjsj": tjsj,
            "sf_dfsj": dfsj,
            "sf_judge_sec": judge_sec,
            "r2_rank": int(r2_info["XH_"]) if r2_info.get("XH_") else None,
            "r2_score": r2_score,
            "r2_score_str": r2_info.get("FS_", ""),
            "r2_tjsj": r2_info.get("ZPZHTJSJ_", ""),
            "delta_vs_r2": delta_vs_r2,
            "delta_vs_prev": delta_vs_prev,
            "rank_delta_vs_prev": rank_delta_vs_prev,
        })

    # Second: qualified teams from the 77-team official list not yet on Semifinal leaderboard
    unsubmitted = []
    for q in qualifiers_77:
        csbh = q["csbh"]
        if csbh in seen_csbh:
            continue
        r2_info = r2_by_csbh.get(csbh, {})
        r2_score = float(r2_info["FS_"]) if r2_info.get("FS_") not in (None, "") else None
        unsubmitted.append({
            "csbh": csbh,
            "tdmc": r2_info.get("TDMC_") or f"晋级队伍 #{q['seq']}",
            "members": q.get("members", []),
            "r2_award": q.get("award", ""),
            "r2_award_seq": q.get("seq"),
            "has_sf_score": False,
            "sf_rank": None,
            "sf_score": None,
            "sf_score_str": "",
            "sf_tjsj": "",
            "sf_dfsj": "",
            "sf_judge_sec": None,
            "r2_rank": int(r2_info["XH_"]) if r2_info.get("XH_") else None,
            "r2_score": r2_score,
            "r2_score_str": r2_info.get("FS_", ""),
            "r2_tjsj": r2_info.get("ZPZHTJSJ_", ""),
            "delta_vs_r2": None,
            "delta_vs_prev": None,
            "rank_delta_vs_prev": None,
        })

    # Sort unsubmitted by their R2 rank (ascending) then award seq
    unsubmitted.sort(key=lambda x: (x["r2_rank"] if x["r2_rank"] is not None else 9999, x["r2_award_seq"] or 9999))
    unified_teams.extend(unsubmitted)

    snapshot_payload = {
        "competition": "基于视频大模型的通用视频高光剪辑",
        "stage": "半决赛（国赛晋级池 77 支队伍）",
        "snapshot_id": snap_id,
        "captured_at": now_iso,
        "platform_create_time": sf_rows[0].get("createTime", "") if sf_rows else "",
        "api_url": API_URL,
        "source_url": SOURCE_URL,
        "request_params": {
            "pageNo": 0,
            "pageSize": 20,
            "type": "JSDF",
            "rwId": RW_ID,
            "stbh": STBH,
            "jd": "半决赛",
        },
        "summary": {
            "total_qualified": len(qualifiers_77),
            "provincial_first_qualified": sum(1 for q in qualifiers_77 if q.get("award") == "省赛一等奖"),
            "provincial_second_qualified": sum(1 for q in qualifiers_77 if q.get("award") == "省赛二等奖"),
            "sf_scored_count": len(sf_rows),
            "sf_unsubmitted_count": len(unsubmitted),
            "top1_team": unified_teams[0]["tdmc"] if sf_rows else None,
            "top1_score": unified_teams[0]["sf_score_str"] if sf_rows else None,
        },
        "teams": unified_teams,
        "history_events": history.get("events", [])[-100:],
        "history_snapshots_meta": [
            {
                "snapshot_id": s["snapshot_id"],
                "captured_at": s["captured_at"],
                "scored_count": s["scored_count"],
                "top1_score": next(iter(s["scores"].values()))["score"] if s.get("scores") else None,
            }
            for s in history.get("snapshots", [])[-50:]
        ],
    }

    json_text = json.dumps(snapshot_payload, ensure_ascii=False, indent=2)
    SNAPSHOT_JSON.write_text(json_text, encoding="utf-8")
    SNAPSHOT_JS.write_text(
        f"window.__INITIAL_SNAPSHOT__ = {json_text};\n", encoding="utf-8"
    )
    print(f"[OK] Updated snapshot {snap_id}: {len(sf_rows)}/77 scored in Semifinal, {len(unsubmitted)} pending.")


if __name__ == "__main__":
    main()
