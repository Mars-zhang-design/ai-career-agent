import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import rag_chroma as rag


class VectorList(list):
    def tolist(self):
        return list(self)


class Encoder:
    def __init__(self):
        self.calls = 0
    def encode(self, texts, **kwargs):
        self.calls += 1
        return VectorList([[float('Python' in t), 1.0, float(len(t) % 7)] for t in texts])


class Index:
    def __init__(self):
        self.rows = {}
    def get(self, **kwargs):
        return {'ids': list(self.rows), 'metadatas': [r[1] for r in self.rows.values()]}
    def upsert(self, ids, documents, metadatas, embeddings):
        for key, text, meta, vector in zip(ids, documents, metadatas, embeddings):
            self.rows[key] = (text, meta, vector)
    def delete(self, ids):
        for key in ids:
            self.rows.pop(key)


class RagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'kb'
        self.root.mkdir()
        self.index = Index()
        self.encoder = Encoder()
        self.client = Mock()
        self.client.get_or_create_collection.return_value = self.index

    def doc(self, name='a.md', body='Python 开发。' * 30):
        p = self.root / 'technical_skills' / name
        p.parent.mkdir(exist_ok=True)
        p.write_text('---\ntitle: Python\nsource_url: https://docs.python.org/3/\n'
                     'category: technical_skills\nupdated_at: 2026-10-18\n---\n' + body, encoding='utf-8')
        return p

    def build(self):
        with patch.object(rag, 'open_client', return_value=self.client):
            return rag.build_index(self.root, Path(self.tmp.name)/'db', 'test-model', self.encoder)

    def test_idempotency_and_update(self):
        self.doc(); first = self.build(); keys = set(self.index.rows)
        second = self.build()
        self.assertGreater(first['updated'], 1)
        self.assertEqual(second['updated'], 0)
        self.assertEqual(self.encoder.calls, 1)
        self.assertEqual(keys, set(self.index.rows))
        self.doc(body='Python 更新。'); result = self.build()
        self.assertEqual(result['chunks'], 1)
        self.assertGreater(result['removed'], 0)
        self.assertEqual(next(iter(self.index.rows.values()))[0], 'Python 更新。')

    def test_removed_document_and_txt(self):
        a = self.doc(); self.doc('b.txt', '其他知识'); self.build()
        a.unlink(); result = self.build()
        self.assertGreater(result['removed'], 0)
        self.assertEqual({r[1]['source'] for r in self.index.rows.values()}, {'technical_skills/b.txt'})

    def test_empty_and_invalid_do_not_erase_index(self):
        a = self.doc(); self.build(); before = dict(self.index.rows)
        a.write_text('invalid', encoding='utf-8')
        with self.assertRaises(ValueError): self.build()
        self.assertEqual(before, self.index.rows)
        a.unlink()
        with self.assertRaises(rag.RagUnavailable): self.build()
        self.assertEqual(before, self.index.rows)

    def test_embedding_failure_preserves_existing(self):
        self.doc(); self.build(); before = dict(self.index.rows)
        self.doc(body='Changed')
        with patch.object(self.encoder, 'encode', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError): self.build()
        self.assertEqual(before, self.index.rows)

    def test_chunks_cover_text_and_bound_size(self):
        text = ''.join(chr(0x4e00 + i) for i in range(400))
        chunks = rag.chunk_text(text)
        self.assertTrue(all(len(c) <= 96 for c in chunks))
        self.assertEqual(chunks[0] + ''.join(c[16:] for c in chunks[1:]), text)

    def test_sentence_boundaries_and_parent_limits(self):
        text = '第一句讲持久化。第二句讲更新。\n\n## 维护\n第三句讲删除旧片段。'
        chunks = rag.chunk_text(text, size=18, overlap=4)
        self.assertTrue(all(not c.startswith(('。', '，')) for c in chunks))
        for sentence in ['第一句讲持久化。', '第二句讲更新。', '第三句讲删除旧片段。']:
            self.assertTrue(any(sentence in chunk for chunk in chunks))
        parents = rag.context_passages(('一个完整段落。' * 30 + '\n\n') * 8)
        self.assertTrue(all(len(parent) <= 600 for parent in parents))

    def test_compound_query_returns_context_without_duplicates(self):
        meta = {'source': 'chroma.md', 'chunk_id': 1, 'context': '持久化到磁盘。更新后删除过期片段。'}
        other = {'source': 'python.md', 'chunk_id': 1, 'context': 'Python 测试。'}
        index = Mock(); index.count.return_value = 3
        index.query.return_value = {
            'documents': [['持久化', '更新', '测试'], ['更新', '持久化', '测试']],
            'metadatas': [[meta, meta, other], [meta, meta, other]],
            'distances': [[0.1, 0.2, 0.8], [0.1, 0.2, 0.9]]}
        with patch.object(rag, 'initialize_rag'), patch.object(rag, 'collection', index), \
             patch.object(rag, 'embedding_model', Encoder()):
            result = rag.retrieve('如何持久化？更新后如何删除旧片段？')
        self.assertEqual(len(result), 2)
        self.assertIn('删除过期片段', result[0]['content'])
        self.assertNotIn('context', result[0]['metadata'])
        self.assertGreater(len(rag.query_variants('如何持久化？更新后如何删除旧片段？')), 1)

    def test_model_names_are_isolated(self):
        self.assertNotEqual(rag.collection_name('a'), rag.collection_name('b'))

    def test_missing_index_never_loads_model(self):
        with patch.object(rag, 'collection', None), patch.object(rag, 'embedding_model', None), \
             patch.object(rag, 'settings', return_value=(self.root, self.root/'missing', 'model')), \
             patch.object(rag, 'load_model') as loader:
            with self.assertRaises(rag.RagUnavailable): rag.initialize_rag()
            loader.assert_not_called()

    def test_input_validation(self):
        for query, k in [('', 3), ('x', 0), ('x', True), ('x', 1.5)]:
            with self.assertRaises(ValueError): rag.retrieve(query, k)

    def test_failure_answer_keeps_contract(self):
        with patch.object(rag, 'retrieve', side_effect=rag.RagUnavailable('索引不可用')):
            self.assertEqual(rag.rag_answer('x'), {'answer':'索引不可用','sources':[]})

    def test_empty_answer_does_not_call_llm(self):
        with patch.object(rag, 'retrieve', return_value=[]), patch('llm_service.structured_call') as llm:
            self.assertEqual(rag.rag_answer('x')['sources'], [])
            llm.assert_not_called()

    def test_sources_survive_response_schema(self):
        from schemas import RagResponse
        source = {'content':'Python', 'distance':0.1, 'metadata':{'source':'a.md','chunk_id':1,
            'title':'Python', 'source_url':'https://docs.python.org/3/',
            'category':'technical_skills','updated_at':'2026-10-18'}}
        result = RagResponse(answer='x', sources=[source]).model_dump()
        self.assertEqual(result['sources'][0]['metadata']['source_url'], source['metadata']['source_url'])

    def test_query_failure_is_sanitized(self):
        index = Mock(); index.count.return_value = 1
        index.query.side_effect = RuntimeError('private secret')
        with patch.object(rag, 'initialize_rag'), patch.object(rag, 'collection', index), \
             patch.object(rag, 'embedding_model', Encoder()):
            result = rag.rag_answer('Python')
        self.assertNotIn('private secret', result['answer'])
        self.assertEqual(result['sources'], [])

    def test_llm_failure_returns_retrieved_sources(self):
        sources = [{'content': 'Python', 'metadata': {}, 'distance': 0.1}]
        with patch.object(rag, 'retrieve', return_value=sources), \
             patch('llm_service.structured_call', side_effect=RuntimeError('private secret')):
            result = rag.rag_answer('Python')
        self.assertEqual(result['sources'], sources)
        self.assertNotIn('private secret', result['answer'])

    def test_real_chroma_persistence_and_updates(self):
        try:
            import chromadb
        except ImportError:
            self.skipTest('Chroma not installed; real storage integration unavailable')
        self.doc()
        db = Path(self.tmp.name) / 'real_db'
        # Chroma has no public close API; stop this isolated test system before Windows cleanup.
        client = rag.open_client(db)
        self.addCleanup(client._system.stop)
        first = rag.build_index(self.root, db, 'test-model', self.encoder)
        again = rag.build_index(self.root, db, 'test-model', self.encoder)
        self.assertEqual(again['updated'], 0)
        self.assertTrue((db / 'chroma.sqlite3').is_file())
        reopened = rag.open_client(db).get_collection(rag.collection_name('test-model'), embedding_function=None)
        self.assertEqual(reopened.count(), first['chunks'])
        self.doc(body='Python 最新文档')
        updated = rag.build_index(self.root, db, 'test-model', self.encoder)
        self.assertGreater(updated['removed'], 0)
        self.assertEqual(reopened.count(), 1)
        result = reopened.query(query_embeddings=self.encoder.encode(['Python']).tolist(), n_results=1)
        self.assertEqual(result['documents'][0][0], 'Python 最新文档')

    def test_repository_knowledge_has_sources(self):
        documents = rag.load_documents(rag.BASE/'knowledge_base')
        self.assertGreaterEqual(len(documents), 6)
        self.assertEqual({meta['category'] for _, meta in documents}, rag.CATEGORIES)


if __name__ == '__main__':
    unittest.main()
