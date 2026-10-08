"""Check visit hours and route eligibility against cited provider facts."""
from __future__ import annotations

from datetime import date
import re

from app.ai.planning_feasibility import Problem
from app.ai.transport_facts import normalize_transport_fact
from app.models.itinerary import ItineraryData
from app.services.schedule_kind import classify_schedule

_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[-—–~～至]\s*(\d{1,2}):(\d{2})")
_WEEK = re.compile(r"周([一二三四五六日天])(?:\s*(?:至|到|[-—~～])\s*周?([一二三四五六日天]))?")
_DAYS = dict(zip("一二三四五六日天", [0, 1, 2, 3, 4, 5, 6, 6]))
_RESTRICTED = re.compile(r"(?:市民|居民|员工|内部|职工)(?:专线|专用|通道|班车)|仅限.{0,8}(?:居民|员工|职工)")


def _weekdays(text: str) -> set[int]:
    days = set()
    for match in _WEEK.finditer(text):
        start, end = _DAYS[match[1]], _DAYS[match[2]] if match[2] else _DAYS[match[1]]
        days.update((start + offset) % 7 for offset in range((end - start) % 7 + 1))
    return days


def _hours(text: str, target: date) -> list[tuple[int, int]] | None:
    # Seasonal/holiday exceptions need an actual dated source, not guessing.
    if re.search(r"\d+月|节假|法定|旺季|淡季|夏季|冬季", text):
        return None
    windows = []
    for segment in re.split(r"[；;\n]", text):
        weekdays = _weekdays(segment)
        if weekdays and target.weekday() not in weekdays:
            continue
        if re.search(r"全天关闭|不开放|闭馆|闭园|休息", segment):
            return []
        if "24小时" in segment or "全天开放" in segment:
            windows.append((0, 1440))
        for match in _RANGE.finditer(segment):
            h1, m1, h2, m2 = map(int, match.groups())
            if h1 > 24 or h2 > 24 or m1 >= 60 or m2 >= 60:
                continue
            start, end = h1 * 60 + m1, h2 * 60 + m2
            windows.append((start, end if end >= start else end + 1440))
    return windows or None


def opening_hours_problems(data: ItineraryData, facts: dict) -> list[Problem]:
    problems = []
    for day in data.itinerary:
        target = date.fromisoformat(day.date)
        for row in day.schedules:
            if not row.start_time or not row.end_time or not row.place_name:
                continue
            for ref in row.fact_refs:
                fact = facts.get(ref, {})
                name = str(fact.get("name") or "")
                if not name or not (name in row.place_name or row.place_name in name):
                    continue
                if classify_schedule(row, fact) != "attraction":
                    continue
                hours = str(fact.get("opening_hours_week") or "")
                if not hours and target == date.today():
                    hours = str(fact.get("opening_hours_today") or "")
                windows = _hours(hours, target)
                if windows is None:
                    continue
                start = sum(int(x) * multiplier for x, multiplier in zip(row.start_time.split(":"), (60, 1)))
                end = sum(int(x) * multiplier for x, multiplier in zip(row.end_time.split(":"), (60, 1)))
                if end < start:
                    end += 1440
                entry = re.search(r"(?:最晚进入|停止入场|停止售票|停止入园|最后入场)\s*(\d{1,2}):(\d{2})", hours)
                after_entry = bool(entry and start >= int(entry[1]) * 60 + int(entry[2]))
                if not after_entry and any(a <= start + shift < end + shift <= b for a, b in windows for shift in (0, 1440)):
                    continue
                problems.append(Problem(
                    message=f"{day.date} {name} 安排在 {row.start_time}–{row.end_time}，与所引开放规则“{hours}”不符；调整到开放时段或改日，转场和闭门后的街区散步不能算作场馆内参观",
                    date=day.date, schedule_id=row.id,
                    user_note="参观时段尚未与开放及入场时间核对一致，请调整后再出发",
                ))
                break
    return problems


def restricted_route_problems(data: ItineraryData, facts: dict, user_text: str) -> list[Problem]:
    # The user may explicitly establish eligibility; absence is not consent.
    eligible = bool(re.search(r"(?:我|本人)(?:已经|已|确实)?(?:持有|拥有|具备)(?:当地|有效的?)?(?:市民卡|居民资格|员工证|通行资格)", user_text))
    if eligible:
        return []
    problems = []
    for day in data.itinerary:
        for row in day.schedules:
            for ref in row.fact_refs:
                fact = facts.get(ref, {})
                if fact.get("tool") != "amap_route":
                    continue
                alternatives = fact.get("alternatives") or [fact]
                restricted = []
                unrestricted = False
                for route in alternatives:
                    names = [str(step.get("line_name") or step.get("instruction") or "")
                             for step in route.get("steps", []) if isinstance(step, dict)]
                    found = [name for name in names if _RESTRICTED.search(name)]
                    restricted.extend(found)
                    if names and not found:
                        unrestricted = True
                text = f"{row.activity} {row.transport or ''}"
                if not restricted or (unrestricted and not any(name.split("(")[0] in text for name in restricted)):
                    continue
                problems.append(Problem(
                    message=f"{day.date} {row.place_name or row.activity} 引用的路线包含资格限制：{'、'.join(dict.fromkeys(restricted))}；用户未说明具备资格。改查并使用公开游客路线，不得继承这条专线的票价、时刻或码头；不能查证时明确待核验并取消确定班次安排",
                    date=day.date, schedule_id=row.id,
                    user_note="该路线有乘坐资格限制，需核对资格或改用公开线路",
                ))
                break
    return problems


def airport_wait_problems(data: ItineraryData, facts: dict, user_text: str) -> list[Problem]:
    """Flag avoidable long airport waits; leave user-requested buffers alone."""
    if re.search(r"(?:提前|早些|早点).{0,12}(?:机场|候机)|(?:机场|候机).{0,8}(?:休息|等候)", user_text):
        return []
    problems = []
    for day in data.itinerary:
        for index, row in enumerate(day.schedules):
            if not row.start_time:
                continue
            flights = [normalize_transport_fact(facts[ref]) for ref in row.fact_refs if ref in facts]
            flights = [fact for fact in flights if fact.get("flight_no") and fact["flight_no"] in f"{row.activity} {row.transport or ''}"]
            if not flights:
                continue
            departure = sum(int(x) * multiplier for x, multiplier in zip(row.start_time.split(":"), (60, 1)))
            for earlier in reversed(day.schedules[:index]):
                if not earlier.end_time or not re.search(r"机场|航站楼", earlier.place_name or ""):
                    continue
                # Do not squeeze a booked flight connection.
                if any(normalize_transport_fact(facts[ref]).get("flight_no") for ref in earlier.fact_refs if ref in facts):
                    break
                city = str(flights[0].get("depart_city") or "").removesuffix("市")
                if city and city not in (earlier.place_name or ""):
                    continue
                arrival = sum(int(x) * multiplier for x, multiplier in zip(earlier.end_time.split(":"), (60, 1)))
                if departure - arrival > 240:
                    problems.append(Problem(
                        message=f"{day.date} 在 {earlier.end_time} 已到机场，航班 {row.start_time} 才起飞，候机超过4小时，用户未要求提前长时间等待；按已核实的班次倒排接驳、取行李和合理值机安检缓冲，将多余时间留作休息或机动，不得更改真实班次",
                        blocking=False, date=day.date, schedule_id=earlier.id,
                    ))
                break
    return problems
