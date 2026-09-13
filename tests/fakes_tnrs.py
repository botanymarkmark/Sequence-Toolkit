"""TNRS 测试替身：完全离线，记录发出的 payload。"""

from __future__ import annotations

import json


class FakePoster:
    """按调用顺序返回预置响应文本；记录每次收到的 payload。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> str:
        self.payloads.append(payload)
        if not self.responses:
            raise AssertionError("FakePoster 没有更多预置响应了")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def rows_json(rows: list[dict]) -> str:
    """把若干行结果拼成 TNRS 风格的 JSON 响应数组。"""
    return json.dumps(rows, ensure_ascii=False)


def make_row(row_id=1, submitted="Acer rubrum", matched="Acer rubrum",
             score="1", accepted="Acer rubrum", rank="species",
             family="", source="wcvp", accepted_family="Sapindaceae",
             warnings="", unmatched="") -> dict:
    """一条 TNRS 结果行，字段名与真实响应一致（实测 46 个字段里我们用到的那些）。"""
    return {
        "ID": str(row_id),
        "Name_submitted": submitted,
        "Name_matched": matched,
        "Overall_score": score,
        "Accepted_name": accepted,
        "Accepted_name_rank": rank,
        "Accepted_name_author": "",
        "Family_submitted": "",
        "Family_matched": family,
        "Source": source,
        "Warnings": warnings,
        "WarningsEng": warnings,
        "Unmatched_terms": unmatched,
        "Name_matched_accepted_family": accepted_family,
    }
