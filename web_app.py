"""Run with: python -m streamlit run web_app.py"""
import streamlit as st
from web_client import ApiError, request_api
import career_ui
import history_ui
from file_import import upload_control
import ui_theme
from career_workflow import run_review

st.set_page_config(page_title="投递小助手", page_icon="✦", layout="wide")
ui_theme.install()


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
    st.markdown('<div class="hero-kicker">看清差距 · 让努力更有方向</div>', unsafe_allow_html=True)
    st.title("投递小助手")
    st.write("从你的真实经历出发，看清岗位差距，找到具体改善方向。")
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
            st.write("**01 · 对照岗位**  放入简历和想投递的岗位 JD。")
            st.write("**02 · 看清差距**  对照岗位要求，明确下一步努力。")
            st.write("**03 · 改善再投递**  按清单完成实践，补充成果后重新评估。")
            st.caption("尚未体现不代表不会；补充真实经历可帮助纠正判断。")


def workspace():
    history_ui.apply_pending()
    with st.sidebar:
        st.markdown('<div class="sidebar-brand"><span class="brand-mark">投</span>投递小助手</div>', unsafe_allow_html=True)
        st.write("已登录 · " + st.session_state.get("user_name", ""))
        page = st.radio("前往", ["工作台", "我的历史"], key="workspace_page", on_change=history_ui.clear_lists)
        st.caption("已保存内容可在「我的历史」找回。")
        if st.button("退出登录", use_container_width=True):
            clear_session()
            st.rerun()
        st.divider()
        st.write("**使用顺序**")
        st.write("1. 放入简历和岗位 JD\n2. 看差距、找下一步\n3. 按清单改善，再评估投递")
        st.caption("新分析、对话和计划会自动保存。未点击保存的输入草稿仍只在当前页面。")
    if page == "我的历史":
        history_ui.render(api, handle_error)
        return
    if st.session_state.get('history_loaded_notice'):
        st.success(st.session_state.pop('history_loaded_notice'))
    st.markdown('<div class="hero-kicker">看清差距 · 让努力更有方向</div>', unsafe_allow_html=True)
    st.title("投递小助手")
    st.caption("对照岗位 JD，看清差距、明确努力方向，改善后再投递。已有资料可从左侧「我的历史」继续。")
    draft_context = ({'resume_text': st.session_state.get('resume_text', '').strip()},
        {field: st.session_state.get(field, '').strip() for field in ('company', 'job_title', 'jd_text')})
    progress = st.session_state.get('career') if st.session_state.get('career_context') == draft_context else None
    ui_theme.progress_pills(progress)
    if progress:
        if not progress.get('history_saved'):
            st.warning(progress.get('persistence_warning') or "当前进度尚未确认保存到历史。离开前请点击保存当前进度。")
        if not progress.get("history_saved") and st.button("保存当前进度"):
            try:
                saved = api('POST','/history/save-progress',{'report_token':progress['report_token']})
                if saved.get('career'):
                    st.session_state['career'] = saved['career']
                else:
                    progress.update(history_saved=True,history_id=saved['id'],persistence_warning='')
                st.rerun()
            except ApiError as exc:
                handle_error(exc)
    inputs, assessment, output = st.tabs(["① 对照岗位", "② 看清差距", "③ 目标清单"],
        default=st.session_state.get('workspace_default_tab', '① 对照岗位'))
    workflow = st.session_state.get('workflow_result')
    if workflow and workflow.get('context') == draft_context and workflow.get('plan_state') == 'failed':
        st.warning("差距分析已完成，行动计划暂未完成。分析结果已保留，请在「③ 目标清单」重试生成计划。")
        with st.expander("查看未完成原因"):
            st.write(workflow.get('plan_error', '暂时无法完成'))
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
            st.caption("✓ 已保存" if resume_ready else "分析时自动保存；也可先单独保存留待下次使用。")
        with right:
            st.subheader("02  目标岗位")
            upload_control("岗位", "jd_text")
            company = st.text_input("公司名称（选填）", key="company", placeholder="招聘公司的名称")
            title = st.text_input("职位名称（选填）", key="job_title", placeholder="例如：AI 应用工程师")
            jd = st.text_area("岗位职责与任职要求", max_chars=40000, height=175, key="jd_text", placeholder="粘贴招聘描述，无需整理成 JSON。")
            job_data = {"company": company.strip(), "job_title": title.strip(), "jd_text": jd.strip()}
            job_ready = bool(st.session_state.get("job_description_id")) and st.session_state.get("saved_job") == job_data
            if st.button("保存岗位", use_container_width=True, disabled=not jd.strip() or job_ready):
                try:
                    row = api("POST", "/job-descriptions", job_data)
                    st.session_state.update(job_description_id=row["id"], saved_job=job_data)
                    st.rerun()
                except ApiError as exc:
                    handle_error(exc)
            st.caption("✓ 已保存" if job_ready else "分析时自动保存；也可先单独保存留待下次使用。")
        st.divider()
        st.subheader("看看这个岗位适不适合我")
        st.caption("填写两份资料后直接分析，会自动保存资料。你会看到已满足的要求、待确认的经历和需要补齐的能力。")
        auto_plan = st.checkbox("分析后帮我安排下一步", value=False, key="auto_plan",
            help="根据当前证据选择先问一两项经历，或参考知识库制定实践步骤。可以跳过提问；已有任务会保留。会增加模型调用和等待时间。")
        if st.button("分析岗位与能力差距",type="primary",use_container_width=True,disabled=not (resume.strip() and jd.strip())):
            try:
                with st.status("准备分析本次岗位", expanded=True) as status:
                    def stage(message):
                        status.update(label=message)
                        st.write(message)
                    outcome = run_review(api, st.session_state, resume_data, job_data,
                                         auto_plan=auto_plan, on_stage=stage)
                    st.session_state['workflow_result'] = {'context':(resume_data, job_data), **outcome}
                    incomplete = outcome['plan_state'] == 'failed'
                    status.update(label="分析已完成，行动计划暂未完成" if incomplete else "本次分析已完成",
                                  state="error" if incomplete else "complete", expanded=incomplete)
                st.session_state['workspace_default_tab'] = '③ 目标清单' if outcome['plan_state']=='complete' else '② 看清差距'
                st.session_state['history_loaded_notice'] = ("差距分析和行动计划已完成，可以从第一项实践开始。"
                    if outcome['plan_state']=='complete' else "差距分析已完成，助手有一两项经历想和你确认，也可以跳过。"
                    if outcome['plan_state']=='waiting' else "差距分析已完成，先看看哪些要求需要关注。")
                st.rerun()
            except ApiError as exc:
                handle_error(exc)
        if not (resume_ready and job_ready):
            st.info("填写简历和岗位 JD 即可分析，公司和职位名称选填，无需分别保存。")
    context=(resume_data,job_data)
    with assessment:
        career_ui.analysis_panel(context)
        active_report = (progress or {}).get('report', {})
        with st.expander("补充经历 / 纠正判断（可选）", expanded=bool(active_report.get("pending")) or
                         active_report.get('agent', {}).get('status') == 'waiting'):
            career_ui.conversation_panel(context,api,handle_error)
    with output:
        career_ui.checklist_panel(context,api,handle_error)



if st.session_state.get("notice"):
    st.warning(st.session_state.pop("notice"))
if not st.session_state.get("token"):
    authentication()
else:
    workspace()
