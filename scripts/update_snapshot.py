#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
半决赛实时看板 — 数据抓取与快照更新脚本
支持：
1. 本地手动/定时运行，更新 data/snapshot.json 与 data/snapshot.js（供 file:// 直接打开）
2. GitHub Actions 定时运行（每 10 分钟），自动记录每个队伍每次提交与进步分数轨迹（sf_timeline & events）
"""

import datetime
import hashlib
import json
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
    for _ in range(retries):
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


def build_team_timelines_and_events(snapshots: list, r2_by_csbh: dict, qual_by_csbh: dict):
    """
    从历史快照序列重建：
    1) 每个队伍的半决赛历次提交轨迹 team_timelines[csbh]
    2) 全局每次提分/新提交事件列表 all_events（含单次进步分数 delta 与较复赛进步分数 delta_vs_r2）
    """
    team_timelines = {}
    all_events = []

    for snap_idx, snap in enumerate(snapshots):
        captured_at = snap.get("captured_at", "")
        scores_map = snap.get("scores", {})
        for csbh, rec in scores_map.items():
            score_str = rec.get("score", "")
            if score_str in (None, ""):
                continue
            score_val = float(score_str)
            tjsj = rec.get("tjsj", "")
            dfsj = rec.get("dfsj", "")
            rank_val = int(rec.get("rank", 0))
            tdmc = rec.get("tdmc", "")
            judge_sec = parse_seconds_diff(tjsj, dfsj)

            r2_info = r2_by_csbh.get(csbh, {})
            r2_score_str = r2_info.get("FS_", "")
            r2_score = float(r2_score_str) if r2_score_str not in (None, "") else None
            delta_vs_r2 = round(score_val - r2_score, 4) if r2_score is not None else None

            tl = team_timelines.setdefault(csbh, [])
            if not tl:
                # 首次在半决赛快照中出现
                step_entry = {
                    "step": 1,
                    "type": "initial_capture" if snap_idx == 0 else "new_submission",
                    "score": score_val,
                    "score_str": score_str,
                    "prev_score": None,
                    "prev_score_str": None,
                    "delta_step": None,
                    "r2_score": r2_score,
                    "r2_score_str": r2_score_str,
                    "delta_vs_r2": delta_vs_r2,
                    "rank": rank_val,
                    "prev_rank": None,
                    "tjsj": tjsj,
                    "dfsj": dfsj,
                    "judge_sec": judge_sec,
                    "detected_at": captured_at,
                }
                tl.append(step_entry)
                if snap_idx > 0:
                    all_events.append({
                        "type": "new_submission",
                        "step": 1,
                        "detected_at": captured_at,
                        "csbh": csbh,
                        "tdmc": tdmc,
                        "new_score": score_str,
                        "prev_score": None,
                        "delta": None,
                        "r2_score": r2_score_str,
                        "delta_vs_r2": delta_vs_r2,
                        "new_rank": rank_val,
                        "prev_rank": None,
                        "tjsj": tjsj,
                        "dfsj": dfsj,
                        "judge_sec": judge_sec,
                    })
            else:
                last_step = tl[-1]
                # 只要分数变化，或者提交时间戳变化，就记为一次新提交尝试
                if score_str != last_step["score_str"] or tjsj != last_step["tjsj"]:
                    delta_step = round(score_val - last_step["score"], 4)
                    ev_type = "score_update" if score_str != last_step["score_str"] else "resubmit_same_score"
                    step_num = len(tl) + 1
                    step_entry = {
                        "step": step_num,
                        "type": ev_type,
                        "score": score_val,
                        "score_str": score_str,
                        "prev_score": last_step["score"],
                        "prev_score_str": last_step["score_str"],
                        "delta_step": delta_step,
                        "r2_score": r2_score,
                        "r2_score_str": r2_score_str,
                        "delta_vs_r2": delta_vs_r2,
                        "rank": rank_val,
                        "prev_rank": last_step["rank"],
                        "tjsj": tjsj,
                        "dfsj": dfsj,
                        "judge_sec": judge_sec,
                        "detected_at": captured_at,
                    }
                    tl.append(step_entry)
                    all_events.append({
                        "type": ev_type,
                        "step": step_num,
                        "detected_at": captured_at,
                        "csbh": csbh,
                        "tdmc": tdmc,
                        "new_score": score_str,
                        "prev_score": last_step["score_str"],
                        "delta": delta_step,
                        "r2_score": r2_score_str,
                        "delta_vs_r2": delta_vs_r2,
                        "new_rank": rank_val,
                        "prev_rank": last_step["rank"],
                        "tjsj": tjsj,
                        "dfsj": dfsj,
                        "judge_sec": judge_sec,
                    })

    # Sort events by dfsj / detected_at descending
    all_events.sort(key=lambda e: (e.get("dfsj") or e.get("detected_at") or ""), reverse=True)
    return team_timelines, all_events


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

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

    sf_res = fetch_stage("半决赛")
    r2_res = fetch_stage("复赛")

    sf_rows = sf_res["response"].get("data") or []
    r2_rows = r2_res["response"].get("data") or []

    r2_by_csbh = {row["CSBH_"]: row for row in r2_rows if "CSBH_" in row}

    history = {"snapshots": [], "events": []}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    current_scores = {}
    for row in sf_rows:
        csbh = row.get("CSBH_", "")
        current_scores[csbh] = {
            "rank": int(row.get("XH_", 0)),
            "score": row.get("FS_"),
            "tjsj": row.get("ZPZHTJSJ_", ""),
            "dfsj": row.get("DFSJ_", ""),
            "tdmc": row.get("TDMC_", ""),
        }

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
        history["snapshots"] = history["snapshots"][-300:]

    team_timelines, all_events = build_team_timelines_and_events(
        history.get("snapshots", []), r2_by_csbh, qual_by_csbh
    )
    history["events"] = all_events[:500]

    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    unified_teams = []
    seen_csbh = set()

    for sf in sf_rows:
        csbh = sf["CSBH_"]
        seen_csbh.add(csbh)
        q_info = qual_by_csbh.get(csbh, {})
        r2_info = r2_by_csbh.get(csbh, {})
        tl = team_timelines.get(csbh, [])

        sf_score = float(sf["FS_"]) if sf.get("FS_") not in (None, "") else None
        r2_score = float(r2_info["FS_"]) if r2_info.get("FS_") not in (None, "") else None

        delta_vs_r2 = round(sf_score - r2_score, 4) if (sf_score is not None and r2_score is not None) else None
        last_step_delta = tl[-1]["delta_step"] if len(tl) >= 2 else None
        first_sf_score = tl[0]["score"] if tl else sf_score
        delta_vs_first_sf = round(sf_score - first_sf_score, 4) if (sf_score is not None and first_sf_score is not None and len(tl) >= 2) else None

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
            "sf_submit_count": len(tl),
            "last_step_delta": last_step_delta,
            "delta_vs_first_sf": delta_vs_first_sf,
            "sf_timeline": tl,
        })

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
            "sf_submit_count": 0,
            "last_step_delta": None,
            "delta_vs_first_sf": None,
            "sf_timeline": [],
        })

    unsubmitted.sort(key=lambda x: (x["r2_rank"] if x["r2_rank"] is not None else 9999, x["r2_award_seq"] or 9999))
    unified_teams.extend(unsubmitted)

    multi_submit_teams = sum(1 for t in unified_teams if t.get("sf_submit_count", 0) >= 2)

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
            "multi_submit_teams_count": multi_submit_teams,
            "captured_events_count": len(all_events),
            "top1_team": unified_teams[0]["tdmc"] if sf_rows else None,
            "top1_score": unified_teams[0]["sf_score_str"] if sf_rows else None,
        },
        "teams": unified_teams,
        "history_events": all_events[:200],
        "history_snapshots_meta": [
            {
                "snapshot_id": s["snapshot_id"],
                "captured_at": s["captured_at"],
                "scored_count": s["scored_count"],
                "top1_score": next(iter(s["scores"].values()))["score"] if s.get("scores") else None,
            }
            for s in history.get("snapshots", [])[-100:]
        ],
    }

    json_text = json.dumps(snapshot_payload, ensure_ascii=False, indent=2)
    SNAPSHOT_JSON.write_text(json_text, encoding="utf-8")
    SNAPSHOT_JS.write_text(
        f"window.__INITIAL_SNAPSHOT__ = {json_text};\n", encoding="utf-8"
    )
    print(f"[OK] Updated snapshot {snap_id}: {len(sf_rows)}/77 scored, {multi_submit_teams} multi-submit teams, {len(all_events)} progression events.")


if __name__ == "__main__":
    main()
