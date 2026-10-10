import os
import re
import json
import uuid
import datetime

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = (
    os.getenv("DEEPSEEK_API_KEY")
    or os.getenv("DASHSCOPE_API_KEY")
    or os.getenv("OPENAI_API_KEY")
)
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("MODEL", "deepseek-chat")

st.set_page_config(page_title="DDL捕手 Agent", layout="wide")
st.title("📌 DDL捕手 Agent")
st.caption("把课程群 / 邮件 / 通知里的非结构化 DDL，变成倒排计划、最小可交付和提交检查清单")

# ---------------- 侧边栏 ----------------
with st.sidebar:
    st.header("Agent 设置")
    today = st.date_input("今天日期", datetime.date.today())
    now_time = st.time_input("当前时间", datetime.datetime.now().time())
    energy = st.selectbox(
        "你当前的状态",
        ["正常", "很累，只想先做60分钟", "时间很多，想提前做完"]
    )
    st.markdown("---")
    st.write("API 状态：", "已配置" if API_KEY else "未配置，请在 .env 中设置")

# ---------------- 示例与输入 ----------------
example = """【人工智能课】同学们，大作业最终报告 10月15日 24:00 前交到教学网，提交 PDF + 代码压缩包。报告不少于 3000 字，要有实验对比。10月13日 课上每组 5 分钟汇报 PPT。
【社团通知】今晚 20:00 前填报名表，明天中午 12:00 前交策划案初稿。
【考试提醒】10月17日 下午六级考试，10月16日 前复习完听力。"""

if "input_text" not in st.session_state:
    st.session_state.input_text = ""

if st.button("填入示例"):
    st.session_state.input_text = example

text = st.text_area(
    "粘贴课程群 / 邮件 / 通知 / 待办文本",
    key="input_text",
    height=220,
    placeholder="例如：同学们，下周三24:00前交报告，提交PDF+代码压缩包……"
)

# ---------------- Prompt ----------------
def build_prompt(user_text, now_dt, energy):
    return f"""你是一个严谨的校园 DDL 规划 Agent。

当前时间：{now_dt.strftime('%Y-%m-%d %H:%M')}
用户状态：{energy}

请从下面文本中抽取所有任务，并生成可执行计划。
只输出 JSON，不要输出 Markdown，不要解释。

JSON 格式必须为：
{{
  "tasks": [
    {{
      "title": "任务名",
      "course": "课程/来源",
      "deadline": "YYYY-MM-DD HH:MM 或 null",
      "deadline_raw": "原文时间描述",
      "estimated_hours": 2.5,
      "priority": "高/中/低",
      "dependencies": ["依赖"],
      "submission": "提交方式/平台/格式",
      "deliverables": ["交付物"],
      "checklist": ["提交前检查项"],
      "minimal_deliverable": "如果只剩60分钟，最小可交付版本是什么",
      "schedule_blocks": [
        {{"time": "YYYY-MM-DD HH:MM-HH:MM", "action": "做什么"}}
      ],
      "risk": "可能风险"
    }}
  ],
  "overall_plan": ["按时间排序的行动建议"],
  "reminders": ["提醒文案"],
  "questions": ["需要用户确认的信息"]
}}

要求：
1. 日期必须结合当前时间计算，尽量输出绝对时间；不确定则 deadline=null，并放进 questions。
2. 优先级综合 deadline 远近、预计耗时、依赖、分值权重。
3. 如果用户状态是“很累，只想先做60分钟”，只安排 60 分钟内能推进的最小任务。
4. 检查清单要具体到学生作业：PDF、代码、命名、封面、引用、提交入口、压缩包等。
5. 只输出 JSON。

用户文本：
{user_text}
"""

# ---------------- LLM 调用 ----------------
def call_llm(prompt):
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "你是一个严谨的校园任务规划 Agent，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=4000,
    )
    return resp.choices[0].message.content

def extract_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            return json.loads(match.group(0))
        raise

# ---------------- 生成 ics ----------------
def parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def make_ics(plan):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DDL Agent//CN",
        "CALSCALE:GREGORIAN",
    ]
    for t in plan.get("tasks", []):
        dt = parse_dt(t.get("deadline"))
        if not dt:
            continue
        uid = str(uuid.uuid4()) + "@ddl-agent"
        dtstart = dt.strftime("%Y%m%dT%H%M%S")
        dtend = (dt + datetime.timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
        summary = t.get("title", "任务")
        desc = f"提交：{t.get('submission', '')}\\n检查清单：{'；'.join(t.get('checklist', []))}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

# ---------------- 主按钮 ----------------
if st.button("🚀 生成 DDL 计划", type="primary"):
    if not API_KEY:
        st.error("请先在 .env 中配置 API Key。")
    elif not text.strip():
        st.warning("请先粘贴一段课程群、邮件或通知文本。")
    else:
        with st.spinner("Agent 正在抽取 DDL、拆解任务、倒排计划……"):
            now_dt = datetime.datetime.combine(today, now_time)
            prompt = build_prompt(text, now_dt, energy)
            try:
                raw = call_llm(prompt)
                plan = extract_json(raw)
                plan["_energy"] = energy
                st.session_state["plan"] = plan
                st.session_state["raw"] = raw
            except Exception as e:
                st.error(f"生成失败：{e}")
                if "raw" in locals():
                    st.code(raw)

# ---------------- 展示结果 ----------------
if "plan" in st.session_state:
    plan = st.session_state["plan"]

    st.subheader("✅ 任务卡片")
    for i, t in enumerate(plan.get("tasks", []), 1):
        title = t.get("title", "未命名任务")
        deadline = t.get("deadline") or "待确认"
        priority = t.get("priority", "中")
        with st.expander(f"{i}. {title} ｜ DDL：{deadline} ｜ 优先级：{priority}", expanded=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**来源/课程：** {t.get('course', '')}")
                st.markdown(f"**预计耗时：** {t.get('estimated_hours', '')} 小时")
                st.markdown(f"**提交方式：** {t.get('submission', '')}")
            with c2:
                st.markdown("**交付物：**")
                for x in t.get("deliverables", []):
                    st.write("- " + x)
                st.markdown("**依赖：**")
                for x in t.get("dependencies", []):
                    st.write("- " + x)
            with c3:
                st.markdown("**提交前检查清单：**")
                for x in t.get("checklist", []):
                    st.write("- " + x)

            current_energy = plan.get("_energy", energy)
            if current_energy == "很累，只想先做60分钟" and t.get("minimal_deliverable"):
                st.info("60 分钟最小可交付：" + t.get("minimal_deliverable", ""))
            if t.get("risk"):
                st.warning("风险：" + t.get("risk", ""))

            if t.get("schedule_blocks"):
                st.markdown("**建议时间块：**")
                for b in t["schedule_blocks"]:
                    st.write(f"- {b.get('time', '')}：{b.get('action', '')}")

    st.subheader("🗓️ 总体倒排计划")
    for x in plan.get("overall_plan", []):
        st.write("- " + x)

    st.subheader("🔔 提醒文案")
    for x in plan.get("reminders", []):
        st.markdown(f"- {x}")

    st.subheader("❓ 需要你确认的信息")
    for x in plan.get("questions", []):
        st.write("- " + x)

    ics = make_ics(plan)
    st.download_button(
        "📥 下载 .ics 日历文件",
        data=ics,
        file_name="ddl_plan.ics",
        mime="text/calendar",
    )

    with st.expander("查看原始 JSON"):
        st.json(plan)