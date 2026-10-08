"""Validate requested departure and arrival windows against calendar dates."""
from datetime import date, timedelta
import re

from app.ai import planning_feasibility as checks
from app.models.itinerary import ItineraryData


_WINDOW = re.compile(
    r"(?:(?P<iso>\d{4}-\d{2}-\d{2})|(?:(?P<month>\d{1,2})月)?(?P<day>\d{1,2})[日号])"
    r"\s*(?P<period>早上|上午|中午|下午|傍晚|晚上|当晚|晚)(?P<clause>[^，。；\n]{0,80})"
)
_BOUNDS = {"早上": ("06:00", "11:59"), "上午": ("06:00", "11:59"),
           "中午": ("11:00", "14:00"), "下午": ("12:00", "17:59"),
           "傍晚": ("17:00", "19:30"), "晚上": ("18:00", "23:59"),
           "当晚": ("18:00", "23:59"), "晚": ("18:00", "23:59")}
_TARGET = re.compile(r"(?:到达|抵达|返回|回到|飞返|回)([\u4e00-\u9fff]{2,8})(?=[，。、；\s]|$)")


def time_window_problems(data: ItineraryData, text: str, retained_facts: dict | None = None) -> list[checks.Problem]:
    facts = checks._usable_facts(retained_facts)
    origin_match = re.search(r"出发地[：:]\s*([\u4e00-\u9fff]{2,8})", text)
    origin = origin_match.group(1) if origin_match else ""
    windows, seen = [], set()
    for match in _WINDOW.finditer(text):
        clause = re.split(r"\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}[日号]", match.group("clause"))[0]
        if re.search(r"出发|启程|起飞", clause):
            role = "departure"
        elif re.search(r"回|到达|抵达", clause):
            role = "arrival"
        else:
            continue
        if match.group("iso"):
            target_date = match.group("iso")
        else:
            day = int(match.group("day"))
            month = int(match.group("month")) if match.group("month") else None
            matches = [item.date for item in data.itinerary if int(item.date[8:10]) == day and (month is None or int(item.date[5:7]) == month)]
            if len(matches) != 1:
                continue
            target_date = matches[0]
        target = ""
        if role == "arrival":
            target_match = _TARGET.search(clause)
            target = target_match.group(1) if target_match else origin if "回" in clause else ""
        key = (target_date, match.group("period"), role, target)
        if key not in seen:
            seen.add(key)
            windows.append(key)
    problems = []
    for target_date, period, role, target in windows:
        low, high = _BOUNDS[period]
        matched = False
        for day in data.itinerary:
            for schedule in day.schedules:
                referenced = [facts[ref] for ref in schedule.fact_refs if ref in facts]
                transport = [fact for fact in referenced if fact.get("tool") in checks.FLIGHT_TOOLS or fact.get("tool") == checks.RAIL_TOOL]
                if not checks._is_transport_leg(schedule, referenced, transport):
                    if not re.search(r"跨城|自驾|驾车前往", schedule.activity):
                        continue
                start, end = checks._normalize_clock(schedule.start_time), checks._normalize_clock(schedule.end_time)
                clock = start if role == "departure" else end
                calendar = day.date
                if role == "arrival" and start and end and end < start:
                    calendar = (date.fromisoformat(day.date) + timedelta(days=1)).isoformat()
                if calendar != target_date or not clock or not low <= clock <= high:
                    continue
                if target:
                    cities = [str(fact.get("arrive_city") or "") for fact in transport if fact.get("arrive_city")]
                    if cities:
                        if not any(city in target or target in city for city in cities):
                            continue
                    elif target not in " ".join(filter(None, (schedule.activity, schedule.transport, schedule.place_name))):
                        continue
                matched = True
                break
            if matched:
                break
        if not matched:
            action = f"到达{target}" if role == "arrival" else "出发"
            problems.append(checks.Problem(
                message=f"用户要求 {target_date} {period}{action}，但没有 {low}–{high} 内的对应交通时刻；到达约束须检查到达时间和实际到达日期，不能用起飞时间代替",
                date=target_date,
            ))
    return problems
