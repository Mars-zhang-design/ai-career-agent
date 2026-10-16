"""Small local text imports; no OCR, persistence or model calls."""
from io import BytesIO
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET


def extract_text(name, data):
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("文件不能超过5MB。")
    suffix = Path(name).suffix.lower()
    try:
        if suffix in (".txt", ".md"):
            for encoding in ("utf-8-sig", "utf-16", "gb18030"):
                try:
                    text = data.decode(encoding)
                    break
                except UnicodeError:
                    continue
            else:
                raise ValueError("无法识别文本编码，请另存为UTF-8。")
        elif suffix == ".docx":
            with zipfile.ZipFile(BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 10 * 1024 * 1024:
                    raise ValueError("文档解压后过大。")
                xml = archive.read(info)
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise ValueError("文档包含不支持的XML定义。")
            root = ET.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text = "\n".join("".join(n.text or "" for n in p.findall(".//w:t", ns)) for p in root.findall(".//w:p", ns))
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ModuleNotFoundError:
                # Optional local dependency directory; normal installations use requirements-web.txt.
                sys.path.append(str(Path(__file__).resolve().parent / ".web-libs"))
                from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("暂不支持加密PDF，请解密后导入。")
            if len(reader.pages) > 30:
                raise ValueError("PDF请控制在30页以内。")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            raise ValueError("支持TXT、MD、DOCX及文字版PDF。")
    except ValueError:
        raise
    except Exception:
        raise ValueError("无法读取这个文件，请改用复制粘贴文本。") from None
    if not text.strip():
        raise ValueError("没有提取到文字；扫描件或图片请先转成文字。")
    if len(text) > 40000:
        raise ValueError("文本超过4万字，请精简后再导入。")
    return text.strip()


def upload_control(label, key):
    import streamlit as st
    with st.expander("从文件导入" + label):
        uploaded = st.file_uploader("选择" + label + "文件", type=["txt","md","docx","pdf"], key=key+"_file")
        st.caption("最大5MB；支持文字版PDF，暂不支持图片或扫描件。导入后请核对文字再保存。")
        if st.button("填入"+label+"内容", key=key+"_import", disabled=uploaded is None):
            try:
                st.session_state[key] = extract_text(uploaded.name, uploaded.getvalue())
                st.success("已填入，请核对下方内容。")
            except ValueError as exc:
                st.error(str(exc))
