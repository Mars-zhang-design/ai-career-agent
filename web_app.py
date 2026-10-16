"""Run with: python -m streamlit run web_app.py"""
import streamlit as st
from web_client import ApiError, request_api
import career_ui
from file_import import upload_control

st.set_page_config(page_title="求职工作台", page_icon="✦", layout="wide")
st.markdown("""<style>
.stApp {background: #f5f7fb;}
.block-container {max-width: 1180px; padding-top: 2.5rem;}
h1,h2,h3 {color: #142b49;}
[data-testid="stSidebar"] {background: #eaf0f8;}
[data-testid="stMetric"] {background: white; padding: 1.2rem; border-radius: 12px; border: 1px solid #dce5f0;}
[data-testid="stForm"] {background: white;}
.stButton button, .stDownloadButton button {border-radius: 8px;}
</style>""", unsafe_allow_html=True)


def clear_session():
    for key in list(st.session_state):
        del st.session_state[key]


def handle_error(exc):
    if exc.status == 401 and st.session_state.get("token"):
        clear_session()
        st.session_state["notice"] = "登录已过期，请重新登录。"
        st.rerun()
    st.error(str(exc))


def api(method, path, data=None):
    return request_api(method, path, token=st.session_state.get("token"), data=data)


def authentication():
    st.title("求职工作台")
    st.write("从你的真实经历出发，分析岗位差距，打磨简历表达。")
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        login, register = st.tabs(["登录", "注册账号"])
        with login:
            with st.form("login", clear_on_submit=True):
                email = st.text_input("邮箱", key="login_email")
                password = st.text_input("密码", type="password", key="login_password")
                submit = st.form_submit_button("登录工作台", type="primary", use_container_width=True)
            if submit:
                if not email.strip() or not password:
                    st.error("请填写邮箱和密码。")
                else:
                    try:
                        result = request_api("POST", "/auth/login", data={"email": email.strip(), "password": password})
                        token = result.get("access_token")
                        if not isinstance(token, str) or not token:
                            raise ApiError("登录响应异常，请重试。")
                        clear_session()
                        st.session_state.update(token=token, user_name=result.get("name", ""))
                        st.rerun()
                    except ApiError as exc:
                        handle_error(exc)
        with register:
            with st.form("register", clear_on_submit=True):
                name = st.text_input("称呼", key="register_name")
                email = st.text_input("注册邮箱", key="register_email")
                password = st.text_input("设置密码", type="password", key="register_password", help="至少 6 位，UTF-8 编码不超过 72 字节")
                confirm = st.text_input("再次输入密码", type="password", key="register_confirm")
                submit = st.form_submit_button("创建账号", use_container_width=True)
            if submit:
                if not name.strip() or not email.strip():
                    st.error("请填写称呼和邮箱。")
                elif len(password) < 6 or len(password.encode("utf-8")) > 72:
                    st.error("密码至少 6 位，UTF-8 编码不能超过 72 字节。")
                elif password != confirm:
                    st.error("两次输入的密码不一致。")
                else:
                    try:
                        request_api("POST", "/auth/register", data={"name": name.strip(), "email": email.strip(), "password": password})
                        st.success("账号创建成功，请切换到登录。")
                    except ApiError as exc:
                        handle_error(exc)
    with right:
        with st.container(border=True):
            st.subheader("一次填写，清晰对照")
            st.write("**01 · 准备资料**  粘贴简历和想投递的岗位。")
            st.write("**02 · 选择任务**  先看差距，或直接优化表达。")
            st.write("**03 · 带走结果**  查看改写对比，复制或下载简历。")
            st.caption("模型只应基于原始经历改写；投递前请核对事实。")


def render_result(result):
    if result.get("status") == "error":
        st.error("这次任务没有完成。以下保留已完成的分析，不能作为已保存的优化结果。")
        for error in result.get("errors", []):
            st.write(error.get("message", "任务未完成"))
    analysis = result.get("analysis") or {}
    optimization = result.get("optimization")
    if analysis:
        score, state, count = st.columns(3)
        score.metric("原简历匹配度", f"{analysis.get('match_score', 0)} / 100")
        state.metric("优化记录", "已保存" if result.get("saved") else "未保存")
        count.metric("执行步骤", result.get("steps", 0))
        st.caption("匹配分数是模型的辅助判断，可能波动，不代表录用概率或改写后的得分。")
        a, b = st.columns(2)
        with a:
            st.subheader("可匹配的能力")
            for skill in analysis.get("matched_skills", []):
                st.write("• " + skill)
        with b:
            st.subheader("尚未体现的能力")
            for skill in analysis.get("missing_skills", []):
                st.write("• " + skill)
        if analysis.get("warnings"):
            with st.expander("需要留意的差距", expanded=True):
                for warning in analysis["warnings"]:
                    st.write("• " + warning)
    if optimization:
        compare, resume = st.tabs(["改写前后", "完整简历与下载"])
        with compare:
            for index, suggestion in enumerate(optimization.get("rewrite_suggestions", []), 1):
                with st.container(border=True):
                    st.caption(f"修改 {index:02d}")
                    before, after = st.columns(2)
                    before.markdown("**原文**")
                    before.write(suggestion["original"])
                    after.markdown("**改写后**")
                    after.write(suggestion["optimized"])
                    if suggestion.get("issue"):
                        st.write("**原段问题：** " + suggestion["issue"])
                    if suggestion.get("reason"):
                        st.write("**修改理由：** " + suggestion["reason"])
                    if suggestion.get("jd_evidence"):
                        st.write("**对应岗位要求：** " + suggestion["jd_evidence"])
                    if suggestion.get("evidence"):
                        with st.expander("查看原文依据"):
                            for quote in suggestion["evidence"]:
                                st.text(quote)
                            st.caption("引用已核对来自原段；是否准确保留语义，仍需你确认。")
        with resume:
            text = optimization.get("optimized_resume", "")
            if not result.get("saved"):
                st.warning("这份结果尚未确认保存，请先核对任务提示。")
            st.text(text)
            st.download_button("下载简历文本", data=text.encode("utf-8"), file_name="优化简历.txt", mime="text/plain", use_container_width=True)
            with st.expander("复制全文"):
                st.caption("点击下方文本框右上角的复制按钮。")
                st.code(text, language=None, wrap_lines=True)
    elif result.get("status") == "success":
        st.info("本次已完成分析，没有生成优化简历。只分析模式或未达到设定匹配度时，这是正常结果。")
    if result.get("warnings"):
        with st.expander("处理过程提示"):
            st.caption("包含重试前的校验提示或检索降级说明，不一定代表最终结果仍有这些问题。")
            for warning in result["warnings"]:
                st.write("• " + warning)


def workspace():
    with st.sidebar:
        st.markdown("### 求职工作台")
        st.write("已登录 · " + st.session_state.get("user_name", ""))
        st.caption("登录凭证仅保留在本次页面会话。")
        if st.button("退出登录", use_container_width=True):
            clear_session()
            st.rerun()
        st.divider()
        st.write("**使用顺序**")
        st.write("1. 保存简历与岗位\n2. 分析差距、对话确认\n3. 能力计划与两种简历")
        st.caption("草稿、对话和分析保留在本次会话，请及时下载计划与简历。已保存的简历和优化记录仍在数据库中。")
    st.title("准备下一次投递")
    st.caption("保存真实资料，然后让 Agent 分析与改写。")
    inputs, assessment, conversation, plan, output = st.tabs(["资料与任务", "匹配分析", "对话补充", "能力计划", "简历与结果"])
    with inputs:
        left, right = st.columns(2, gap="large")
        with left:
            st.subheader("01  你的简历")
            upload_control("简历", "resume_text")
            resume = st.text_area("简历内容", max_chars=40000, height=330, key="resume_text", placeholder="直接粘贴完整简历，可以正常换行。")
            resume_data = {"resume_text": resume.strip()}
            resume_ready = bool(st.session_state.get("resume_id")) and st.session_state.get("saved_resume") == resume_data
            if st.button("保存简历", use_container_width=True, disabled=not resume.strip() or resume_ready):
                try:
                    row = api("POST", "/resumes", resume_data)
                    st.session_state.update(resume_id=row["id"], saved_resume=resume_data)
                    st.rerun()
                except ApiError as exc:
                    handle_error(exc)
            st.caption("已保存，可用于本次任务" if resume_ready else "尚未保存，或内容已有修改")
        with right:
            st.subheader("02  目标岗位")
            upload_control("岗位", "jd_text")
            company = st.text_input("公司名称", key="company", placeholder="招聘公司的名称")
            title = st.text_input("职位名称", key="job_title", placeholder="例如：AI 应用工程师")
            jd = st.text_area("岗位职责与任职要求", max_chars=40000, height=175, key="jd_text", placeholder="粘贴招聘描述，无需整理成 JSON。")
            job_data = {"company": company.strip(), "job_title": title.strip(), "jd_text": jd.strip()}
            job_ready = bool(st.session_state.get("job_description_id")) and st.session_state.get("saved_job") == job_data
            if st.button("保存岗位", use_container_width=True, disabled=not all(job_data.values()) or job_ready):
                try:
                    row = api("POST", "/job-descriptions", job_data)
                    st.session_state.update(job_description_id=row["id"], saved_job=job_data)
                    st.rerun()
                except ApiError as exc:
                    handle_error(exc)
            st.caption("已保存，可用于本次任务" if job_ready else "尚未保存，或内容已有修改")
        st.divider()
        st.subheader("03  从岗位差距开始")
        st.caption("分析会调用DeepSeek。完成后可以对话澄清能力，再生成学习计划、美化简历或预览目标版本。")
        if st.button("分析岗位与能力差距",type="primary",use_container_width=True,disabled=not (resume_ready and job_ready)):
            try:
                with st.spinner("正在逐项比对岗位要求与简历证据……"):
                    value=api("POST","/career/review",{"resume_id":st.session_state["resume_id"],
                        "job_description_id":st.session_state["job_description_id"]})
                career_ui.remember(value)
                st.session_state['career_context']=(resume_data,job_data)
                st.success("分析完成，切换到「匹配分析」或「对话补充」。")
            except ApiError as exc:
                handle_error(exc)
        if not (resume_ready and job_ready):
            st.info("请先保存简历和岗位。")
        with st.expander("更多：原有 Agent 分析、岗位改写与条件优化"):
            st.subheader("03  选择处理方式")
            modes = {"只分析匹配度": "analyze", "直接优化简历": "optimize", "达到匹配度才优化": "conditional"}
            selected = st.radio("这次想做什么？", list(modes), horizontal=True, key="mode_label")
            threshold = st.slider("达到多少分后优化？", 0, 100, 60, disabled=modes[selected] != "conditional")
            instruction = st.text_area("补充要求（可选）", max_chars=4000, key="instruction", placeholder="例如：突出后端开发经历，精简空泛自评，不添加未掌握的技能。", height=90)
            use_knowledge = st.checkbox("参考岗位知识库", value=False, help="当前知识库内容有限；首次使用可能需要下载模型。")
            st.caption("运行会调用 DeepSeek 并产生 API 费用。生成并通过检查的优化结果会自动保存。")
            if not resume_ready or not job_ready:
                st.info("请先保存上方两份资料。修改内容后，需要再次保存才能运行。")
            if st.button("开始处理", disabled=not (resume_ready and job_ready), use_container_width=True):
                st.session_state.pop("result", None)
                st.session_state["result_context"] = (resume_data, job_data)
                payload = {"resume_id": st.session_state["resume_id"], "job_description_id": st.session_state["job_description_id"],
                           "mode": modes[selected], "match_threshold": threshold, "use_knowledge": use_knowledge,
                           "instruction": instruction.strip() or "基于真实经历分析匹配情况，按所选模式处理，不编造技能或经历。"}
                with st.spinner("正在分析资料并处理任务，请稍候，不要重复提交……"):
                    try:
                        st.session_state["result"] = api("POST", "/resume/agent-by-id", payload)
                    except ApiError as exc:
                        if exc.payload and "task_id" in exc.payload:
                            st.session_state["result"] = exc.payload
                        handle_error(exc)
                if st.session_state.get("result", {}).get("status") == "success":
                    st.success("处理完成，点击上方「简历与结果」。")
    context=(resume_data,job_data)
    with assessment:
        career_ui.analysis_panel(context)
    with conversation:
        career_ui.conversation_panel(context,api,handle_error)
    with plan:
        career_ui.plan_panel(context,api,handle_error)
    with output:
        career_ui.resume_panel(context,api,handle_error)
        st.divider()
        st.subheader("原有 Agent 任务结果")
        result = st.session_state.get("result")
        if not result:
            st.info("还没有处理结果。先在「资料与任务」中保存内容并开始处理。")
        else:
            if st.session_state.get("result_context") != (resume_data, job_data):
                st.warning("资料已经修改，下面是上一次提交的结果。请保存新资料并重新处理。")
            render_result(result)


if st.session_state.get("notice"):
    st.warning(st.session_state.pop("notice"))
if not st.session_state.get("token"):
    authentication()
else:
    workspace()
