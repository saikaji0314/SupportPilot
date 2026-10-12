import unittest
from unittest.mock import patch

from supportpilot.cli.corpus_demo import prepare_corpus, check_isolation
from supportpilot.knowledge.retrieval import retrieve_passages
from supportpilot.agent.chat_support import with_preceding_context


class CorpusTests(unittest.TestCase):
    def test_prepare_multiple_documents_and_reject_duplicate_ids(self):
        def source(path):
            name = str(path)
            return ([{"page": 1, "text": "合成正文"}],
                    {"document_id": name, "product_id": name, "source_revision": "r"},
                    {"chunk_size": 100, "overlap": 10})
        with patch('pathlib.Path.read_text', return_value='{"sources":["a","b"]}'), \
             patch('supportpilot.cli.corpus_demo.load_source', side_effect=source):
            chunks = prepare_corpus()
            self.assertEqual(len(chunks), 2)
            self.assertNotEqual(chunks[0]['metadata']['product_id'], chunks[1]['metadata']['product_id'])
        with patch('pathlib.Path.read_text', return_value='{"sources":["a","a"]}'), \
             patch('supportpilot.cli.corpus_demo.load_source', side_effect=source):
            with self.assertRaises(ValueError):
                prepare_corpus()

    def test_real_chroma_filters_mixed_collection_and_context(self):
        import chromadb
        from uuid import uuid4
        client = chromadb.EphemeralClient()
        collection = client.create_collection('test_' + uuid4().hex, embedding_function=None)
        try:
            chunks = [{"id": f"{p}{i}", "text": "同义内容", "metadata": {
                "product_id": p, "document_id": "shared", "source_url": "https://example.test",
                "page": i, "section": 0}} for p in ('a', 'b') for i in (1, 2)]
            collection.upsert(ids=[c['id'] for c in chunks], documents=[c['text'] for c in chunks],
                metadatas=[c['metadata'] for c in chunks], embeddings=[[1., 0.] for c in chunks])
            for product in ('a', 'b', 'missing'):
                hits = retrieve_passages(collection, lambda texts: [[1., 0.]], '同一问题', product)
                passages = with_preceding_context(hits, chunks, product)
                check_isolation(passages, product, {'a', 'b'})
                self.assertEqual(bool(passages), product != 'missing')
        finally:
            client.delete_collection(collection.name)

    def test_isolation_rejects_foreign_product(self):
        with self.assertRaises(ValueError):
            check_isolation([{'product_ids': ['b']}], 'a', {'a', 'b'})


if __name__ == '__main__':
    unittest.main()
