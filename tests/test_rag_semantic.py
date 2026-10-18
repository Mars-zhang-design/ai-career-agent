"""Opt-in local-model retrieval acceptance; no LLM or business database calls.
Run: set RAG_SEMANTIC_TESTS=1 in the process environment, then unittest discover.
Build the configured knowledge index first.
"""
import os
import unittest
import rag_chroma as rag


@unittest.skipUnless(os.getenv('RAG_SEMANTIC_TESTS') == '1', 'opt-in: requires built index and cached model')
class SemanticAcceptance(unittest.TestCase):
    def test_compound_and_update_questions_have_evidence(self):
        questions = [
            'Chroma 如何持久化保存知识库？更新文档后如何处理旧片段？',
            '修改知识文件以后，原来的向量记录会重复吗？',
            '知识目录为空会清空已有索引吗？',
        ]
        for question in questions:
            with self.subTest(question=question):
                results = rag.retrieve(question)
                evidence = '\n'.join(row['content'] for row in results)
                self.assertIn('过期片段', evidence)
                self.assertIn('空目录', evidence)
                self.assertTrue(any(row['metadata']['source'] == 'technical_skills/chroma_persistence.md'
                                    for row in results))
                if question == questions[0]:
                    self.assertIn('PersistentClient', evidence)
