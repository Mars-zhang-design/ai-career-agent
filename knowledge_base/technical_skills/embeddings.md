---
title: Embedding 与语义检索
source_url: https://www.sbert.net/docs/sentence_transformer/usage/usage.html
category: technical_skills
updated_at: 2026-10-18
---
# Embedding 与语义检索
SentenceTransformer 将文本编码为固定维度向量。语义检索通过向量相似性寻找相关文本，不等同于严格关键词匹配，也不能保证找到的资料能回答问题。

## 查询与文档
官方提供 encode、encode_query 和 encode_document。具有不同查询和文档提示的模型应使用对应编码方法。本项目默认多语言 MiniLM 使用 encode，索引与查询使用同一个模型及归一化设置。

## 使用边界
相似度不是事实正确率。生成答案时应保留来源，并在资料不足时说明不足。过长输入可能被截断，因此分块长度要结合模型上下文限制检查。
