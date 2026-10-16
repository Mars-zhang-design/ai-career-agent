"""Generate bounded paragraph patches, then assemble from unchanged source slices."""
from collections import Counter
import re


def split_segments(resume):
    # Keep offsets into the original, including CRLF and repeated identical lines.
    return [{"segment_id": index, "start": match.start(), "end": match.end(),
             "text": match.group(), "editable": len(match.group().strip()) >= 20}
            for index, match in enumerate(re.finditer(r"[^\r\n]+", resume), 1)
            if match.group().strip()]


def validate_plan(segments, plan, jd):
    lookup = {s["segment_id"]: s for s in segments}
    problems, used = [], set()
    if not plan.edits:
        return ["没有可应用的分段改写；请选择有岗位相关事实的段落进行改写。"]
    for edit in plan.edits:
        prefix = f"段落{edit.segment_id}："
        segment = lookup.get(edit.segment_id)
        if segment is None or not segment["editable"]:
            problems.append(prefix + "段落不存在或是受保护的短行，请重新选择。")
            continue
        if edit.segment_id in used:
            problems.append(prefix + "同一段落只能修改一次。")
        used.add(edit.segment_id)
        original = segment["text"]
        if not edit.optimized.strip() or "\n" in edit.optimized or "\r" in edit.optimized:
            problems.append(prefix + "请返回单段非空改写，不要生成多段或整份简历。")
        if not edit.issue.strip() or not edit.reason.strip():
            problems.append(prefix + "必须说明具体问题和修改理由。")
        if any(not quote.strip() or quote not in original for quote in edit.evidence):
            problems.append(prefix + "原文依据必须逐字引用这个段落，不能引用其他经历。")
        if not edit.jd_evidence.strip() or edit.jd_evidence not in jd:
            problems.append(prefix + "岗位依据必须逐字来自用户的招聘描述。")
        numbers = lambda text: Counter(re.findall(r"\d+(?:[.,]\d+)*%?", text))
        if numbers(original) != numbers(edit.optimized):
            problems.append(prefix + "不能新增、删除或修改原文数字。")
        levels = lambda text: Counter(re.findall(r"精通|熟练掌握|熟练|熟悉|掌握|了解|使用过", text))
        if levels(original) != levels(edit.optimized):
            problems.append(prefix + "不能擅自改变原文的技能熟练度表述。")
    return problems


def assemble_resume(resume, segments, plan):
    lookup = {s["segment_id"]: s for s in segments}
    edits = sorted(plan.edits, key=lambda e: lookup[e.segment_id]["start"])
    cursor, pieces, suggestions = 0, [], []
    for edit in edits:
        segment = lookup[edit.segment_id]
        pieces.extend([resume[cursor:segment["start"]], edit.optimized])
        cursor = segment["end"]
        suggestions.append({**edit.model_dump(), "original": segment["text"]})
    pieces.append(resume[cursor:])
    return "".join(pieces), suggestions
