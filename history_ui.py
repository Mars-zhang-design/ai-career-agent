"""Personal library; no shared caches, direct SQL, or model calls."""
import streamlit as st
from web_client import ApiError

LABELS = {'sessions':'分析与学习进度','optimizations':'历史优化简历','resumes':'已保存的简历','jobs':'已保存的岗位'}
ACTIONS = {'review':'岗位分析','chat':'对话补充','confirm':'能力确认','make_plan':'能力计划','manual':'手动保存'}


def apply_pending():
    value = st.session_state.pop('history_load_pending', None)
    if value is None:
        return
    for key in ('career','career_context','result','result_context','career_polish','target_resume','promoted_resume','workflow_result'):
        st.session_state.pop(key, None)
    resume, job = value.get('resume'), value.get('job')
    if resume:
        st.session_state.update(resume_text=resume['resume_text'], resume_id=resume['id'],
                                saved_resume={'resume_text':resume['resume_text']})
    if job:
        fields = {k:job[k] for k in ('company','job_title','jd_text')}
        st.session_state.update(**fields, job_description_id=job['id'], saved_job=fields)
    if value.get('career'):
        st.session_state['career'] = value['career']
        st.session_state['career_context'] = (st.session_state['saved_resume'], st.session_state['saved_job'])
    st.session_state['workspace_page'] = '工作台'
    st.session_state['workspace_default_tab'] = '② 看清差距' if value.get('career') else '① 对照岗位'
    st.session_state['history_loaded_notice'] = '已加载保存的资料与进度。可继续查看、对话或生成计划，无需重新分析。' if value.get('career') else '历史资料已填入工作台，原记录保留。请选择另一份资料后再分析。'


def label(row, kind):
    date = str(row.get('created_at','')).replace('T',' ')[:19]
    if kind == 'optimizations':
        name = f"优化简历 #{row['id']} · 原简历 #{row['resume_id']}"
    elif kind == 'sessions':
        name = f"{ACTIONS.get(row.get('action'),'工作进度')} · 简历 #{row['resume_id']} / 岗位 #{row['job_description_id']}"
    else:
        name = str(row.get('title','')).replace('\n',' ')[:60] or '未命名资料'
    return f'{name} · {date}'


def render(api, handle_error):
    st.title('我的历史')
    st.caption('仅显示当前账号的数据。退出登录不会删除已保存内容。')
    kind = st.radio('查看哪类内容', list(LABELS), format_func=LABELS.get, horizontal=True, key='history_kind')
    state_key = 'history_pages_' + kind
    pages = st.session_state.setdefault(state_key, [0])
    before = pages[-1]
    cache_key = f'history_list_{kind}_{before}'
    if st.button('刷新历史记录'):
        st.session_state.pop(cache_key, None)
        st.session_state.pop('history_detail', None)
    try:
        if cache_key not in st.session_state:
            st.session_state[cache_key] = api('GET', f'/history/{kind}?before={before}')
        listing = st.session_state[cache_key]
    except ApiError as exc:
        handle_error(exc)
        return
    rows = listing.get('items', [])
    if not rows:
        st.info('这个分类下还没有保存的记录。新分析、对话确认和能力计划会自动保存；旧会话未保存的内容无法恢复。' if kind=='sessions' else '这个分类下还没有保存的记录。')
    else:
        selected = st.selectbox('选择记录', rows, format_func=lambda row:label(row,kind), key=f'history_pick_{kind}_{before}')
        st.caption('每页最多20条，最新记录在前。日期沿用数据库保存时间。加载资料会替换当前页面草稿，请先保存需要保留的内容。')
        if st.button('打开记录', type='primary'):
            try:
                record = api('GET', f"/history/{kind}/{selected['id']}")
                st.session_state['history_detail'] = (kind, selected['id'], record)
            except ApiError as exc:
                handle_error(exc)
        cached = st.session_state.get('history_detail')
        if cached and cached[:2] == (kind, selected['id']):
            show_record(kind, cached[2], api, handle_error)
    a,b = st.columns(2)
    if a.button('上一页', disabled=len(pages)==1):
        pages.pop(); st.rerun()
    if b.button('更早记录', disabled=not listing.get('next_before')):
        pages.append(listing['next_before']); st.rerun()


def show_record(kind, record, api, handle_error):
    if kind in ('resumes','optimizations'):
        text = record['resume_text'] if kind=='resumes' else record['optimized_resume']
        with st.expander('查看完整简历', expanded=True):
            st.text(text)
        st.download_button('下载这份简历', text.encode('utf-8-sig'), file_name=f"简历_{record['id']}.txt",mime='text/plain')
        if kind=='resumes':
            if st.button('使用这份简历'):
                st.session_state['history_load_pending']={'resume':record};st.rerun()
        else:
            st.caption('这是已保存的优化正文。早期记录未保存逐段改写理由，无法补回；使用此版本会另存一份简历。')
            if st.button('另存为简历并继续分析'):
                try:
                    saved = api('POST','/resumes',{'resume_text':text})
                    st.session_state['history_load_pending']={'resume':{'id':saved['id'],'resume_text':text}}
                    st.rerun()
                except ApiError as exc:
                    handle_error(exc)
    elif kind=='jobs':
        st.subheader(record['job_title'])
        st.caption(record['company'])
        st.text(record['jd_text'])
        if st.button('使用这个岗位'):
            st.session_state['history_load_pending']={'job':record};st.rerun()
    else:
        report = record['report']
        a,b,c = st.columns(3)
        a.metric('岗位证据匹配度', f"{report['score']} / 100")
        b.metric('能力任务', len(report['tasks']))
        c.metric('保存的对话消息', len(report['messages']))
        st.caption('恢复分析、最近12条对话、待确认补充和能力计划。目标清单会按恢复的状态自动显示。')
        if st.button('恢复进度，继续工作', type='primary'):
            try:
                st.session_state['history_load_pending'] = api('GET',f"/history/sessions/{record['id']}/resume")
                st.rerun()
            except ApiError as exc:
                handle_error(exc)
        with st.expander('查看保存的能力计划'):
            if report['tasks']:
                from career_ui import plan_export
                text=plan_export(report)
                st.text(text)
                st.download_button('下载保存的计划',text.encode('utf-8-sig'),file_name='已保存能力计划.txt',mime='text/plain')
            else:
                st.info('这份进度还没有能力计划。')


def clear_lists():
    for key in list(st.session_state):
        if key.startswith('history_list_'):
            st.session_state.pop(key, None)
