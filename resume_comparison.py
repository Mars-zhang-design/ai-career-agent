"""Escaped, deterministic comparison of the actual resume texts (no model calls)."""
from difflib import SequenceMatcher
from html import escape


def _highlight(text, tag):
    return f'<{tag}>' + escape(text) + f'</{tag}>' if text else ''


def _inline(before, after):
    # Bound character matching for long/repetitive resumes; block highlighting
    # still preserves the full text when a paragraph is too large.
    if len(before) + len(after) > 4000:
        return _highlight(before, 'del'), _highlight(after, 'ins')
    left, right = [], []
    for kind, a, b, c, d in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        left.append(escape(before[a:b]) if kind == 'equal' else _highlight(before[a:b], 'del'))
        right.append(escape(after[c:d]) if kind == 'equal' else _highlight(after[c:d], 'ins'))
    return ''.join(left), ''.join(right)


def compare_resume(before, after):
    """Return lossless aligned blocks, with escaped HTML highlighting per side."""
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    blocks = []
    for kind, a, b, c, d in SequenceMatcher(None, old, new).get_opcodes():
        original, polished = ''.join(old[a:b]), ''.join(new[c:d])
        left, right = (escape(original), escape(polished)) if kind == 'equal' else _inline(original, polished)
        blocks.append({'kind': kind, 'before': original, 'after': polished,
                       'before_html': left, 'after_html': right})
    return blocks


def render_resume_comparison(original, polished, *, key='resume_compare'):
    import streamlit as st
    blocks = compare_resume(original, polished)
    changes = [block for block in blocks if block['kind'] != 'equal']
    st.markdown("""<style>
    .resume-comparison {white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;
      font-family:inherit;font-size:1rem;color:#203047;background:#fff;
      padding:18px;border:1px solid #dce5f0;border-radius:10px;}
    .resume-comparison del {background:#ffe4e6;color:#9f1239;text-decoration:line-through;}
    .resume-comparison ins {background:#dcfce7;color:#166534;text-decoration:underline;}
    </style>""", unsafe_allow_html=True)
    st.caption(f'共 {len(changes)} 处文本变化 · 左侧红色划线：删改前；右侧绿色下划线：新增或改写后。')
    view = st.radio('对照方式', ['只看改动', '完整对照'], horizontal=True, key=key)
    if not changes:
        st.info('这次没有修改正文，原简历与美化后内容一致。可切换完整对照查看。')
    shown = changes if view == '只看改动' else [{
        'before_html': ''.join(block['before_html'] for block in blocks),
        'after_html': ''.join(block['after_html'] for block in blocks),
        'before': original, 'after': polished,
    }]
    for index, block in enumerate(shown, 1):
        if view == '只看改动':
            st.markdown(f'**修改 {index}**')
        left, right = st.columns(2, gap='medium')
        for pane, name, side in ((left, '你输入的简历', 'before'), (right, '美化后的简历', 'after')):
            with pane:
                st.caption(name)
                if block[side]:
                    markup = block[side + '_html'].replace('\r', '&#13;').replace('\n', '&#10;')
                    st.markdown('<div class="resume-comparison">' + markup + '</div>', unsafe_allow_html=True)
                else:
                    st.caption('此处为新增内容' if side == 'before' else '此处内容已删除')
    return len(changes)
